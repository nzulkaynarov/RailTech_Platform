"""Single source of truth for accounts lookup CODES.

These mirror the `code` of seeded lookup rows (WorkspaceRole, SystemRole,
CompanyType, VerificationStatus). Reference these constants in business logic
instead of bare string literals — a typo becomes an AttributeError, not a silent
runtime miss. The rows themselves still live in the DB (names, i18n, sort_order);
this is just the stable contract between code and data.

NB: do NOT import this from migrations — migrations must stay frozen.
"""

from django.db import models


class WorkspaceRoleCode(models.TextChoices):
    OWNER = "OWNER", "Владелец"
    SALES_MANAGER = "SALES_MANAGER", "Менеджер по продажам"
    DIRECTOR = "DIRECTOR", "Директор"
    FOREIGN_TRADE_SPECIALIST = "FOREIGN_TRADE_SPECIALIST", "Менеджер ВЭД"
    LOGIST = "LOGIST", "Логист"
    CONTRACT_MANAGER = "CONTRACT_MANAGER", "Договорник"
    PROCUREMENT_MANAGER = "PROCUREMENT_MANAGER", "Менеджер закупок"
    BUYER_MANAGER = "BUYER_MANAGER", "Менеджер покупателя"
    MEMBER = "MEMBER", "Участник"


class Permission(models.TextChoices):
    """Company-level capability codes — the checkboxes a company admin ticks on a role.
    World-standard Role+Permission-set model (replaces the raw can_sell/can_buy toggles).
    Sensitive-first: cost/margin visibility, money, signing, exports, team management."""

    # Sales / КП
    QUOTE_BUILD = "quote.build", "Строить КП"
    QUOTE_SEND = "quote.send", "Отправлять КП клиенту"
    QUOTE_VIEW_COST_MARGIN = "quote.view_cost_margin", "Видеть себестоимость и маржу"
    QUOTE_EDIT_PRICING = "quote.edit_pricing", "Менять цены и скидки"
    # Internal КП approval chain (NEW — distinct from quote.approve, which is the BUYER's
    # accept/reject). quote.review = intermediate approver; quote.approve_final = the mandatory
    # final approver («руководитель»). The company admin role carries both by default.
    QUOTE_REVIEW = "quote.review", "Согласовывать КП (промежуточно)"
    QUOTE_APPROVE_FINAL = "quote.approve_final", "Финально утверждать КП (руководитель)"
    # Procurement / Buyer
    REQUEST_CREATE = "request.create", "Создавать заявки"
    QUOTE_APPROVE = "quote.approve", "Принимать/отклонять КП"
    CONTRACT_SIGN = "contract.sign", "Подписывать контракты"
    PAYMENT_RECORD = "payment.record", "Проводить платежи"
    # Catalog
    CATALOG_MANAGE = "catalog.manage", "Управлять каталогом и офферами"
    CATALOG_PUBLISH = "catalog.publish", "Публиковать товары"
    # Company admin
    TEAM_MANAGE = "team.manage", "Управлять командой и ролями"
    SETTINGS_EDIT = "settings.edit", "Менять настройки компании"
    CHARGE_TEMPLATES_MANAGE = "charge_templates.manage", "Управлять шаблонами статей"
    # Data
    DATA_EXPORT = "data.export", "Экспортировать данные"


# Grouping for the settings UI (the checkbox sections).
PERMISSION_GROUPS = {
    "sales": [
        Permission.QUOTE_BUILD,
        Permission.QUOTE_SEND,
        Permission.QUOTE_VIEW_COST_MARGIN,
        Permission.QUOTE_EDIT_PRICING,
        Permission.QUOTE_REVIEW,
        Permission.QUOTE_APPROVE_FINAL,
    ],
    "procurement": [
        Permission.REQUEST_CREATE,
        Permission.QUOTE_APPROVE,
        Permission.CONTRACT_SIGN,
        Permission.PAYMENT_RECORD,
    ],
    "catalog": [Permission.CATALOG_MANAGE, Permission.CATALOG_PUBLISH],
    "company": [Permission.TEAM_MANAGE, Permission.SETTINGS_EDIT, Permission.CHARGE_TEMPLATES_MANAGE],
    "data": [Permission.DATA_EXPORT],
}

