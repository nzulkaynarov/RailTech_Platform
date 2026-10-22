"""Матрица ролей Платформы. ГЕНЕРИРУЕТСЯ — не править руками (PLT-11).

Источник: packages/contracts/platform-rbac.yaml (version 1).
Пересоздание: `make -C apps/platform rbac`; `tests/test_rbac_generated.py` и
`make check-platform` сверяют файл с контрактом. Логика доступа — `app/rbac.py`.
"""

from typing import Final, Literal

RoleCode = Literal["MANAGER", "DIRECTOR", "SUPPLY", "ENGINEER", "ACCOUNTANT", "ADMIN"]
ModuleCode = Literal["dashboard", "crm", "eds", "erp", "chats", "admin"]
Level = Literal["full", "read", "hidden"]

# Порядок ролей и модулей — как в контракте (модули рейла показываются в этом порядке).
ROLES: Final[tuple[RoleCode, ...]] = (
    "MANAGER",
    "DIRECTOR",
    "SUPPLY",
    "ENGINEER",
    "ACCOUNTANT",
    "ADMIN",
)
MODULES: Final[tuple[ModuleCode, ...]] = ("dashboard", "crm", "eds", "erp", "chats", "admin")

# Названия ролей (ru/uz/en).
ROLE_NAMES: Final[dict[RoleCode, dict[str, str]]] = {
    "MANAGER": {"ru": "Менеджер", "uz": "Menejer", "en": "Manager"},
    "DIRECTOR": {"ru": "Директор", "uz": "Direktor", "en": "Director"},
    "SUPPLY": {"ru": "Снабженец", "uz": "Ta'minotchi", "en": "Supply specialist"},
    "ENGINEER": {"ru": "Гл. инженер", "uz": "Bosh muhandis", "en": "Chief engineer"},
    "ACCOUNTANT": {"ru": "Бухгалтер", "uz": "Buxgalter", "en": "Accountant"},
    "ADMIN": {"ru": "Администратор", "uz": "Administrator", "en": "Administrator"},
}

# Роли ERP и права поверх шаблонов, которые CRM выдаёт роли Платформы
# (docs/architecture/integration-map.md §4).
# Пустой кортеж у ADMIN: суперпользователь ERP, роли ERP не нужны.
ERP_ROLE_CODES: Final[dict[RoleCode, tuple[str, ...]]] = {
    "MANAGER": ("VIEWER",),
    "DIRECTOR": ("HEAD",),
    "SUPPLY": ("CATALOG_SUPPLY", "FULFILLMENT"),
    "ENGINEER": ("FULFILLMENT",),
    "ACCOUNTANT": ("FINANCE",),
    "ADMIN": (),
}
ERP_EXTRA_PERMISSIONS: Final[dict[RoleCode, tuple[str, ...]]] = {
    "MANAGER": ("deal.manage",),
    "DIRECTOR": (),
    "SUPPLY": ("quote.build", "quote.edit_pricing"),
    "ENGINEER": ("quote.build",),
    "ACCOUNTANT": ("contract.manage", "fulfillment.act"),
    "ADMIN": (),
}

# Раздел матрицы -> модуль.
RESOURCE_MODULE: Final[dict[str, ModuleCode]] = {
    "dashboard.queue": "dashboard",
    "dashboard.summary": "dashboard",
    "crm.leads": "crm",
    "crm.clients": "crm",
    "eds.inbox": "eds",
    "eds.drafts": "eds",
    "eds.projects": "eds",
    "eds.payments": "eds",
    "eds.memo.create": "eds",
    "eds.memo.approve": "eds",
    "erp.calc": "erp",
    "erp.stock": "erp",
    "chats.internal": "chats",
    "chats.external": "chats",
    "admin": "admin",
}

