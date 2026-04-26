from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from core.storage import (
    company_application_contract_path,
    company_application_nda_path,
    company_application_partnership_path,
    company_logo_path,
    get_private_storage,
    get_public_storage,
    kyc_document_path,
    user_avatar_path,
)
from master_data.models import AbstractLookup, Country

# ────────────────────────────────────────────
# Справочники модуля Accounts
# ────────────────────────────────────────────


class SystemRole(AbstractLookup):
    """
    Системная роль пользователя на уровне платформы.

    Seed: ADMIN (Platform Admin), USER (обычный пользователь компании).
    Больше ролей нет — права внутри компаний регулирует WorkspaceRole.
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Системная роль")
        verbose_name_plural = _("Справочник: Системные роли")


class CompanyType(AbstractLookup):
    """
    Тип/роль компании на платформе.
    Seed: CLIENT, MANUFACTURER, SUPPLIER, LOGISTICS_PROVIDER
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Тип компании")
        verbose_name_plural = _("Справочник: Типы компаний")


class WorkspaceRole(AbstractLookup):
    """
    Роль пользователя внутри компании.

    Роли типа-специфичные. Пример seed:
      BUYER  → OWNER, PROCUREMENT_MANAGER, MANAGER
      SELLER → OWNER, SALES_MANAGER, LOGIST
      MANUFACTURER → OWNER, CONTRACT_MANAGER, FOREIGN_TRADE_SPECIALIST

    applicable_to_types ограничивает, в каких компаниях роль можно назначить.
    Пустой набор = роль универсальная (например, OWNER).
    """

    applicable_to_types = models.ManyToManyField(
        CompanyType,
        blank=True,
        related_name="workspace_roles",
        verbose_name=_("Применимо к типам компаний"),
        help_text=_(
            "Если пусто — роль универсальна. Если указаны типы — роль " "доступна только в компаниях этих типов."
        ),
    )

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Роль в компании")
        verbose_name_plural = _("Справочник: Роли в компании")


class VerificationStatus(AbstractLookup):
    """
    Статусы верификации KYC.
    Seed: L1_UNVERIFIED, PROFILE_SUBMITTED, L2_VERIFIED, L3_CONTRACTED
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус верификации")
        verbose_name_plural = _("Справочник: Статусы верификации")


class KYCDocType(AbstractLookup):
    """
    Типы KYC-документов.
    Seed: CHARTER, LICENSE, PASSPORT, TAX_CERT, BANK_REF, OTHER
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Тип KYC документа")
        verbose_name_plural = _("Справочник: Типы KYC документов")


