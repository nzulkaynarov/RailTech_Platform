"""Каталог возможностей Платформы (роли как данные). ГЕНЕРИРУЕТСЯ — не править руками (ADR-0012).

Источник: packages/contracts/platform-rbac.yaml (version 2). Пересоздание:
`make -C apps/crm platform-roles`; тест `tests/unit/domain/test_platform_roles.py` сверяет
файл с каталогом.
"""

from typing import Final

# Системные роли: неизменны, не удаляются (код в `platform_roles.code` как есть).
SYSTEM_ROLE_CODES: Final[tuple[str, ...]] = (
    "ADMIN",
    "DIRECTOR",
)

# Шаблоны: при первом запуске создаются обычными ролями с кодом `tpl:<код>`.
TEMPLATE_ROLE_CODES: Final[tuple[str, ...]] = (
    "MANAGER",
    "SUPPLY",
    "ENGINEER",
    "ACCOUNTANT",
)

# Разделы каталога в порядке файла.
RESOURCE_KEYS: Final[tuple[str, ...]] = (
    "dashboard.queue",
    "dashboard.summary",
    "crm.leads",
    "crm.clients",
    "eds.inbox",
    "eds.drafts",
    "eds.projects",
    "eds.payments",
    "eds.memo.create",
    "eds.memo.approve",
    "erp.calc",
    "erp.calc.goods",
    "erp.calc.services",
    "erp.stock",
    "chats.internal",
    "chats.external",
    "admin",
    "company.settings",
)

# Допустимые уровни доступа раздела.
RESOURCE_LEVELS: Final[dict[str, tuple[str, ...]]] = {
    "dashboard.queue": (
        "read",
        "full",
    ),
    "dashboard.summary": (
        "read",
        "full",
    ),
    "crm.leads": (
        "read",
        "full",
    ),
    "crm.clients": (
        "read",
        "full",
    ),
    "eds.inbox": (
        "read",
        "full",
    ),
    "eds.drafts": (
        "read",
        "full",
    ),
    "eds.projects": (
        "read",
        "full",
    ),
    "eds.payments": (
        "read",
        "full",
    ),
    "eds.memo.create": (
        "read",
        "full",
    ),
    "eds.memo.approve": (
        "read",
        "full",
    ),
    "erp.calc": (
        "read",
        "full",
    ),
    "erp.calc.goods": ("full",),
    "erp.calc.services": ("full",),
    "erp.stock": (
        "read",
        "full",
    ),
    "chats.internal": (
        "read",
        "full",
    ),
    "chats.external": (
        "read",
        "full",
    ),
    "admin": (
        "read",
        "full",
    ),
    "company.settings": (
        "read",
        "full",
    ),
}

# Раздел -> уровень -> права CRM `ресурс:действие` (уровень full включает read).
CRM_BACKEND: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "dashboard.queue": {},
    "dashboard.summary": {
        "read": (
            "dashboard:read",
            "spend:read",
        ),
    },
    "crm.leads": {
        "read": (
            "leads:read",
            "stream:read",
            "dashboard:read",
            "kb:read",
        ),
        "full": (
            "leads:read",
            "leads:take",
            "leads:work",
            "leads:reply",
            "leads:note",
            "leads:assist",
            "leads:create",
            "stream:read",
            "dashboard:read",
            "kb:read",
            "reply_templates:read",
        ),
    },
    "crm.clients": {
        "read": (
            "clients:read",
            "deals:read",
            "documents:read",
        ),
        "full": (
            "clients:read",
            "clients:write",
            "deals:read",
            "deals:write",
            "documents:read",
            "documents:write",
        ),
    },
    "eds.inbox": {},
    "eds.drafts": {},
    "eds.projects": {},
    "eds.payments": {},
    "eds.memo.create": {},
    "eds.memo.approve": {},
    "erp.calc": {},
    "erp.calc.goods": {},
    "erp.calc.services": {},
    "erp.stock": {},
    "chats.internal": {},
    "chats.external": {
        "read": ("leads:read",),
        "full": (
            "leads:read",
            "leads:reply",
            "leads:note",
            "leads:assist",
        ),
    },
    "admin": {
        "read": (
            "users:read",
            "integrations:read",
            "models:read",
            "system:read",
            "external_services:read",
            "backups:read",
            "audit:read",
            "settings:read",
            "reply_templates:read",
            "kb:read",
            "tickets:read",
        ),
        "full": (
            "users:read",
            "users:write",
            "settings:read",
            "settings:write",
            "integrations:read",
            "integrations:write",
            "models:read",
            "models:test",
            "models:write",
            "system:read",
            "external_services:read",
            "external_services:write",
            "backups:read",
            "backups:write",
            "audit:read",
            "spend:read",
            "kb:read",
            "kb:write",
            "reply_templates:read",
            "reply_templates:write",
            "sandbox:use",
            "export:read",
            "tickets:read",
            "tickets:write",
        ),
    },
    "company.settings": {},
}

