from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission
from django.utils.translation import gettext_lazy as _
from import_export.admin import ImportExportModelAdmin
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.import_export.forms import ExportForm, ImportForm
from unfold.decorators import display
from unfold.forms import UserChangeForm, UserCreationForm  # noqa: F401

from core.admin_mixins import ReadOnlyInspectionMixin, superuser_only_action

from . import services
from .models import (
    Company,
    CompanyMember,
    CompanyRoleApplication,
    CompanyType,
    CustomUser,
    KYCDocType,
    KYCDocument,
    SupplierSubscription,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from .resources import CompanyResource, UserResource

admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(ModelAdmin):
    """Django auth Group — оставлен для инженерной инспекции.

    В RailTech бизнес-RBAC живёт в SystemRole + CompanyMember.role (ADR-0002),
    Django Groups НЕ используются для проверки прав в services.py. Этот экран —
    для DBA, который хочет понять, какие Django-разрешения выданы группе.
    """

    list_display = ("name", "permissions_count")
    search_fields = ("name",)
    filter_horizontal = ("permissions",)
    list_per_page = 25

    @display(description=_("Разрешений"))
    def permissions_count(self, obj):
        return obj.permissions.count()

    def get_queryset(self, request):
        # Аннотация через raw SQL была бы оптимальнее, но Group.permissions.count()
        # вызывается только при рендере ~25 строк — дешевле, чем subquery.
        return super().get_queryset(request).prefetch_related("permissions")


@admin.register(Permission)
class PermissionAdmin(ModelAdmin):
    """Django Permission — 4 авто-разрешения на каждый ContentType (add/change/delete/view).

    В RailTech НЕ используется для проверки бизнес-прав (услуги проверяют
    is_member_of / role.code). Этот экран нужен только чтобы понять, что Django
    знает о каждой модели — отладка, не повседневное использование.
    """

    list_display = ("permission_name", "app_label_col", "model_col", "codename")
    list_filter = ("content_type__app_label", "content_type__model")
    list_filter_submit = True
    search_fields = ("name", "codename", "content_type__app_label", "content_type__model")
    list_select_related = ("content_type",)
    list_per_page = 50
    show_full_result_count = False

    @display(description=_("Разрешение"), ordering="name")
    def permission_name(self, obj):
        # Bypass Permission.__str__ which dereferences content_type and would
        # crash on any orphaned FK; just return the name field directly.
        return obj.name

    @display(description=_("Приложение"), ordering="content_type__app_label")
    def app_label_col(self, obj):
        ct = getattr(obj, "content_type", None)
        return ct.app_label if ct else "—"

    # Name is `model_col`, NOT `model` — ModelAdmin.model already shadows any
    # list_display entry called "model" (it's the admin's bound model class),
    # and Django's lookup_field resolves to the class, not to this callable.
    @display(description=_("Модель"), ordering="content_type__model")
    def model_col(self, obj):
        ct = getattr(obj, "content_type", None)
        return ct.model if ct else "—"


# ────────────────────────────────────────────
# Inlines
# ────────────────────────────────────────────


class CompanyMemberInline(TabularInline):
    model = CompanyMember
    extra = 0
    show_change_link = True
    tab = True
    fields = ["user", "role", "is_primary", "is_active", "joined_at"]
    readonly_fields = ["joined_at"]
    autocomplete_fields = ["company", "role", "user"]


class KYCDocumentInline(TabularInline):
    model = KYCDocument
    extra = 0
    show_change_link = True
    tab = True
    fields = ["doc_type", "file", "original_filename", "uploaded_at"]
    readonly_fields = ["uploaded_at", "original_filename"]
    autocomplete_fields = ["doc_type"]


# ────────────────────────────────────────────
# Lookups
# ────────────────────────────────────────────


@admin.register(SystemRole, WorkspaceRole, CompanyType, VerificationStatus, KYCDocType)
class LookupAdmin(ModelAdmin):
    list_display = ["name", "code", "sort_order", "is_active"]
    list_editable = ["sort_order", "is_active"]
    search_fields = ["name", "code"]
    list_per_page = 25


# ────────────────────────────────────────────
# Users
# ────────────────────────────────────────────


@admin.register(CustomUser)
class UserAdmin(ImportExportModelAdmin, BaseUserAdmin, ModelAdmin):
    resource_classes = [UserResource]
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ("show_user", "role_badge", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    list_filter_submit = True
    search_fields = ("email", "first_name", "last_name", "phone", "username")
    list_per_page = 25
    list_select_related = ("role",)
    inlines = [CompanyMemberInline]
    warn_unsaved_form = True

    @display(header=True, description=_("Пользователь"))
    def show_user(self, obj):
        name = obj.get_full_name() or obj.username
        return [name, obj.email]

    @display(
        description=_("Роль"),
        label={
            "Администратор платформы": "danger",
            "Пользователь": "info",
        },
    )
    def role_badge(self, obj):
        return obj.role.name if obj.role else "—"

    fieldsets = (
        (
            None,
            {
                "fields": (("email", "password"),),
            },
        ),
        (
            _("Профиль"),
            {
                "classes": ["tab"],
                "fields": (
                    ("first_name", "last_name"),
                    ("username", "phone"),
                    "avatar",
                ),
            },
        ),
        (
            _("Доступ"),
            {
                "classes": ["tab"],
                "fields": (
                    ("is_active", "is_staff", "is_superuser"),
                    "role",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
    )
    filter_horizontal = ("groups", "user_permissions")
    autocomplete_fields = ("role",)

    #: Поля, которыми человек поднимает СЕБЕ или другому уровень доступа на всю платформу.
    PRIVILEGE_FIELDS = ("is_superuser", "is_staff", "groups", "user_permissions")

    def get_readonly_fields(self, request, obj=None):
        """Привилегированный блок редактирует ТОЛЬКО суперпользователь.

        Прогон 20-08: инженер с правом `accounts.change_customuser` открывал форму пользователя и
        сохранял себе `is_superuser=True` — тремя кликами, без следа и без второго человека.
        Django-админка сама такой защиты не даёт: право на модель означает право на ВСЕ её поля.

        Ровно так же поступает сам Django в `contrib.auth.admin.UserAdmin` (`get_form`: поле
        `user_permissions` прячется от того, кто не суперпользователь) — здесь мы распространяем
        тот же принцип на весь блок эскалации, включая членство в группах: `system_engineers`
        открывает инженерную админку, и раздавать её должен тот же, кто раздаёт суперправа.
        """
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            readonly.extend(field for field in self.PRIVILEGE_FIELDS if field not in readonly)
        return tuple(readonly)


# ────────────────────────────────────────────
# Companies
# ────────────────────────────────────────────


@admin.register(Company)
class CompanyAdmin(ReadOnlyInspectionMixin, ImportExportModelAdmin, ModelAdmin):
    resource_classes = [CompanyResource]
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ("name", "inn", "status_badge", "types_display", "country", "created_at")
    list_filter = ("verification_status", "types", "country")
    list_filter_submit = True
    search_fields = ("name", "inn")
    list_per_page = 25
    list_select_related = ("verification_status", "country")
    inlines = [CompanyMemberInline, KYCDocumentInline]
    autocomplete_fields = ["verification_status", "country", "types"]
    # Business actions moved to React Admin — this action kept ONLY as emergency
    # engineering escape-hatch (superuser-only). Use /admin/kyc/ in React SPA instead.
    actions = ["verify_kyc"]
    warn_unsaved_form = True

    # Уровень KYC — БИЗНЕС-действие с обязательным следом, а не поле формы. В инженерной
    # админке оно правилось обычным «Сохранить»: суперпользователь ставил L2_VERIFIED мимо
    # сервиса, без обоснования и без единой строки в журнале — при том что pre-save сигнал
    # всё равно слал владельцам письмо о смене статуса, то есть уведомление приходило о
    # выдаче, следа которой не существует. Поле закрыто ДЛЯ ВСЕХ, включая суперпользователя:
    # выдаёт уровень панель оператора, а здесь остаётся аварийное действие `verify_kyc`,
    # которое идёт через сервис (ADR-0001: Unfold — инженерам, бизнес-операции — в React
    # Admin). Найдено скептиком при проверке волны «гейт обоснования», 24-08.
    KYC_STATE_FIELDS = ("verification_status", "is_verified")

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is None:
            # На создании поля ещё нет смысла: новая компания рождается неверифицированной.
            return readonly
        for field in self.KYC_STATE_FIELDS:
            if field not in readonly:
                readonly.append(field)
        return readonly

    def get_queryset(self, request):
        # Prefetch M2M `types` so types_display() doesn't issue 1 query per row.
        return super().get_queryset(request).prefetch_related("types")

    @display(
        description=_("Статус KYC"),
        label={
            "Не верифицирован": "danger",
            "Профиль на проверке": "warning",
            "KYC подтверждён": "success",
            "Договор заключён": "info",
            "Отклонён": "danger",
        },
    )
    def status_badge(self, obj):
        return obj.verification_status.name if obj.verification_status else "—"

    @display(description=_("Роли"))
    def types_display(self, obj):
        types = obj.types.all()
        return ", ".join(t.name for t in types) if types else "—"

    @superuser_only_action(_("[Emergency] Подтвердить KYC (L2)"))
    def verify_kyc(self, request, queryset):
        # Обоснования у аварийного действия быть не может — у действия Django нет формы, а
        # подставить его от имени человека значит подделать след. Поэтому компании с неполными
        # доказательствами сервис здесь ОТКЛОНИТ (`KYC_REASON_REQUIRED_WITHOUT_EVIDENCE`), а
        # сообщение отправит оператора туда, где обоснование записывается, — в панель оператора
        # (ADR-0001: Unfold — инженерам, бизнес-действия — в React Admin).
        approved, skipped = services.bulk_verify_kyc(queryset, request.user, level_code="L2_VERIFIED")
        if skipped:
            # `skipped` — список СЛОВАРЕЙ {company_id, name, error}; строковый join по нему
            # падал в TypeError, то есть аварийное действие ломалось ровно в тот момент, когда
            # ему было что сказать оператору (найдено 24-08 при простановке гейта обоснования).
            self.message_user(
                request,
                _(
                    "Не подтверждено (%(names)s). Выдать уровень без документов можно из панели "
                    "оператора — там записывается обоснование."
                )
                % {"names": ", ".join(f"{item['name']}: {item['error']}" for item in skipped)},
                level="warning",
            )
        if approved:
            self.message_user(request, _("%(count)d компаний подтверждено.") % {"count": approved})

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("name", "inn"),
                    ("verification_status", "country"),
                    "types",
                ),
            },
        ),
        (
            _("Контакты"),
            {
                "classes": ["tab"],
                "fields": (
                    ("contact_person", "phone"),
                    ("email", "website"),
                    "legal_address",
                    "logo",
                ),
            },
        ),
        (
            _("Банк"),
            {
                "classes": ["tab"],
                "fields": (("bank_account", "mfo"),),
            },
        ),
        (
            _("KYC"),
            {
                "classes": ["tab"],
                "fields": ("kyc_notes",),
            },
        ),
    )


@admin.register(KYCDocument)
class KYCDocumentAdmin(ModelAdmin):
    list_display = ("company", "doc_type", "original_filename", "uploaded_at")
    list_filter = ("doc_type",)
    list_filter_submit = True
    search_fields = ("company__name", "original_filename")
    autocomplete_fields = ["company", "doc_type"]
    readonly_fields = ["uploaded_at", "original_filename"]
    list_per_page = 25
    list_select_related = ("company", "doc_type")
    show_full_result_count = False

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("company", "doc_type"),
                    ("file", "original_filename"),
                    "uploaded_at",
                ),
            },
        ),
    )


