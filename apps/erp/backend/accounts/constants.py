"""Single source of truth for accounts lookup CODES.

These mirror the `code` of seeded lookup rows (WorkspaceRole, SystemRole,
CompanyType). Reference these constants in business logic
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
    """Коды SystemRole. Операторская плоскость («ADMIN без компании = оператор») удалена в
    M1-ERP-02: администратор ERP = `is_superuser`. Судьба самой модели — M1-ERP-03/05."""

    ADMIN = "ADMIN", "Администратор платформы"
    USER = "USER", "Пользователь"


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
