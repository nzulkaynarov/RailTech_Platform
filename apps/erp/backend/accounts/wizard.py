"""
Company creation wizard — 4-step form for django admin.

Steps:
  1. Requisites: name, INN, country, logo
  2. Contacts: address, phone, email, bank details
  3. Role: company types, verification status
  4. Members: add owner (existing user or create new)
"""

import logging

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.tokens import default_token_generator
from django.core.files.storage import default_storage
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext_lazy as _
from formtools.wizard.views import SessionWizardView

from master_data.models import Country

from .constants import VerificationStatusCode
from .models import Company, CompanyMember, CompanyType, CustomUser, VerificationStatus, WorkspaceRole

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────
# Step forms
# ────────────────────────────────────────────


class Step1RequisitesForm(forms.Form):
    """Шаг 1: Реквизиты."""

    name = forms.CharField(
        max_length=255,
        label=_("Название компании"),
        help_text=_("Полное наименование организации"),
    )
    inn = forms.CharField(
        max_length=20,
        label=_("ИНН"),
        help_text=_("Идентификационный номер налогоплательщика"),
    )
    country = forms.ModelChoiceField(
        queryset=Country.objects.all().order_by("sort_order", "name"),
        label=_("Страна регистрации"),
        # Подсказка обещала, что страна «определяет ставку НДС», — это неправда: ставку КП
        # берёт из настроек компании (`CompanySettings.default_vat_rate`), а `Country.vat_rate`
        # ценообразование не читает. Оператор выбирал страну, ожидая несуществующего эффекта.
        help_text=_("Страна регистрации юридического лица"),
        required=False,
    )
    logo = forms.ImageField(
        label=_("Логотип"),
        required=False,
        help_text=_("Логотип компании (PNG, JPG, SVG)"),
    )

    def clean_inn(self):
        inn = self.cleaned_data["inn"]
        if Company.objects.filter(inn=inn).exists():
            raise forms.ValidationError(_("Компания с таким ИНН уже существует."))
        return inn


class Step2ContactsForm(forms.Form):
    """Шаг 2: Контакты и реквизиты."""

    legal_address = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
        label=_("Юридический адрес"),
    )
    contact_person = forms.CharField(
        max_length=255,
        required=False,
        label=_("Контактное лицо"),
        help_text=_("ФИО ответственного представителя"),
    )
    phone = forms.CharField(
        max_length=50,
        required=False,
        label=_("Телефон"),
    )
    email = forms.EmailField(
        required=False,
        label=_("Email"),
        help_text=_("Для уведомлений и переписки"),
    )
    website = forms.URLField(
        required=False,
        label=_("Веб-сайт"),
    )
    bank_account = forms.CharField(
        max_length=50,
        required=False,
        label=_("Расчётный счёт"),
    )
    mfo = forms.CharField(
        max_length=10,
        required=False,
        label=_("МФО"),
        help_text=_("Код банка"),
    )


class Step3RoleForm(forms.Form):
    """Шаг 3: Роль на платформе."""

    types = forms.ModelMultipleChoiceField(
        queryset=CompanyType.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        label=_("Роли компании"),
        help_text=_(
            "Выберите одну или несколько ролей. "
            "Клиент — покупает товары. Поставщик — продаёт. "
            "Производитель — OEM."
        ),
    )
    # Мастер ЗАВОДИТ арендатора, а не верифицирует его: выдача L2+ — отдельное действие с
    # обоснованием и следом в журнале (политика владельца 2026-06-03, сервис
    # `verify_company_kyc`). Раньше здесь можно было выбрать любой уровень, включая
    # L2_VERIFIED, и компания рождалась подтверждённой без документов, без причины и без
    # единой строки аудита. Оставлены только уровни ДО верификации.
    verification_status = forms.ModelChoiceField(
        queryset=VerificationStatus.objects.filter(
            code__in=[VerificationStatusCode.L1_UNVERIFIED, VerificationStatusCode.PROFILE_SUBMITTED]
        ),
        label=_("Статус верификации"),
        required=False,
        help_text=_(
            "Начальный статус KYC. По умолчанию — не верифицирован. "
            "Подтверждение уровня L2 и выше выдаётся в панели оператора: там записывается обоснование."
        ),
    )
    kyc_notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label=_("Заметки по KYC"),
        help_text=_("Внутренние комментарии (не видны клиенту)"),
    )


class Step4MembersForm(forms.Form):
    """Шаг 4: Владелец/администратор компании."""

    owner_email = forms.EmailField(
        label=_("Email владельца"),
        help_text=_(
            "Если пользователь с таким email уже есть — он будет привязан. " "Если нет — будет создан новый аккаунт."
        ),
    )
    owner_first_name = forms.CharField(
        max_length=150,
        required=False,
        label=_("Имя"),
    )
    owner_last_name = forms.CharField(
        max_length=150,
        required=False,
        label=_("Фамилия"),
    )
    owner_phone = forms.CharField(
        max_length=20,
        required=False,
        label=_("Телефон владельца"),
    )


# ────────────────────────────────────────────
# Wizard view
# ────────────────────────────────────────────

WIZARD_FORMS = [
    ("requisites", Step1RequisitesForm),
    ("contacts", Step2ContactsForm),
    ("role", Step3RoleForm),
    ("members", Step4MembersForm),
]


