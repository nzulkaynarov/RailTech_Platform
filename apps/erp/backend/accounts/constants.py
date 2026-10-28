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
    """Права бэк-офиса — галочки роли (M1-ERP-05; паттерн ERPNext «Role + Role Permission» /
    Odoo «группы доступа»). Права складываются: у сотрудника несколько ролей, действует
    объединение (BUSINESS §11 «очереди складываются»). «Администратор» — `is_superuser`, ему всё.

    Чтение открыто любому сотруднику своей компании (роль «Наблюдатель» = ни одного права);
    коды ниже — это ДЕЙСТВИЯ. Каждый эндпоинт мутации объявляет свой код
    (`core.permissions.RoleGatedViewMixin.required_permissions`), сервисы проверяют тот же код
    через `accounts.services.permissions.member_has_permission`."""

    # Запросы и сделки
    DEAL_MANAGE = "deal.manage", "Вести запросы и сделки"
    DEAL_ASSIGN = "deal.assign", "Назначать ответственного"
    # КП
    QUOTE_BUILD = "quote.build", "Строить КП"
    QUOTE_EDIT_PRICING = "quote.edit_pricing", "Менять цены, скидки и статьи расходов"
    QUOTE_VIEW_COST_MARGIN = "quote.view_cost_margin", "Видеть себестоимость и маржу"
    QUOTE_SEND = "quote.send", "Отправлять КП клиенту"
    # Визы КП внутри компании. Одобрение КП директором — маршрут EDS (EDS-03, волна 12): права ERP на него нет.
    # Акцепт КП клиентом — не право бэк-офиса (Cabinet / публичная ссылка).
    QUOTE_REVIEW = "quote.review", "Согласовывать КП"
    # Виза строки расчёта по типу позиции (ADR-0012 п. 6, D2-1): товар — «расчёт товаров и склад», услуга — «расчёт
    # услуг». Права вычисляет CRM из разделов каталога `erp.calc.goods` и `erp.calc.services` (platform-rbac.yaml).
    QUOTE_VISA_GOODS = "quote.visa_goods", "Визировать товары в расчёте"
    QUOTE_VISA_SERVICES = "quote.visa_services", "Визировать услуги в расчёте"
    # Договоры
    CONTRACT_MANAGE = "contract.manage", "Готовить договоры"
    CONTRACT_SIGN = "contract.sign", "Подписывать договоры от компании"
    # Каталог
    CATALOG_MANAGE = "catalog.manage", "Вести каталог"
    CATALOG_PUBLISH = "catalog.publish", "Публиковать карточки"
    # Снабжение (M4 добавит заказы поставщикам и приёмку)
    SUPPLY_MANAGE = "supply.manage", "Вести поставщиков и их предложения"
    # Исполнение и логистика
    FULFILLMENT_MANAGE = "fulfillment.manage", "Вести отгрузки и накладные"
    FULFILLMENT_ACT = "fulfillment.act", "Оформлять акты"
    # Финансы
    # D2-4 (Q-D2-4-1): чтение счетов и оплат без права действовать — директор, менеджер («Ч» в SPEC-v3 §4.2).
    FINANCE_VIEW = "finance.view", "Видеть счета и оплаты клиентов"
    FINANCE_INVOICE = "finance.invoice", "Выставлять счета клиентам"
    FINANCE_PAYMENT = "finance.payment", "Фиксировать оплаты"
    # Курс КП вручную (с причиной) и фактическая закупка для отклонения маржи (M1-ERP-08)
    FINANCE_RATES = "finance.rates", "Менять курс КП и вносить факт закупки"
    # Настройки и команда
    SETTINGS_EDIT = "settings.edit", "Менять реквизиты, шаблоны и нумерацию"
    SETTINGS_CHARGE_TEMPLATES = "settings.charge_templates", "Вести шаблоны статей расходов КП"
    TEAM_MANAGE = "team.manage", "Управлять командой и ролями"
    # Данные
    DATA_EXPORT = "data.export", "Экспортировать данные"