# ────────────────────────────────────────────
# Role Applications
# ────────────────────────────────────────────


@admin.register(CompanyRoleApplication)
class CompanyRoleApplicationAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("company", "requested_type", "app_status", "submitted_by", "reviewed_by", "created_at")
    list_filter = ("status", "requested_type", "created_at")
    list_filter_submit = True
    search_fields = ("company__name", "company__inn")
    autocomplete_fields = ["company", "requested_type", "submitted_by", "reviewed_by"]
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 25
    list_select_related = ("company", "requested_type", "submitted_by", "reviewed_by")
    actions = ["approve_application", "reject_application"]
    warn_unsaved_form = True

    @display(
        description=_("Статус"),
        label={
            "На рассмотрении": "warning",
            "Требуются документы": "info",
            "Ожидание оплаты": "info",
            "Одобрено": "success",
            "Отклонено": "danger",
        },
    )
    def app_status(self, obj):
        return obj.get_status_display()

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("company", "requested_type"),
                    ("status", "submitted_by"),
                ),
            },
        ),
        (
            _("Документы"),
            {
                "classes": ["tab"],
                "fields": (
                    "contract_file",
                    "nda_file",
                    "partnership_agreement",
                ),
            },
        ),
        (
            _("Рассмотрение"),
            {
                "classes": ["tab"],
                "fields": (
                    ("reviewed_by", "reviewed_at"),
                    "review_notes",
                    ("created_at", "updated_at"),
                ),
            },
        ),
    )

    @superuser_only_action(_("[Emergency] Одобрить (с проверкой документов)"))
    def approve_application(self, request, queryset):
        approved, errors = services.bulk_approve_role_applications(queryset, request.user)
        if errors:
            self.message_user(request, "\n".join(errors), level="warning")
        if approved:
            self.message_user(request, _("%(count)d заявок одобрено.") % {"count": approved})

    @superuser_only_action(_("[Emergency] Отклонить"))
    def reject_application(self, request, queryset):
        rejected, errors = services.bulk_reject_role_applications(queryset, request.user)
        if errors:
            self.message_user(request, "\n".join(errors), level="warning")
        self.message_user(request, _("%(count)d заявок отклонено.") % {"count": rejected})