# Раздел -> уровень -> права ERP (`Permission`; уровень full включает read).
ERP_BACKEND: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "dashboard.queue": {},
    "dashboard.summary": {
        "full": ("data.export",),
    },
    "crm.leads": {},
    "crm.clients": {
        "full": (
            "deal.manage",
            "quote.send",
        ),
    },
    "eds.inbox": {
        "full": ("deal.assign",),
    },
    "eds.drafts": {
        "full": ("quote.review",),
    },
    "eds.projects": {
        "full": (
            "contract.manage",
            "contract.sign",
            "fulfillment.act",
        ),
    },
    "eds.payments": {
        "full": (
            "finance.invoice",
            "finance.payment",
            "finance.rates",
            "data.export",
        ),
    },
    "eds.memo.create": {},
    "eds.memo.approve": {},
    "erp.calc": {
        "full": (
            "deal.manage",
            "quote.build",
            "quote.edit_pricing",
        ),
    },
    "erp.calc.goods": {
        "full": (
            "quote.build",
            "quote.edit_pricing",
        ),
    },
    "erp.calc.services": {
        "full": ("quote.build",),
    },
    "erp.stock": {
        "full": (
            "catalog.manage",
            "catalog.publish",
            "supply.manage",
            "fulfillment.manage",
        ),
    },
    "chats.internal": {},
    "chats.external": {},
    "admin": {
        "full": ("team.manage",),
    },
    "company.settings": {
        "full": (
            "settings.edit",
            "settings.charge_templates",
        ),
    },
}

# Раздел -> уровень -> права EDS (`EdsPermission`; уровень full включает read).
EDS_BACKEND: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "dashboard.queue": {},
    "dashboard.summary": {},
    "crm.leads": {},
    "crm.clients": {},
    "eds.inbox": {
        "read": (
            "letters.read",
            "registry.read",
        ),
        "full": (
            "letters.read",
            "registry.read",
            "letters.register",
            "letters.resolve",
        ),
    },
    "eds.drafts": {
        "full": ("approvals.decide",),
    },
    "eds.projects": {
        "read": ("registry.read",),
        "full": ("registry.read",),
    },
    "eds.payments": {
        "read": ("registry.read",),
        "full": (
            "registry.read",
            "registry.export",
            "payments.confirm",
        ),
    },
    "eds.memo.create": {
        "full": ("memos.create",),
    },
    "eds.memo.approve": {
        "full": ("memos.approve",),
    },
    "erp.calc": {},
    "erp.calc.goods": {},
    "erp.calc.services": {},
    "erp.stock": {},
    "chats.internal": {},
    "chats.external": {},
    "admin": {
        "full": ("bus.manage",),
    },
    "company.settings": {},
}

# Поле с ограничением -> права ERP, которые оно открывает.
FIELD_ERP_BACKEND: Final[dict[str, tuple[str, ...]]] = {
    "cost_margin": ("quote.view_cost_margin",),
    "supplier_prices": (),
    "totals_only": (),
}

