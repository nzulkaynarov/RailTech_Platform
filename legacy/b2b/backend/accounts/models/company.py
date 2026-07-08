import pghistory
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import company_document_profile_logo_path, company_logo_path, get_public_storage
from master_data.models import Country

# ────────────────────────────────────────────
# Справочники модуля Accounts
# ────────────────────────────────────────────


# ────────────────────────────────────────────
# Основные модели
# ────────────────────────────────────────────


@pghistory.track()  # G6: audit engineer (Unfold superuser) edits — KYC level, types, requisites
class Company(models.Model):
    """
    Юридическое лицо / Организация.
    Одна компания может быть одновременно и поставщиком, и клиентом (через M2M types).
    """

    name = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name=_("Название"),
        help_text=_("Полное наименование организации"),
    )
    # INN is deferred from registration (Phase 1) — collected later at KYC.
    # null=True keeps the unique index valid for many INN-less companies
    # (Postgres treats NULLs as distinct); the regex validator still runs once
    # an INN is actually provided.
    inn = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        validators=[RegexValidator(settings.INN_VALIDATION_REGEX, _("Некорректный формат ИНН."))],
        verbose_name=_("ИНН"),
        help_text=_("Идентификационный номер налогоплательщика"),
    )
    # INN as STATED by a seller for an offline (unverified) client — NOT unique, because
    # two sellers may independently enter the same real company before KYC (owner: "I'm
    # not afraid of duplicates — the admin merges/rejects at KYC"). The canonical, unique
    # `inn` above is assigned only when the company is verified (that's where dups surface).
    stated_inn = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        verbose_name=_("ИНН (со слов, до проверки)"),
        help_text=_("ИНН клиента, указанный продавцом; канонический ИНН присваивается на KYC"),
    )
    types = models.ManyToManyField(
        "accounts.CompanyType",
        related_name="companies",
        blank=True,
        verbose_name=_("Роли на платформе"),
        help_text=_("Роли компании: клиент, поставщик, производитель"),
    )
    verification_status = models.ForeignKey(
        "accounts.VerificationStatus",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        verbose_name=_("Статус верификации"),
        help_text=_("Текущий статус KYC-проверки компании"),
    )
    is_verified = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Верифицирован"),
        help_text=_("Компания прошла базовую проверку RailTech"),
    )
    has_iso9001 = models.BooleanField(
        default=False,
        verbose_name=_("ISO 9001"),
        help_text=_("Имеется сертификат качества ISO 9001"),
    )
    trust_score = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Индекс доверия"),
        help_text=_("Рейтинг доверия поставщика (0-100)"),
    )
    country = models.ForeignKey(
        Country,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
        verbose_name=_("Страна"),
        help_text=_("Страна регистрации юридического лица"),
    )

    # Реквизиты
    legal_address = models.TextField(
        blank=True,
        verbose_name=_("Юридический адрес"),
        help_text=_("Полный юридический адрес организации"),
    )
    bank_account = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Расчётный счёт"),
        help_text=_("Номер расчётного счёта в банке"),
    )
    mfo = models.CharField(
        max_length=10,
        blank=True,
        verbose_name=_("МФО"),
        help_text=_("Межфилиальный оборот (код банка)"),
    )
    contact_person = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Контактное лицо"),
        help_text=_("ФИО ответственного представителя компании"),
    )
    phone = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Телефон"),
        help_text=_("Контактный телефон компании"),
    )
    email = models.EmailField(
        blank=True,
        verbose_name=_("Email"),
        help_text=_("Основной email компании для уведомлений"),
    )
    website = models.URLField(
        max_length=255,
        blank=True,
        verbose_name=_("Веб-сайт"),
        help_text=_("Адрес корпоративного сайта"),
    )
    logo = models.ImageField(
        upload_to=company_logo_path,
        storage=get_public_storage,
        null=True,
        blank=True,
        verbose_name=_("Логотип"),
        help_text=_("Логотип компании для отображения на платформе"),
    )
    kyc_notes = models.TextField(
        blank=True,
        verbose_name=_("Заметки по KYC"),
        help_text=_("Внутренние заметки менеджера (не видны клиенту)"),
    )
    # False = an "offline" client a seller created in their CRM (no platform login yet).
    # Flips to True when a real user joins the company (signal / invite-accept). Lets the
    # UI and queries distinguish a rep-created account from a self-registered one.
    is_registered = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Зарегистрирована на платформе"),
        help_text=_("False — клиент заведён продавцом вручную (без входа в систему)"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата регистрации"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    class Meta:
        verbose_name = _("Компания")
        verbose_name_plural = _("Компании")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.inn})"

    @property
    def document_profile(self):
        """Get-or-create the company's branded document profile (КП / договор requisites).

        Lazily materialised so every company has a profile object to render from; the
        seller fills it in once via the OWNER endpoint. Cheap OneToOne reverse lookup.
        """
        profile = CompanyDocumentProfile.objects.filter(company=self).first()
        if profile is None:
            profile = CompanyDocumentProfile.objects.create(company=self)
        return profile

    @property
    def settings(self):
        """Get-or-create the company's КП-defaults + numbering settings row.

        Lazily materialised so every company has a settings object to read from; the
        seller fills it in via the OWNER endpoint. Cheap OneToOne reverse lookup.
        """
        row = CompanySettings.objects.filter(company=self).first()
        if row is None:
            row = CompanySettings.objects.create(company=self)
        return row