class CompanyWizardView(SessionWizardView):
    template_name = "admin/accounts/company_wizard.html"
    file_storage = default_storage

    def dispatch(self, request, *args, **kwargs):
        # Тот же гейт, что у самой админки (`core.admin_site.EngineeringAdminSite`), а не голый
        # `is_staff`: мастер живёт внутри Unfold и создаёт компании — пускать сюда шире, чем в
        # админку, значит оставить обходную дверь.
        from django.contrib.admin import site
        from django.core.exceptions import PermissionDenied

        if not site.has_permission(request):
            return redirect("/admin/login/")
        # Вход в админку и СОЗДАНИЕ АРЕНДАТОРА — разные вещи, и Django ровно так их разделяет.
        #
        # Гейт двери (волна 20-08) пускает сюда суперпользователя ИЛИ члена `system_engineers`.
        # Этого мало: мастер заводит компанию и сразу проставляет ей `verification_status`, то
        # есть уровень KYC. Прогон 20-08 показал, что член группы БЕЗ ЕДИНОГО модельного права
        # (`get_all_permissions() == []`) проходил мастер до конца и создавал арендатора с
        # выставленным KYC. Модельное право — тот самый второй ключ.
        if not request.user.has_perm("accounts.add_company"):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add admin site context for base_site.html
        from django.contrib.admin import site

        context.update(site.each_context(self.request))
        context["title"] = _("Создание компании")
        return context

    def done(self, form_list, form_dict, **kwargs):
        """Create company + owner membership after all steps."""
        data = {}
        for form in form_list:
            data.update(form.cleaned_data)

        # Create company
        company = Company.objects.create(
            name=data["name"],
            inn=data["inn"],
            country=data.get("country"),
            logo=data.get("logo"),
            legal_address=data.get("legal_address", ""),
            contact_person=data.get("contact_person", ""),
            phone=data.get("phone", ""),
            email=data.get("email", ""),
            website=data.get("website", ""),
            bank_account=data.get("bank_account", ""),
            mfo=data.get("mfo", ""),
            verification_status=data.get("verification_status"),
            kyc_notes=data.get("kyc_notes", ""),
        )

        # Set company types
        types = data.get("types")
        if types:
            company.types.set(types)

        # Create or get owner
        owner_email = data["owner_email"]
        from accounts.constants import SystemRoleCode
        from accounts.models import SystemRole

        # `code="CLIENT"` НЕ СУЩЕСТВУЕТ: роли сведены к двум (ADMIN/USER), а CLIENT вычищен
        # миграцией `accounts/0044_purge_retired_roles_after_core_seed`. `.first()` на пустой
        # выборке молча отдавал None, и владелец компании, заведённый оператором через мастер,
        # оставался БЕЗ системной роли — в отличие от точно такого же владельца, пришедшего
        # через регистрацию (`accounts/services/auth.py` ставит USER). В реестре пользователей
        # он не попадал ни под один фильтр по роли, а `/me` отдавал `role_data: null`.
        #
        # `.get()`, а не `.filter().first()` — по Rule 1: роль сеется миграцией, и её отсутствие
        # означает неприменённую миграцию, о которой надо узнать сразу, а не получить None.
        owner_role = SystemRole.objects.get(code=SystemRoleCode.USER)

        user, created = CustomUser.objects.get_or_create(
            email=owner_email,
            defaults={
                "username": owner_email,
                "first_name": data.get("owner_first_name", ""),
                "last_name": data.get("owner_last_name", ""),
                "phone": data.get("owner_phone", ""),
                "role": owner_role,
                "is_active": False,
            },
        )
        if created:
            user.set_unusable_password()
            user.save()
            # Send setup-password email (same flow as registration)
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            base_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173")
            setup_url = f"{base_url}/setup-password?uid={uid}&token={token}"
            try:
                from notifications.emails import send_templated_email

                send_templated_email(
                    "setup_password",
                    {
                        "first_name": data.get("owner_first_name", ""),
                        "setup_url": setup_url,
                    },
                    to=[owner_email],
                    channel="transactional",
                    user=user,
                    fail_silently=True,
                )
            except Exception:  # noqa: BLE001 — fault barrier: best-effort email must not break company creation
                logger.exception(f"Failed to send setup email to {owner_email}")

        # Create membership
        owner_role = WorkspaceRole.objects.filter(code="OWNER").first()
        if owner_role:
            CompanyMember.objects.get_or_create(
                user=user,
                company=company,
                defaults={
                    "role": owner_role,
                    "is_primary": True,
                    "is_active": True,
                },
            )

        messages.success(
            self.request,
            _("Компания «%(name)s» успешно создана! " "Владелец: %(email)s")
            % {
                "name": company.name,
                "email": owner_email,
            },
        )

        # Дверь в мастер открывает `accounts.add_company` (гейт в `dispatch`), а страница
        # компании требует `view_company`/`change_company`. У актора ровно с правом «заводить»
        # мастер отрабатывал до конца — и выбрасывал его на голый 403: компания создана,
        # сообщение об успехе не показано, вернуться некуда.
        #
        # Приём самой Django (`ModelAdmin.response_post_save_add`): вести на страницу объекта,
        # только если актор её откроет, иначе — на главную админки, где сообщение об успехе он
        # увидит.
        user = self.request.user
        if user.has_perm("accounts.view_company") or user.has_perm("accounts.change_company"):
            return redirect(f"/admin/accounts/company/{company.pk}/change/")
        return redirect(reverse("admin:index"))
