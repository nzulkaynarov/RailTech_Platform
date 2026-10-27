"""Каталог возможностей Платформы. ГЕНЕРИРУЕТСЯ — не править руками (ADR-0012).

Источник: packages/contracts/platform-rbac.yaml (version 2).
Пересоздание: `make -C apps/platform rbac`; `tests/test_rbac_generated.py` и
`make check-platform` сверяют файл с контрактом. Логика доступа — `app/rbac.py`.
Роли — данные CRM: здесь только каталог, системные роли и шаблоны.
"""

from typing import Final, Literal, TypedDict

ModuleCode = Literal["dashboard", "crm", "eds", "erp", "chats", "admin"]
Level = Literal["full", "read"]
RestrictedField = Literal["cost_margin", "supplier_prices", "totals_only"]


class CatalogRole(TypedDict):
    """Роль каталога: название (ru/uz/en), матрица и поля с ограничением."""

    name: dict[str, str]
    access: dict[str, Level]
    restricted_fields: tuple[RestrictedField, ...]


# Модули рейла в порядке показа.
MODULES: Final[tuple[ModuleCode, ...]] = (
    "dashboard",
    "crm",
    "eds",
    "erp",
    "chats",
    "admin",
)

# Раздел каталога -> модуль (порядок — как в контракте).
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
    "erp.calc.goods": "erp",
    "erp.calc.services": "erp",
    "erp.stock": "erp",
    "chats.internal": "chats",
    "chats.external": "chats",
    "admin": "admin",
    "company.settings": "admin",
}

# Допустимые уровни раздела (скрыто — раздела нет в матрице роли).
RESOURCE_LEVELS: Final[dict[str, tuple[Level, ...]]] = {
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

# Бэкенды, права в которых даёт раздел (по `backend` каталога).
RESOURCE_BACKENDS: Final[dict[str, tuple[str, ...]]] = {
    "dashboard.queue": (),
    "dashboard.summary": (
        "crm",
        "erp",
    ),
    "crm.leads": ("crm",),
    "crm.clients": (
        "crm",
        "erp",
    ),
    "eds.inbox": ("erp",),
    "eds.drafts": ("erp",),
    "eds.projects": ("erp",),
    "eds.payments": ("erp",),
    "eds.memo.create": (),
    "eds.memo.approve": (),
    "erp.calc": ("erp",),
    "erp.calc.goods": ("erp",),
    "erp.calc.services": ("erp",),
    "erp.stock": ("erp",),
    "chats.internal": (),
    "chats.external": ("crm",),
    "admin": (
        "crm",
        "erp",
    ),
    "company.settings": ("erp",),
}

# Меню: модуль -> пункт -> разделы; пункт виден, если виден любой из них.
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
        "kb": (
            "crm.leads",
            "admin",
        ),
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
        "approvals": (
            "eds.memo.approve",
            "eds.memo.create",
        ),
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
        "all": (
            "chats.internal",
            "chats.external",
        ),
        "internal": ("chats.internal",),
        "external": ("chats.external",),
        "contacts": ("chats.internal",),
    },
    "admin": {
        "roles": ("admin",),
        "org": ("admin",),
        "integrations": ("admin",),
        "bus": ("admin",),
        "tickets": ("admin",),
        "company": ("company.settings",),
        "bot": ("admin",),
        "audit": ("admin",),
    },
}

# Поля с ограничением: роль перечисляет поля, которые она видит.
RESTRICTED_FIELDS: Final[tuple[RestrictedField, ...]] = (
    "cost_margin",
    "supplier_prices",
    "totals_only",
)

# Вид работы «Моей очереди» -> (раздел, уровень не ниже).
QUEUE: Final[dict[str, tuple[str, Level]]] = {
    "answer_lead": (
        "crm.leads",
        "full",
    ),
    "take_lead": (
        "crm.leads",
        "full",
    ),
    "create_request": (
        "crm.clients",
        "full",
    ),
    "service_request": (
        "crm.clients",
        "full",
    ),
    "resolve_letter": (
        "eds.inbox",
        "full",
    ),
    "approve_quote": (
        "eds.drafts",
        "full",
    ),
    "approve_memo": (
        "eds.memo.approve",
        "full",
    ),
    "problem_project": (
        "eds.projects",
        "full",
    ),
    "calc_task": (
        "erp.calc",
        "full",
    ),
    "supplier_overdue": (
        "erp.stock",
        "full",
    ),
    "confirm_payment": (
        "eds.payments",
        "full",
    ),
    "issue_invoice": (
        "eds.payments",
        "full",
    ),
    "issue_contract": (
        "eds.projects",
        "full",
    ),
    "attach_scan": (
        "eds.projects",
        "full",
    ),
    "pay_memo": (
        "eds.payments",
        "full",
    ),
    "overdue_invoice": (
        "eds.payments",
        "full",
    ),
    "ticket": (
        "admin",
        "full",
    ),
    "integration_issue": (
        "admin",
        "full",
    ),
}

# Системные роли (неизменны): название, матрица, поля с ограничением.
SYSTEM_ROLES: Final[dict[str, CatalogRole]] = {
    "ADMIN": {
        "name": {
            "ru": "Администратор",
            "uz": "Administrator",
            "en": "Administrator",
        },
        "access": {
            "dashboard.queue": "full",
            "eds.memo.create": "full",
            "chats.internal": "full",
            "admin": "full",
            "company.settings": "full",
        },
        "restricted_fields": (),
    },
    "DIRECTOR": {
        "name": {
            "ru": "Директор",
            "uz": "Direktor",
            "en": "Director",
        },
        "access": {
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
            "admin": "read",
            "company.settings": "full",
        },
        "restricted_fields": (
            "cost_margin",
            "supplier_prices",
        ),
    },
}

# Шаблоны ролей: при первом запуске CRM создаёт по ним обычные роли.
TEMPLATES: Final[dict[str, CatalogRole]] = {
    "MANAGER": {
        "name": {
            "ru": "Менеджер",
            "uz": "Menejer",
            "en": "Manager",
        },
        "access": {
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
        "restricted_fields": (),
    },
    "SUPPLY": {
        "name": {
            "ru": "Снабженец",
            "uz": "Ta'minotchi",
            "en": "Supply specialist",
        },
        "access": {
            "dashboard.queue": "full",
            "crm.clients": "read",
            "eds.projects": "read",
            "eds.memo.create": "full",
            "erp.calc": "full",
            "erp.calc.goods": "full",
            "erp.stock": "full",
            "chats.internal": "full",
        },
        "restricted_fields": (
            "cost_margin",
            "supplier_prices",
        ),
    },
    "ENGINEER": {
        "name": {
            "ru": "Гл. инженер",
            "uz": "Bosh muhandis",
            "en": "Chief engineer",
        },
        "access": {
            "dashboard.queue": "full",
            "crm.clients": "read",
            "eds.projects": "read",
            "eds.memo.create": "full",
            "erp.calc": "full",
            "erp.calc.services": "full",
            "erp.stock": "full",
            "chats.internal": "full",
        },
        "restricted_fields": (),
    },
    "ACCOUNTANT": {
        "name": {
            "ru": "Бухгалтер",
            "uz": "Buxgalter",
            "en": "Accountant",
        },
        "access": {
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
        "restricted_fields": ("totals_only",),
    },
}