# Разделы редактора роли (порядок = порядок на экране; подписи — i18n по ключу раздела).
PERMISSION_GROUPS = {
    "deals": [Permission.DEAL_MANAGE, Permission.DEAL_ASSIGN],
    "quotes": [
        Permission.QUOTE_BUILD,
        Permission.QUOTE_EDIT_PRICING,
        Permission.QUOTE_VIEW_COST_MARGIN,
        Permission.QUOTE_SEND,
        Permission.QUOTE_REVIEW,
        Permission.QUOTE_VISA_GOODS,
        Permission.QUOTE_VISA_SERVICES,
    ],
    "contracts": [Permission.CONTRACT_MANAGE, Permission.CONTRACT_SIGN],
    "catalog": [Permission.CATALOG_MANAGE, Permission.CATALOG_PUBLISH],
    "supply": [Permission.SUPPLY_MANAGE],
    "fulfillment": [Permission.FULFILLMENT_MANAGE, Permission.FULFILLMENT_ACT],
    "finance": [
        Permission.FINANCE_VIEW,
        Permission.FINANCE_INVOICE,
        Permission.FINANCE_PAYMENT,
        Permission.FINANCE_RATES,
    ],
    "settings": [Permission.SETTINGS_EDIT, Permission.SETTINGS_CHARGE_TEMPLATES, Permission.TEAM_MANAGE],
    "data": [Permission.DATA_EXPORT],
}

ALL_PERMISSIONS = [p.value for p in Permission]


class BackofficeRoleCode(models.TextChoices):
    """Коды ролей-шаблонов бэк-офиса (BUSINESS §11). Сеются миграцией accounts/0003 и
    `ensure_default_company_roles` для своей компании; системные — имя и права не меняются,
    своя роль собирается кнопкой «Новая роль». Код стабилен, имя на экране — i18n по коду."""

    CALCULATION = "CALCULATION", "Расчёт"
    CATALOG_SUPPLY = "CATALOG_SUPPLY", "Каталог и закупки"
    FULFILLMENT = "FULFILLMENT", "Исполнение и логистика"
    FINANCE = "FINANCE", "Финансы"
    HEAD = "HEAD", "Руководитель"
    VIEWER = "VIEWER", "Наблюдатель"


P = Permission
ROLE_TEMPLATES = {
    BackofficeRoleCode.CALCULATION: [
        P.DEAL_MANAGE,
        P.QUOTE_BUILD,
        P.QUOTE_EDIT_PRICING,
        P.QUOTE_VIEW_COST_MARGIN,
        P.QUOTE_SEND,
        P.QUOTE_REVIEW,
        P.QUOTE_VISA_GOODS,
        P.QUOTE_VISA_SERVICES,
        P.CONTRACT_MANAGE,
    ],
    BackofficeRoleCode.CATALOG_SUPPLY: [
        P.CATALOG_MANAGE,
        P.CATALOG_PUBLISH,
        P.SUPPLY_MANAGE,
        P.QUOTE_VIEW_COST_MARGIN,
    ],
    BackofficeRoleCode.FULFILLMENT: [P.FULFILLMENT_MANAGE, P.FULFILLMENT_ACT],
    BackofficeRoleCode.FINANCE: [
        P.FINANCE_VIEW,
        P.FINANCE_INVOICE,
        P.FINANCE_PAYMENT,
        P.FINANCE_RATES,
        P.QUOTE_VIEW_COST_MARGIN,
        P.DATA_EXPORT,
    ],
    # Руководитель: финальное утверждение и все действия бэк-офиса (BUSINESS §11, M1-ERP-05).
    BackofficeRoleCode.HEAD: list(Permission),
    BackofficeRoleCode.VIEWER: [],
}
ROLE_TEMPLATES = {code.value: [p.value for p in perms] for code, perms in ROLE_TEMPLATES.items()}
del P

# Коды прав до M1-ERP-05 → новые коды (миграция accounts/0003 переписывает CompanyRole.permissions).
# `supply.manage` и `deal.manage` добавляются держателям прежних прав, которые их покрывали:
# офферы поставщиков жили под `catalog.manage`, смена стадии и документы сделки — под `quote.build`.
LEGACY_PERMISSION_RENAMES = {
    "payment.record": ["finance.payment"],
    "charge_templates.manage": ["settings.charge_templates"],
    "catalog.manage": ["catalog.manage", "supply.manage"],
    "quote.build": ["quote.build", "deal.manage"],
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