# Названия системных ролей и шаблонов (ru, uz, en).
ROLE_NAMES: Final[dict[str, dict[str, str]]] = {
    "ADMIN": {
        "ru": "Администратор",
        "uz": "Administrator",
        "en": "Administrator",
    },
    "DIRECTOR": {
        "ru": "Директор",
        "uz": "Direktor",
        "en": "Director",
    },
    "MANAGER": {
        "ru": "Менеджер",
        "uz": "Menejer",
        "en": "Manager",
    },
    "SUPPLY": {
        "ru": "Снабженец",
        "uz": "Ta'minotchi",
        "en": "Supply specialist",
    },
    "ENGINEER": {
        "ru": "Гл. инженер",
        "uz": "Bosh muhandis",
        "en": "Chief engineer",
    },
    "ACCOUNTANT": {
        "ru": "Бухгалтер",
        "uz": "Buxgalter",
        "en": "Accountant",
    },
}

# Матрица системных ролей и шаблонов: раздел -> full|read (скрытые не хранятся).
ROLE_ACCESS: Final[dict[str, dict[str, str]]] = {
    "ADMIN": {
        "admin": "full",
        "company.settings": "full",
        "dashboard.queue": "full",
        "chats.internal": "full",
        "eds.memo.create": "full",
    },
    "DIRECTOR": {
        "dashboard.queue": "full",
        "dashboard.summary": "full",
        "crm.leads": "read",
        "crm.clients": "full",
        "eds.inbox": "full",
        "eds.drafts": "full",
        "eds.projects": "full",
        "eds.payments": "full",
        "eds.memo.create": "full",
        "eds.memo.approve": "full",
        "erp.calc": "full",
        "erp.calc.goods": "full",
        "erp.calc.services": "full",
        "erp.stock": "full",
        "chats.internal": "full",
        "chats.external": "read",
        "company.settings": "full",
        "admin": "read",
    },
    "MANAGER": {
        "dashboard.queue": "full",
        "crm.leads": "full",
        "crm.clients": "full",
        "eds.inbox": "read",
        "eds.drafts": "read",
        "eds.projects": "read",
        "eds.payments": "read",
        "eds.memo.create": "full",
        "erp.stock": "read",
        "chats.internal": "full",
        "chats.external": "full",
    },
    "SUPPLY": {
        "dashboard.queue": "full",
        "crm.clients": "read",
        "eds.projects": "read",
        "eds.memo.create": "full",
        "erp.calc": "full",
        "erp.calc.goods": "full",
        "erp.stock": "full",
        "chats.internal": "full",
    },
    "ENGINEER": {
        "dashboard.queue": "full",
        "crm.clients": "read",
        "eds.projects": "read",
        "eds.memo.create": "full",
        "erp.calc": "full",
        "erp.calc.services": "full",
        "erp.stock": "full",
        "chats.internal": "full",
    },
    "ACCOUNTANT": {
        "dashboard.queue": "full",
        "dashboard.summary": "read",
        "crm.clients": "read",
        "eds.inbox": "read",
        "eds.projects": "full",
        "eds.payments": "full",
        "eds.memo.create": "full",
        "erp.calc": "read",
        "erp.stock": "read",
        "chats.internal": "full",
        "chats.external": "full",
    },
}

# Поля с ограничением, которые видит системная роль или шаблон.
ROLE_RESTRICTED_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "ADMIN": (),
    "DIRECTOR": (
        "cost_margin",
        "supplier_prices",
    ),
    "MANAGER": (),
    "SUPPLY": (
        "cost_margin",
        "supplier_prices",
    ),
    "ENGINEER": (),
    "ACCOUNTANT": (
        "totals_only",
        "supplier_prices",
    ),
}

# Базовая роль CRM для старого фронта: роль с кодом (порядок — прежние шесть ролей).
CRM_BASE_ROLE_BY_CODE: Final[dict[str, str]] = {
    "MANAGER": "manager",
    "DIRECTOR": "viewer",
    "SUPPLY": "viewer",
    "ENGINEER": "viewer",
    "ACCOUNTANT": "manager",
    "ADMIN": "admin",
}

# Базовая роль CRM для роли без кода: достаточно одного условия `раздел:уровень`.
CRM_BASE_ROLE_BY_ACCESS: Final[dict[str, tuple[str, ...]]] = {
    "admin": ("admin:full",),
    "manager": ("crm.leads:full",),
}