# Матрица SPEC-v3 §4.2: раздел -> роль -> уровень. У нескольких ролей берётся максимум.
ACCESS: Final[dict[str, dict[RoleCode, Level]]] = {
    "dashboard.queue": {
        "MANAGER": "full",
        "DIRECTOR": "full",
        "SUPPLY": "full",
        "ENGINEER": "full",
        "ACCOUNTANT": "full",
        "ADMIN": "full",
    },
    "dashboard.summary": {
        "MANAGER": "hidden",
        "DIRECTOR": "full",
        "SUPPLY": "hidden",
        "ENGINEER": "hidden",
        "ACCOUNTANT": "read",
        "ADMIN": "hidden",
    },
    "crm.leads": {
        "MANAGER": "full",
        "DIRECTOR": "read",
        "SUPPLY": "hidden",
        "ENGINEER": "hidden",
        "ACCOUNTANT": "hidden",
        "ADMIN": "hidden",
    },
    "crm.clients": {
        "MANAGER": "full",
        "DIRECTOR": "read",
        "SUPPLY": "read",
        "ENGINEER": "read",
        "ACCOUNTANT": "read",
        "ADMIN": "hidden",
    },
    "eds.inbox": {
        "MANAGER": "read",
        "DIRECTOR": "full",
        "SUPPLY": "hidden",
        "ENGINEER": "hidden",
        "ACCOUNTANT": "read",
        "ADMIN": "hidden",
    },
    "eds.drafts": {
        "MANAGER": "read",
        "DIRECTOR": "full",
        "SUPPLY": "hidden",
        "ENGINEER": "hidden",
        "ACCOUNTANT": "hidden",
        "ADMIN": "hidden",
    },
    "eds.projects": {
        "MANAGER": "read",
        "DIRECTOR": "full",
        "SUPPLY": "read",
        "ENGINEER": "read",
        "ACCOUNTANT": "full",
        "ADMIN": "hidden",
    },
    "eds.payments": {
        "MANAGER": "read",
        "DIRECTOR": "read",
        "SUPPLY": "hidden",
        "ENGINEER": "hidden",
        "ACCOUNTANT": "full",
        "ADMIN": "hidden",
    },
    "eds.memo.create": {
        "MANAGER": "full",
        "DIRECTOR": "full",
        "SUPPLY": "full",
        "ENGINEER": "full",
        "ACCOUNTANT": "full",
        "ADMIN": "full",
    },
    "eds.memo.approve": {
        "MANAGER": "hidden",
        "DIRECTOR": "full",
        "SUPPLY": "hidden",
        "ENGINEER": "hidden",
        "ACCOUNTANT": "hidden",
        "ADMIN": "hidden",
    },
    "erp.calc": {
        "MANAGER": "hidden",
        "DIRECTOR": "full",
        "SUPPLY": "full",
        "ENGINEER": "full",
        "ACCOUNTANT": "read",
        "ADMIN": "hidden",
    },
    "erp.stock": {
        "MANAGER": "read",
        "DIRECTOR": "full",
        "SUPPLY": "full",
        "ENGINEER": "full",
        "ACCOUNTANT": "read",
        "ADMIN": "hidden",
    },
    "chats.internal": {
        "MANAGER": "full",
        "DIRECTOR": "full",
        "SUPPLY": "full",
        "ENGINEER": "full",
        "ACCOUNTANT": "full",
        "ADMIN": "full",
    },
    "chats.external": {
        "MANAGER": "full",
        "DIRECTOR": "read",
        "SUPPLY": "hidden",
        "ENGINEER": "hidden",
        "ACCOUNTANT": "full",
        "ADMIN": "hidden",
    },
    "admin": {
        "MANAGER": "hidden",
        "DIRECTOR": "read",
        "SUPPLY": "hidden",
        "ENGINEER": "hidden",
        "ACCOUNTANT": "hidden",
        "ADMIN": "full",
    },
}

# Меню (Q-PLT-12-2): модуль -> пункт -> разделы; пункт виден, если виден любой из них.
MENU: Final[dict[ModuleCode, dict[str, tuple[str, ...]]]] = {
    "dashboard": {
        "queue": ("dashboard.queue",),
        "projects": ("eds.projects",),
        "summary": ("dashboard.summary",),
    },
    "crm": {
        "messages": ("crm.leads",),
        "leads": ("crm.leads",),
        "clients": ("crm.clients",),
        "requests": ("crm.clients",),
        "channels": ("crm.leads",),
        "kb": ("crm.leads",),
    },
    "eds": {
        "documents": (
            "eds.inbox",
            "eds.drafts",
            "eds.projects",
            "eds.payments",
            "eds.memo.create",
            "eds.memo.approve",
        ),
        "inbox": ("eds.inbox",),
        "outbox": ("eds.drafts",),
        "projects": ("eds.projects",),
        "drafts": ("eds.drafts",),
        "approvals": ("eds.memo.approve", "eds.memo.create"),
        "payments": ("eds.payments",),
    },
    "erp": {
        "requests": ("erp.calc",),
        "calc": ("erp.calc",),
        "stock": ("erp.stock",),
        "catalog": ("erp.stock",),
        "docs": ("erp.stock",),
    },
    "chats": {
        "all": ("chats.internal", "chats.external"),
        "internal": ("chats.internal",),
        "external": ("chats.external",),
        "contacts": ("chats.internal",),
    },
    "admin": {
        "roles": ("admin",),
        "org": ("admin",),
        "integrations": ("admin",),
        "tickets": ("admin",),
    },
}

# Поля с ограничением (SPEC-v3 §4.2): группа -> роли, которым она видна.
RESTRICTED_FIELDS: Final[dict[str, tuple[RoleCode, ...]]] = {
    "cost_margin": ("DIRECTOR", "SUPPLY"),
    "totals_only": ("ACCOUNTANT",),
    "supplier_prices": ("DIRECTOR", "SUPPLY", "ACCOUNTANT"),
}