class CompanyDocumentProfile(models.Model):
    """Branded requisites a company prints on its OWN commercial documents (КП, договор).

    Tenant org-admin (OWNER) fills it once: legal name, ИНН, юр.адрес, банковские
    реквизиты, подписант, логотип, колонтитул. The КП / contract documents render the
    «Поставщик» block from this profile instead of the hardcoded platform name, so each
    selling company issues offers under its OWN brand. One profile per company.
    """

    company = models.OneToOneField(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="document_profile_rel",
        verbose_name=_("Компания"),
        help_text=_("Организация, чьи документы оформляются по этому профилю"),
    )
    logo = models.ImageField(
        upload_to=company_document_profile_logo_path,
        storage=get_public_storage,
        null=True,
        blank=True,
        verbose_name=_("Логотип для документов"),
        help_text=_("Логотип, печатаемый в шапке КП / договора"),
    )
    legal_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Полное юридическое наименование"),
        help_text=_("Наименование организации для документов (напр. ООО «РемПуть»)"),
    )
    inn = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("ИНН"),
        help_text=_("ИНН организации для реквизитов в документах"),
    )
    legal_address = models.TextField(
        blank=True,
        verbose_name=_("Юридический адрес"),
        help_text=_("Юридический адрес для реквизитов в документах"),
    )
    bank_details = models.TextField(
        blank=True,
        verbose_name=_("Банковские реквизиты"),
        help_text=_("Р/с, банк, МФО, корр. счёт и пр."),
    )
    signatory_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("ФИО подписанта"),
        help_text=_("Лицо, подписывающее документы от имени компании"),
    )
    signatory_position = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Должность подписанта"),
        help_text=_("Должность подписанта (напр. Генеральный директор)"),
    )
    footer_text = models.TextField(
        blank=True,
        verbose_name=_("Колонтитул / оговорка"),
        help_text=_("Текст внизу документа: дисклеймер, условия, контакты"),
    )
    accent_color = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Акцентный цвет"),
        help_text=_("HEX-цвет фирменного стиля для шапки документа (напр. #15294d)"),
    )
    # ── Layout toggles (P3 document-settings) — what the seller shows on its documents ──
    show_logo = models.BooleanField(
        default=True,
        verbose_name=_("Показывать логотип"),
        help_text=_("Печатать логотип в шапке документов"),
    )
    show_lead_time = models.BooleanField(
        default=True,
        verbose_name=_("Показывать колонку «Срок»"),
        help_text=_("Колонка срока поставки по позициям в КП"),
    )
    show_fx_note = models.BooleanField(
        default=False,
        verbose_name=_("Показывать курс ЦБ в КП"),
        help_text=_("Печатать курс ЦБ (FX-базис) на клиентском КП. По умолчанию скрыто — клиент видит цену в сумах."),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создан"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлён"))

    class Meta:
        verbose_name = _("Профиль документов компании")
        verbose_name_plural = _("Профили документов компаний")

    def __str__(self):
        return f"Документы: {self.company.name}"