ALL_PERMISSIONS = [p.value for p in Permission]

# Seeded default role templates (starting points; a company can clone/rename/edit).
# The "Company administrator" template is the immutable full-rights role (never-orphan).
COMPANY_ADMIN_ROLE_NAME = "Администратор компании"
ROLE_TEMPLATES = {
    COMPANY_ADMIN_ROLE_NAME: ALL_PERMISSIONS,
    "Менеджер по продажам": [
        Permission.QUOTE_BUILD.value,
        Permission.QUOTE_SEND.value,
        Permission.QUOTE_VIEW_COST_MARGIN.value,
        Permission.QUOTE_EDIT_PRICING.value,
        Permission.CATALOG_MANAGE.value,
    ],
    "Менеджер закупок": [
        Permission.REQUEST_CREATE.value,
        Permission.QUOTE_APPROVE.value,
        Permission.CONTRACT_SIGN.value,
        Permission.PAYMENT_RECORD.value,
    ],
    "Финансы": [
        Permission.PAYMENT_RECORD.value,
        Permission.QUOTE_VIEW_COST_MARGIN.value,
        Permission.DATA_EXPORT.value,
    ],
    "Наблюдатель": [],
}


class SystemRoleCode(models.TextChoices):
    ADMIN = "ADMIN", "Администратор платформы"
    USER = "USER", "Пользователь"


# ──────────────────────────────────────────────────────────────────────────
# Platform Operator plane (ADR-0004 G1) — granular operator sub-roles.
#
# The Platform Operator (SystemRole.ADMIN, no CompanyMember) was a monolith: one
# all-powerful ADMIN doing KYC + billing + moderation + force-overrides. G1 splits
# that into least-privilege sub-roles. This is PLATFORM-scoped (NOT a CompanyRole):
# it gates which platform-staff actions an operator may take, never tenant operations
# (ADMIN_VIEWER_CANNOT_ACT still forbids acting on behalf of a company).
# ──────────────────────────────────────────────────────────────────────────


class OperatorRoleCode(models.TextChoices):
    """Stable codes for the seeded operator sub-roles. SUPER_OPERATOR == the legacy
    all-powerful ADMIN (backward compatible)."""

    SUPPORT = "SUPPORT", "Поддержка"
    KYC_OFFICER = "KYC_OFFICER", "Офицер KYC"
    BILLING_OPERATOR = "BILLING_OPERATOR", "Оператор биллинга"
    MODERATOR = "MODERATOR", "Модератор"
    SUPER_OPERATOR = "SUPER_OPERATOR", "Супероператор"


class OperatorPermission(models.TextChoices):
    """Platform-staff capability codes — what an operator sub-role may do.
    Sensitive-first: KYC verification, billing changes, moderation, force-overrides,
    operator-role administration. Compared by code; never by translated name."""

    # Users
    USERS_VIEW = "users.view", "Просматривать пользователей"
    USERS_MANAGE = "users.manage", "Управлять пользователями (блок/роль)"
    # Companies
    COMPANIES_VIEW = "companies.view", "Просматривать компании"
    COMPANIES_MANAGE = "companies.manage", "Управлять компаниями"
    # KYC
    KYC_VIEW = "kyc.view", "Просматривать KYC и документы"
    KYC_VERIFY = "kyc.verify", "Верифицировать KYC (L1→L3)"
    # Billing
    BILLING_VIEW = "billing.view", "Просматривать подписки и счета"
    BILLING_MANAGE = "billing.manage", "Управлять подписками и платежами"
    # Moderation
    MODERATION_ROLE_APPLICATIONS = "moderation.role_applications", "Модерация заявок на роли"
    MODERATION_FORCE_OVERRIDE = "moderation.force_override", "Force-override (сделки/КП/контракты)"
    # Platform
    PLATFORM_SETTINGS = "platform.settings", "Системные настройки и справочники"
    OPERATORS_MANAGE = "operators.manage", "Управлять ролями операторов"


