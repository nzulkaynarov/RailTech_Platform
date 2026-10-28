"""Каталог версии 2 дословно — независимый от YAML эталон для тестов (не генерируется).

Колонки — роли каталога: две системные (ADMIN, DIRECTOR) и четыре шаблона (MANAGER, SUPPLY,
ENGINEER, ACCOUNTANT); F — full, R — read, H — скрыто. Менять вместе с `platform-rbac.yaml`: тесты
падают, пока файл и эталон расходятся. Роли в Платформе — данные; эти шесть — только
предустановки (ADR-0012).
"""

from typing import Final

ROLES: Final = ("ADMIN", "DIRECTOR", "MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT")
SYSTEM: Final = ("ADMIN", "DIRECTOR")
LEVELS: Final = {"F": "full", "R": "read", "H": "hidden"}
RANK: Final = {"hidden": 0, "read": 1, "full": 2}

MATRIX: Final[dict[str, str]] = {
    "dashboard.queue": "FFFFFF",
    "dashboard.summary": "HFHHHR",
    "crm.leads": "HRFHHH",
    "crm.clients": "HFFRRR",
    "eds.inbox": "HFRHHR",
    "eds.drafts": "HFRHHH",
    "eds.projects": "HFRRRF",
    "eds.payments": "HRRHHF",
    "eds.memo.create": "FFFFFF",
    "eds.memo.approve": "HFHHHH",
    "erp.calc": "HFHFFR",
    "erp.calc.goods": "HFHFHH",
    "erp.calc.services": "HFHHFH",
    "erp.stock": "HFRFFR",
    "chats.internal": "FFFFFF",
    "chats.external": "HRFHHF",
    "admin": "FRHHHH",
    "company.settings": "FFHHHH",
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
    "ACCOUNTANT": ("supplier_prices", "totals_only"),
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
