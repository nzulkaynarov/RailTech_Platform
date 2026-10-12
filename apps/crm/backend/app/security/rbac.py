"""RBAC на Casbin (SPEC §11, ADR-0005): политики в БД, кэш в памяти.

Модель и seed-политики — `infra/casbin/`. При старте недостающие seed-правила
добавляются в БД (существующие не удаляются). Субъект проверки — роль
пользователя; объектные проверки (владелец лида) — в сервисах.
"""

import csv
from collections.abc import Iterable
from pathlib import Path
from typing import Final

import casbin
import structlog
from casbin_async_sqlalchemy_adapter import Adapter
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models.auth import CasbinRule

logger = structlog.get_logger(__name__)

DOMAIN: Final = "crm"

# Каталог прав, который видит фронт (`GET /me/permissions`).
CATALOG: Final[dict[str, tuple[str, ...]]] = {
    "leads": ("read", "take", "work", "reply", "note", "assist"),
    "stream": ("read",),
    "dashboard": ("read",),
    "clients": ("read", "write"),
    "deals": ("read", "write"),
    "documents": ("read", "write"),
    "users": ("read", "write"),
    "settings": ("read", "write"),
    "kb": ("read", "write"),
    "audit": ("read",),
    "backups": ("read", "write"),
    "spend": ("read",),
    "models": ("read", "test", "write"),
    "integrations": ("read", "write"),
    "system": ("read",),
    "sandbox": ("use",),
}


def read_seed(path: Path) -> list[list[str]]:
    rules: list[list[str]] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.reader(handle, skipinitialspace=True):
            if row and row[0].strip() == "p":
                rules.append([cell.strip() for cell in row[1:]])
    return rules


class Rbac:
    def __init__(self, enforcer: casbin.AsyncEnforcer) -> None:
        self._enforcer = enforcer

    @classmethod
    async def create(cls, engine: AsyncEngine, casbin_dir: Path) -> "Rbac":
        adapter = Adapter(engine, db_class=CasbinRule)
        enforcer = casbin.AsyncEnforcer(str(casbin_dir / "model.conf"), adapter)
        await enforcer.load_policy()
        seed = read_seed(casbin_dir / "policy.seed.csv")
        missing = [rule for rule in seed if not enforcer.has_policy(*rule)]
        if missing:
            await enforcer.add_policies(missing)
            logger.info("rbac_seed_applied", rules=len(missing))
        return cls(enforcer)

    @classmethod
    def from_rules(cls, casbin_dir: Path, rules: Iterable[list[str]]) -> "Rbac":
        """Без БД — для unit-тестов матрицы прав."""
        enforcer = casbin.AsyncEnforcer(str(casbin_dir / "model.conf"))
        for rule in rules:
            enforcer.get_model().add_policy("p", "p", rule)
        enforcer.build_role_links()
        return cls(enforcer)

    async def reload(self) -> None:
        await self._enforcer.load_policy()

    def allowed(self, roles: Iterable[str], resource: str, action: str) -> bool:
        return any(self._enforcer.enforce(role, DOMAIN, resource, action) for role in roles)

    def permissions(self, roles: Iterable[str]) -> dict[str, dict[str, bool]]:
        role_list = list(roles)
        return {
            resource: {action: self.allowed(role_list, resource, action) for action in actions}
            for resource, actions in CATALOG.items()
        }
