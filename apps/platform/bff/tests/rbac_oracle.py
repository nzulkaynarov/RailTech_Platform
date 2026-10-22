"""Матрица SPEC-v3 §4.2 дословно — независимый от YAML эталон для тестов (не генерируется).

Колонки: MANAGER, DIRECTOR, SUPPLY, ENGINEER, ACCOUNTANT, ADMIN; F — full, R — read, H — hidden.
Менять вместе с `platform-rbac.yaml`: тесты падают, пока файл и эталон расходятся.
"""

from typing import Final

ROLES: Final = ("MANAGER", "DIRECTOR", "SUPPLY", "ENGINEER", "ACCOUNTANT", "ADMIN")
LEVELS: Final = {"F": "full", "R": "read", "H": "hidden"}
RANK: Final = {"hidden": 0, "read": 1, "full": 2}

MATRIX: Final[dict[str, str]] = {
    "dashboard.queue": "FFFFFF",
    "dashboard.summary": "HFHHRH",
    "crm.leads": "FRHHHH",
    "crm.clients": "FRRRRH",
    "eds.inbox": "RFHHRH",
    "eds.drafts": "RFHHHH",
    "eds.projects": "RFRRFH",
    "eds.payments": "RRHHFH",
    "eds.memo.create": "FFFFFF",
    "eds.memo.approve": "HFHHHH",
    "erp.calc": "HFFFRH",
    "erp.stock": "RFFFRH",
    "chats.internal": "FFFFFF",
    "chats.external": "FRHHFH",
    "admin": "HRHHHF",
}

MODULE_OF: Final[dict[str, str]] = {key: key.split(".")[0] for key in MATRIX}

# Группы полей с ограничением (SPEC-v3 §4.2, последний абзац).
RESTRICTED: Final[dict[str, tuple[str, ...]]] = {
    "cost_margin": ("DIRECTOR", "SUPPLY"),
    "totals_only": ("ACCOUNTANT",),
    "supplier_prices": ("DIRECTOR", "SUPPLY", "ACCOUNTANT"),
}


def level(role: str, key: str) -> str:
    return LEVELS[MATRIX[key][ROLES.index(role)]]


def union(roles: list[str], key: str) -> str:
    best = "hidden"
    for role in roles:
        if RANK[level(role, key)] > RANK[best]:
            best = level(role, key)
    return best