class CompanySettings(models.Model):
    """Per-company КП defaults + the document-numbering scheme.

    The selling company sets these once (OWNER-gated). New КП built by the company
    pre-fill from `default_*` so the seller team isn't re-entering the same Incoterm,
    valuta, ставку НДС, маржу and validity on every offer. `doc_number_prefix` brands
    the company's own document numbering (contracts/invoices/acts): with prefix "ACME"
    a contract reads `ACME-CT-2026-00001`; without it the platform default `CT-2026-00001`.
    One settings row per company (get-or-create via the `Company.settings` accessor).
    """

    company = models.OneToOneField(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="settings_rel",
        verbose_name=_("Компания"),
        help_text=_("Организация, к которой относятся настройки"),
    )

    # ── КП defaults (inherited by a new Quote on CREATE only) ──────────────────
    default_delivery_basis = models.ForeignKey(
        "master_data.DeliveryBasis",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Базис поставки по умолчанию"),
        help_text=_("Incoterm, подставляемый в новый КП (FCA, CIP, DDP …)"),
    )
    default_cost_currency = models.ForeignKey(
        "master_data.Currency",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Валюта себестоимости по умолчанию"),
        help_text=_("Валюта базовой цены, наследуемая новыми позициями КП"),
    )
    default_vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Ставка НДС по умолчанию (%)"),
        help_text=_("Ставка НДС, подставляемая в новый КП"),
    )
    default_margin_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Маржа по умолчанию (%)"),
        help_text=_("Наценка на себестоимость, подставляемая в новый КП"),
    )
    default_offer_validity_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Срок действия КП по умолчанию (дней)"),
        help_text=_("Через сколько дней истекает новый КП (valid_until = сегодня + N)"),
    )
    # ── Margin governance (юнит-экономика / защита от убытка) ──────────────────
    # Both are GROSS MARGIN ON PRICE (прибыль / цена), NOT markup. The КП builder shows a
    # traffic light per line and on the deal: 🟢 ≥ target, 🟡 between floor and target,
    # 🔴 < floor. Below the floor a КП needs approval; below COST it is hard-blocked.
    min_margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=15,
        verbose_name=_("Порог маржи (%)"),
        help_text=_("Минимальная валовая маржа (на цене). Ниже — КП требует согласования."),
    )
    target_margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=25,
        verbose_name=_("Целевая маржа (%)"),
        help_text=_("Желаемая валовая маржа (на цене) — зелёная зона в конструкторе КП."),
    )

    # ── Document numbering scheme ──────────────────────────────────────────────
    doc_number_prefix = models.CharField(
        max_length=16,
        blank=True,
        verbose_name=_("Префикс нумерации документов"),
        help_text=_("Префикс номеров документов компании (напр. «ACME» → ACME-CT-2026-00001)"),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создан"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлён"))

    class Meta:
        verbose_name = _("Настройки компании")
        verbose_name_plural = _("Настройки компаний")

    def __str__(self):
        return f"Настройки: {self.company.name}"


class Contact(models.Model):
    """A person at a client company who has NO platform login (the CRM "Contact").

    World-standard Account(Company)+Contact model: a seller can record the people they
    deal with at an offline client and reuse them across deals. Distinct from
    CompanyMember (a registered user). One company has many contacts.
    """

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="contacts",
        verbose_name=_("Компания"),
        help_text=_("Организация, к которой относится контакт"),
    )
    name = models.CharField(max_length=255, verbose_name=_("ФИО"))
    email = models.EmailField(blank=True, verbose_name=_("Email"))
    phone = models.CharField(max_length=50, blank=True, verbose_name=_("Телефон"))
    position = models.CharField(max_length=255, blank=True, verbose_name=_("Должность"))
    is_primary = models.BooleanField(
        default=False,
        verbose_name=_("Основной контакт"),
        help_text=_("Контакт по умолчанию для отправки КП"),
    )
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_contacts",
        verbose_name=_("Кем создан"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Контакт")
        verbose_name_plural = _("Контакты")
        ordering = ["-is_primary", "name"]

    def clean(self):
        # World-practice rule: a contact must be reachable by at least one channel.
        from django.core.exceptions import ValidationError

        if not (self.email or self.phone):
            raise ValidationError(_("Укажите email или телефон контакта."))

    def __str__(self):
        return f"{self.name} — {self.company.name}"


class ClientInvite(models.Model):
    """A seller's invitation for an OFFLINE client to register and CLAIM its existing Company
    (CRM Phase D, spec-remaining-2026-07-07 §2.4).

    Turns the seller's offline book into registered platform users WITHOUT creating a duplicate:
    the invited person registers and, instead of a brand-new company, is attached to the existing
    `company` (which flips is_registered=True). Stateful + one-time: the raw token lives only in
    the emailed link; we store its sha256 hash for lookup, audit, and single-use enforcement.
    """

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="client_invites",
        verbose_name=_("Приглашаемая компания"),
    )
    contact = models.ForeignKey(
        "accounts.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invites",
        verbose_name=_("Контакт"),
    )
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_client_invites",
        verbose_name=_("Кем приглашён"),
    )
    email = models.EmailField(verbose_name=_("Email приглашения"))
    token_hash = models.CharField(max_length=64, unique=True, db_index=True, verbose_name=_("Хэш токена"))
    expires_at = models.DateTimeField(verbose_name=_("Истекает"))
    accepted_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Принято"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Приглашение клиента")
        verbose_name_plural = _("Приглашения клиентов")
        ordering = ["-created_at"]

    def __str__(self):
        return f"ClientInvite → {self.email} ({self.company_id})"