# Grouping for the operator-role editor UI (the checkbox sections).
OPERATOR_PERMISSION_GROUPS = {
    "users": [OperatorPermission.USERS_VIEW, OperatorPermission.USERS_MANAGE],
    "companies": [OperatorPermission.COMPANIES_VIEW, OperatorPermission.COMPANIES_MANAGE],
    "kyc": [OperatorPermission.KYC_VIEW, OperatorPermission.KYC_VERIFY],
    "billing": [OperatorPermission.BILLING_VIEW, OperatorPermission.BILLING_MANAGE],
    "moderation": [OperatorPermission.MODERATION_ROLE_APPLICATIONS, OperatorPermission.MODERATION_FORCE_OVERRIDE],
    "platform": [OperatorPermission.PLATFORM_SETTINGS, OperatorPermission.OPERATORS_MANAGE],
}

ALL_OPERATOR_PERMISSIONS = [p.value for p in OperatorPermission]

# Seeded operator sub-role presets (ADR-0004 Decision 5.1). SUPER_OPERATOR is the
# immutable full-rights role (= today's single ADMIN; never-orphan floor).
OPERATOR_ROLE_TEMPLATES = {
    OperatorRoleCode.SUPER_OPERATOR.value: {
        "name": "Супероператор",
        "permissions": ALL_OPERATOR_PERMISSIONS,
        "is_system": True,
        "description": "Полный доступ ко всем функциям платформенного оператора (= прежний единый администратор).",
    },
    OperatorRoleCode.SUPPORT.value: {
        "name": "Поддержка",
        "permissions": [
            OperatorPermission.USERS_VIEW.value,
            OperatorPermission.COMPANIES_VIEW.value,
            OperatorPermission.KYC_VIEW.value,
            OperatorPermission.BILLING_VIEW.value,
        ],
        "is_system": False,
        "description": "Только просмотр пользователей, компаний, KYC и биллинга для триажа обращений.",
    },
    OperatorRoleCode.KYC_OFFICER.value: {
        "name": "Офицер KYC",
        "permissions": [
            OperatorPermission.USERS_VIEW.value,
            OperatorPermission.COMPANIES_VIEW.value,
            OperatorPermission.KYC_VIEW.value,
            OperatorPermission.KYC_VERIFY.value,
        ],
        "is_system": False,
        "description": "Проверка и верификация KYC (L1→L3), загрузка документов.",
    },
    OperatorRoleCode.BILLING_OPERATOR.value: {
        "name": "Оператор биллинга",
        "permissions": [
            OperatorPermission.USERS_VIEW.value,
            OperatorPermission.COMPANIES_VIEW.value,
            OperatorPermission.BILLING_VIEW.value,
            OperatorPermission.BILLING_MANAGE.value,
        ],
        "is_system": False,
        "description": "Управление подписками поставщиков и проведение платежей.",
    },
    OperatorRoleCode.MODERATOR.value: {
        "name": "Модератор",
        "permissions": [
            OperatorPermission.USERS_VIEW.value,
            OperatorPermission.COMPANIES_VIEW.value,
            OperatorPermission.KYC_VIEW.value,
            OperatorPermission.MODERATION_ROLE_APPLICATIONS.value,
            OperatorPermission.MODERATION_FORCE_OVERRIDE.value,
        ],
        "is_system": False,
        "description": "Модерация заявок на роли и аварийные force-override действия (с указанием причины).",
    },
}