# ────────────────────────────────────────────
# Основные модели
# ────────────────────────────────────────────


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
    inn = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        validators=[RegexValidator(settings.INN_VALIDATION_REGEX, _("Некорректный формат ИНН."))],
        verbose_name=_("ИНН"),
        help_text=_("Идентификационный номер налогоплательщика"),
    )
    types = models.ManyToManyField(
        CompanyType,
        related_name="companies",
        blank=True,
        verbose_name=_("Роли на платформе"),
        help_text=_("Роли компании: клиент, поставщик, производитель"),
    )
    verification_status = models.ForeignKey(
        VerificationStatus,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        verbose_name=_("Статус верификации"),
        help_text=_("Текущий статус KYC-проверки компании"),
    )
    is_verified = models.BooleanField(
        default=False,
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


class CustomUser(AbstractUser):
    """
    Пользователь системы.
    Привязка к компании — через промежуточную модель CompanyMember (Multi-tenancy).
    """

    email = models.EmailField(
        unique=True,
        verbose_name=_("Email"),
        help_text=_("Основной email для входа в систему"),
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Телефон"),
        help_text=_("Мобильный или рабочий телефон"),
    )
    avatar = models.ImageField(
        upload_to=user_avatar_path,
        storage=get_public_storage,
        null=True,
        blank=True,
        verbose_name=_("Аватар"),
        help_text=_("Фото пользователя для профиля"),
    )
    role = models.ForeignKey(
        SystemRole,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        verbose_name=_("Системная роль"),
        help_text=_("Глобальная роль: определяет права доступа на всей платформе"),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = _("Пользователь")
        verbose_name_plural = _("Пользователи")

    def __str__(self):
        return self.email

    @property
    def is_platform_admin(self) -> bool:
        """
        Platform Admin — владелец платформы RailTech.

        Инвариант: is_superuser ИЛИ носитель SystemRole='ADMIN' БЕЗ активных
        членств в компаниях. Видит всё, регулирует платформу целиком.
        """
        if self.is_superuser:
            return True
        if not self.role or self.role.code != "ADMIN":
            return False
        return not self.memberships.filter(is_active=True).exists()

    @cached_property
    def primary_company(self):
        """Основная компания пользователя (is_primary=True). Кэшируется на инстанс."""
        try:
            for m in self.memberships.all():
                if m.is_primary and m.is_active:
                    return m.company
        except AttributeError:
            pass
        return None


class CompanyMember(models.Model):
    """
    Связь «Пользователь ↔ Компания» с ролью.
    Один пользователь может состоять в нескольких компаниях с разными ролями.
    """

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("Пользователь"),
        help_text=_("Участник компании"),
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name=_("Компания"),
        help_text=_("Организация, в которой состоит пользователь"),
    )
    role = models.ForeignKey(
        WorkspaceRole,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Роль в компании"),
        help_text=_("Функциональная роль внутри рабочего пространства"),
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
        help_text=_(
            "Разрешено подавать SupplierBid, управлять каталогом и офферами "
            "от лица компании. Выключается владельцем компании."
        ),
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


class KYCDocument(models.Model):
    """Документы для верификации (KYC) компании."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="kyc_documents",
        verbose_name=_("Компания"),
        help_text=_("Организация, к которой относится документ"),
    )
    doc_type = models.ForeignKey(
        KYCDocType,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Тип документа"),
        help_text=_("Вид документа из справочника (устав, лицензия, паспорт)"),
    )
    file = models.FileField(
        upload_to=kyc_document_path,
        storage=get_private_storage,
        verbose_name=_("Файл"),
        help_text=_("Загруженный скан документа (хранится в приватном хранилище)"),
    )
    original_filename = models.CharField(
        max_length=255,
        verbose_name=_("Оригинальное имя файла"),
        help_text=_("Имя файла, загруженного пользователем"),
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата загрузки"),
    )

    class Meta:
        verbose_name = _("KYC-документ")
        verbose_name_plural = _("KYC-документы")

    def __str__(self):
        return f"{self.doc_type} — {self.company.name}"


# ────────────────────────────────────────────
# Онбординг и подписки
# ────────────────────────────────────────────


class CompanyRoleApplication(models.Model):
    """
    Заявка компании на получение роли (SUPPLIER или MANUFACTURER).
    CLIENT роль назначается автоматически при регистрации.
    """

    STATUS_CHOICES = [
        ("PENDING", _("На рассмотрении")),
        ("DOCUMENTS_REQUIRED", _("Требуются документы")),
        ("PAYMENT_REQUIRED", _("Ожидание оплаты")),
        ("APPROVED", _("Одобрено")),
        ("REJECTED", _("Отклонено")),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="role_applications",
        verbose_name=_("Компания"),
        help_text=_("Организация, подавшая заявку"),
    )
    requested_type = models.ForeignKey(
        CompanyType,
        on_delete=models.PROTECT,
        related_name="applications",
        verbose_name=_("Запрашиваемая роль"),
        help_text=_("Роль, на которую подаётся заявка (SUPPLIER или MANUFACTURER)"),
    )
    status = models.CharField(
        max_length=25,
        choices=STATUS_CHOICES,
        default="PENDING",
        verbose_name=_("Статус"),
        help_text=_("Текущий статус рассмотрения заявки"),
    )
    submitted_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_applications",
        verbose_name=_("Подал заявку"),
        help_text=_("Пользователь, инициировавший заявку"),
    )

    # Documents
    contract_file = models.FileField(
        upload_to=company_application_contract_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Договор"),
        help_text=_("Подписанный договор (обязательно для SUPPLIER)"),
    )
    nda_file = models.FileField(
        upload_to=company_application_nda_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("NDA"),
        help_text=_("Соглашение о неразглашении (обязательно для SUPPLIER)"),
    )
    partnership_agreement = models.FileField(
        upload_to=company_application_partnership_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Договор о партнёрстве"),
        help_text=_("Партнёрское соглашение (обязательно для MANUFACTURER)"),
    )

    # Admin review
    reviewed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_applications",
        verbose_name=_("Рассмотрел"),
        help_text=_("Администратор, рассмотревший заявку"),
    )
    review_notes = models.TextField(
        blank=True,
        verbose_name=_("Комментарий"),
        help_text=_("Внутренний комментарий администратора"),
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Дата рассмотрения"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата подачи"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    class Meta:
        verbose_name = _("Заявка на роль компании")
        verbose_name_plural = _("Заявки на роли компаний")
        ordering = ["-created_at"]
        unique_together = [("company", "requested_type")]

    def __str__(self):
        return f"{self.company.name} → {self.requested_type.name} ({self.get_status_display()})"


class SupplierSubscription(models.Model):
    """
    Подписка поставщика на платформу.
    Тарифы до конца календарного года + ежемесячная оплата.
    """

    PLAN_CHOICES = [
        ("BASIC", _("Базовый")),
        ("STANDARD", _("Стандартный")),
        ("PREMIUM", _("Премиум")),
    ]
    STATUS_CHOICES = [
        ("TRIAL", _("Пробный период")),
        ("ACTIVE", _("Активна")),
        ("PAST_DUE", _("Просрочена")),
        ("SUSPENDED", _("Приостановлена")),
        ("CANCELLED", _("Отменена")),
    ]

    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="subscription",
        verbose_name=_("Компания"),
        help_text=_("Компания-поставщик (одна подписка на компанию)"),
    )
    plan = models.CharField(
        max_length=20,
        choices=PLAN_CHOICES,
        default="BASIC",
        verbose_name=_("Тарифный план"),
        help_text=_("Базовый, Стандартный или Премиум"),
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="TRIAL",
        verbose_name=_("Статус"),
        help_text=_("Текущее состояние подписки"),
    )

    # Billing
    monthly_rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name=_("Ежемесячная стоимость"),
        help_text=_("Сумма ежемесячного платежа"),
    )
    currency = models.ForeignKey(
        "master_data.Currency",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Валюта"),
        help_text=_("Валюта расчётов"),
    )
    valid_from = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Действует с"),
        help_text=_("Дата начала действия подписки"),
    )
    valid_until = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Действует до"),
        help_text=_("Дата окончания (обычно конец календарного года)"),
    )
    last_payment_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Последний платёж"),
        help_text=_("Дата последнего успешного платежа"),
    )
    next_payment_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Следующий платёж"),
        help_text=_("Дата ожидаемого следующего платежа"),
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("Заметки"),
        help_text=_("Внутренние заметки администратора"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата создания"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    class Meta:
        verbose_name = _("Подписка поставщика")
        verbose_name_plural = _("Подписки поставщиков")

    def __str__(self):
        return f"{self.company.name} — {self.get_plan_display()} ({self.get_status_display()})"

    @property
    def is_active(self):
        from django.utils import timezone

        today = timezone.now().date()
        return self.status == "ACTIVE" and self.valid_until and self.valid_until >= today

    @property
    def is_operational(self) -> bool:
        """Subscription permits supplier operations (ACTIVE or TRIAL within validity)."""
        from django.utils import timezone

        today = timezone.now().date()
        if self.status not in ("ACTIVE", "TRIAL"):
            return False
        if self.valid_until and self.valid_until < today:
            return False
        return True