class CompanyRole(models.Model):
    """A company-defined role with an explicit permission set (the access matrix).

    World-standard Role+Permission-set: the company admin creates named roles and ticks
    permission checkboxes (accounts.constants.Permission). Replaces the cryptic
    can_sell/can_buy toggles. Scoped per company — each company has its own role policy.
    See Docs/dev/specs/rbac-roles-design-2026-06-25.md.
    """

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="roles",
        verbose_name=_("Компания"),
    )
    name = models.CharField(max_length=120, verbose_name=_("Название роли"))
    permissions = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Права"),
        help_text=_("Список кодов прав (accounts.constants.Permission)"),
    )
    is_system = models.BooleanField(
        default=False,
        verbose_name=_("Системная (Администратор компании)"),
        help_text=_("Полноправная роль администратора компании — нельзя удалить/урезать"),
    )
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кем создана"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Роль компании")
        verbose_name_plural = _("Роли компаний")
        ordering = ["-is_system", "name"]
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="unique_role_name_per_company"),
        ]

    def has_perm(self, code: str) -> bool:
        return self.is_system or code in (self.permissions or [])

    def __str__(self):
        return f"{self.name} — {self.company.name}"


class CompanyMember(models.Model):
    """
    Связь «Пользователь ↔ Компания» с ролью.
    Один пользователь может состоять в нескольких компаниях с разными ролями.
    """

    user = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("Пользователь"),
        help_text=_("Участник компании"),
    )
    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name=_("Компания"),
        help_text=_("Организация, в которой состоит пользователь"),
    )
    role = models.ForeignKey(
        "accounts.WorkspaceRole",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Роль в компании"),
        help_text=_("Функциональная роль внутри рабочего пространства"),
    )
    # New per-company role with an explicit permission set (Role+Permission-set model,
    # rbac-roles-design-2026-06-25). Additive: when set it drives access; `role`
    # (legacy WorkspaceRole) is kept during the transition and as a derivation fallback.
    company_role = models.ForeignKey(
        "accounts.CompanyRole",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
        verbose_name=_("Роль (с правами)"),
        help_text=_("Роль компании с набором прав; назначается администратором компании"),
    )
    is_primary = models.BooleanField(
        default=False,
        verbose_name=_("Основная компания"),
        help_text=_("Основное рабочее пространство пользователя"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активен"),
        help_text=_("Деактивированные участники не имеют доступа к компании"),
    )
    # Per-member capabilities. The company's OWNER distributes selling/buying
    # rights inside the team. Defaults are True so existing memberships keep
    # their current access; OWNER can turn flags off explicitly.
    can_sell = models.BooleanField(
        default=True,
        verbose_name=_("Может продавать"),
        help_text=_("Разрешено управлять каталогом и офферами от лица компании. " "Выключается владельцем компании."),
    )
    can_buy = models.BooleanField(
        default=True,
        verbose_name=_("Может покупать"),
        help_text=_(
            "Разрешено создавать заявки/сделки и принимать bid'ы от лица " "компании. Выключается владельцем компании."
        ),
    )
    joined_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата вступления"),
    )

    class Meta:
        verbose_name = _("Участник компании")
        verbose_name_plural = _("Участники компаний")
        unique_together = [("user", "company")]
        ordering = ["-is_primary", "joined_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_primary=True),
                name="unique_primary_company_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user.email} → {self.company.name} [{self.role}]"
