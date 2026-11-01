"""Каталог версии 2 дословно — независимый от YAML эталон для тестов (не генерируется).

Колонки — роли каталога: две системные (ADMIN, DIRECTOR) и шесть шаблонов (MANAGER, SUPPLY,
ENGINEER, ACCOUNTANT; с P8 — роли пилота REGISTRAR и MANAGER_ALL); F — full, R — read,
H — скрыто. Менять вместе с `platform-rbac.yaml`: тесты падают, пока файл и эталон расходятся.
Роли в Платформе — данные; эти восемь — только предустановки (ADR-0012).
"""

from typing import Final

ROLES: Final = (
    "ADMIN",
    "DIRECTOR",
    "MANAGER",
    "SUPPLY",
    "ENGINEER",
    "ACCOUNTANT",
    "REGISTRAR",
    "MANAGER_ALL",
)
SYSTEM: Final = ("ADMIN", "DIRECTOR")
LEVELS: Final = {"F": "full", "R": "read", "H": "hidden"}
RANK: Final = {"hidden": 0, "read": 1, "full": 2}

MATRIX: Final[dict[str, str]] = {
    "dashboard.queue": "FFFFFFFF",
    "dashboard.summary": "HFHHHRHH",
    "crm.leads": "HRFHHHFF",
    "crm.clients": "HFFRRRRF",
    "eds.inbox": "HFRHHRRR",
    # P8: регистрация входящих отдельно от резолюции — директор (системная) и делопроизводитель.
    "eds.inbox.register": "HFHHHHFH",
    "eds.drafts": "HFRHHHHR",
    "eds.projects": "HFRRRFRF",
    "eds.payments": "HRRHHFHF",
    "eds.memo.create": "FFFFFFFF",
    "eds.memo.approve": "HFHHHHHH",
    "erp.calc": "HFHFFRHF",
    "erp.calc.goods": "HFHFHHHF",
    "erp.calc.services": "HFHHFHHF",
    "erp.stock": "HFRFFRHF",
    "chats.internal": "FFFFFFFF",
    "chats.external": "HRFHHFRF",
    "admin": "FRHHHHHH",
    "company.settings": "FFHHHHHH",
}

MODULE_OF: Final[dict[str, str]] = {
    key: "admin" if key == "company.settings" else key.split(".")[0] for key in MATRIX
}

# Поля с ограничением, которые видит роль.
FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "ADMIN": (),
    "DIRECTOR": ("cost_margin", "supplier_prices"),
    "MANAGER": (),
    "SUPPLY": ("cost_margin", "supplier_prices"),
    "ENGINEER": (),
    "ACCOUNTANT": ("totals_only",),
    "REGISTRAR": (),
    "MANAGER_ALL": ("cost_margin", "supplier_prices"),
}


def level(role: str, key: str) -> str:
    return LEVELS[MATRIX[key][ROLES.index(role)]]


def union(roles: list[str], key: str) -> str:
    best = "hidden"
    for role in roles:
        if RANK[level(role, key)] > RANK[best]:
            best = level(role, key)
    return best


def access_of(role: str) -> dict[str, str]:
    return {key: level(role, key) for key in MATRIX if level(role, key) != "hidden"}