class CompanyTypeCode(models.TextChoices):
    CLIENT = "CLIENT", "Клиент (покупатель)"
    SUPPLIER = "SUPPLIER", "Поставщик (продавец)"
    # DEPRECATED participant roles (retired 2026-06-23). Marketplace sides are now
    # SELLER (SUPPLIER) + BUYER (CLIENT). "Производитель" is ONLY an OEM brand
    # reference (catalog.Manufacturer), not a company role. Kept for migration/history;
    # deactivated as selectable types and remapped to SUPPLIER by accounts migration 0018.
    MANUFACTURER = "MANUFACTURER", "Производитель (DEPRECATED — см. catalog.Manufacturer)"
    PLANT = "PLANT", "Завод (DEPRECATED)"


# Company types whose members operate on the seller side. A manufacturer that sells
# is simply a SUPPLIER; the OEM-as-brand lives in catalog.Manufacturer.
SELLER_COMPANY_TYPES = (CompanyTypeCode.SUPPLIER,)


class VerificationStatusCode(models.TextChoices):
    L1_UNVERIFIED = "L1_UNVERIFIED", "Не верифицирован"
    PROFILE_SUBMITTED = "PROFILE_SUBMITTED", "Профиль подан"
    L2_VERIFIED = "L2_VERIFIED", "Верифицирован (L2)"
    L3_CONTRACTED = "L3_CONTRACTED", "Контракт (L3)"


class FeatureKey(models.TextChoices):
    """Stable feature keys for the entitlement layer (ADR-0006 §3 monetization).

    The app gates on these codes — NEVER a plan name. A company's plan / promo / demo is projected
    into CompanyEntitlement rows keyed by these. Add a key here, then gate the call site with
    accounts.services.entitlements.has_entitlement(company_id, FeatureKey.X).
    """

    QUOTE_SEND = "quote.send", "Отправка КП клиенту"
    QUOTE_EXPORT = "quote.export", "Экспорт КП (PDF/Excel)"
    AI_MATCH = "ai.match", "AI-подбор каталога"
    AI_DRAFT = "ai.draft", "AI-черновик КП"
    AI_PREFLIGHT = "ai.preflight", "AI-проверка заявки"
    AI_ENRICH = "ai.enrich", "AI-обогащение карточки товара (PIM)"
    ROLES_CUSTOM = "roles.custom", "Кастомные роли компании"
    DOCUMENT_GENERATE = "document.generate", "Генерация документов по шаблонам"


# The FREE FLOOR — features always granted, no entitlement row required. Keeps the platform's core
# loop usable for free and avoids a circular gate (the permission engine the КП builder reads must
# never be paywalled). Everything NOT here is locked unless an entitlement row grants it.
FREE_FLOOR_FEATURES = frozenset(
    {
        FeatureKey.AI_MATCH.value,  # match заявка↔catalog — feeds the wedge, drives adoption; free
        FeatureKey.AI_PREFLIGHT.value,  # advisory request quality — free, improves data for everyone
    }
)

# Baseline features an OPERATIONAL SupplierSubscription grants (no explicit entitlement row needed)
# — so a paying/trial seller keeps sending & exporting КП and building AI drafts. An explicit
# CompanyEntitlement row OVERRIDES this (a promo grant, or a DEMO downgrade). This is the ONE place
# that maps "has a plan" → features; business code still only ever checks a FeatureKey.
SUBSCRIPTION_BASELINE_FEATURES = frozenset(
    {
        FeatureKey.QUOTE_SEND.value,
        FeatureKey.QUOTE_EXPORT.value,
        FeatureKey.AI_DRAFT.value,
        # AI PIM enrichment is a SELLER premium (like ai.draft): it accelerates the seller's
        # catalog build, which only matters once they're subscribed to actually sell. NOT part
        # of the free floor — enrich is gated on this baseline / an explicit grant.
        FeatureKey.AI_ENRICH.value,
        FeatureKey.ROLES_CUSTOM.value,
        # «Документы 2.0» (owner decision 2026-07-22): generating arbitrary
        # template-based documents (letters, reports, поручения) is a baseline
        # subscription feature, gated like quote.send.
        FeatureKey.DOCUMENT_GENERATE.value,
    }
)