# ────────────────────────────────────────────
# Subscriptions
# ────────────────────────────────────────────


@admin.register(SupplierSubscription)
class SupplierSubscriptionAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("company", "plan_badge", "sub_status", "monthly_rate", "currency", "valid_until")
    list_filter = ("plan", "status")
    list_filter_submit = True
    search_fields = ("company__name", "company__inn")
    autocomplete_fields = ["company", "currency"]
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 25
    list_select_related = ("company", "currency")
    actions = ["activate_subscription", "suspend_subscription"]
    warn_unsaved_form = True

    @display(
        description=_("План"),
        label={"Базовый": "info", "Стандартный": "warning", "Премиум": "success"},
    )
    def plan_badge(self, obj):
        return obj.get_plan_display()

    @display(
        description=_("Статус"),
        label={
            "Пробный период": "info",
            "Активна": "success",
            "Просрочена": "danger",
            "Приостановлена": "warning",
            "Отменена": "danger",
        },
    )
    def sub_status(self, obj):
        return obj.get_status_display()

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "company",
                    ("plan", "status"),
                ),
            },
        ),
        (
            _("Биллинг"),
            {
                "classes": ["tab"],
                "fields": (
                    ("monthly_rate", "currency"),
                    ("valid_from", "valid_until"),
                    ("last_payment_date", "next_payment_date"),
                ),
            },
        ),
        (
            _("Заметки"),
            {
                "classes": ["tab"],
                "fields": (
                    "notes",
                    ("created_at", "updated_at"),
                ),
            },
        ),
    )

    @superuser_only_action(_("[Emergency] Активировать"))
    def activate_subscription(self, request, queryset):
        updated = services.change_subscription_status(queryset, "ACTIVE")
        self.message_user(request, _("%(count)d активировано.") % {"count": updated})

    @superuser_only_action(_("[Emergency] Приостановить"))
    def suspend_subscription(self, request, queryset):
        updated = services.change_subscription_status(queryset, "SUSPENDED")
        self.message_user(request, _("%(count)d приостановлено.") % {"count": updated})
