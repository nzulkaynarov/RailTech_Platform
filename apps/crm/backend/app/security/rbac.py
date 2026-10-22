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
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.domain.platform_roles import role_subject
from app.models.auth import CasbinRule

logger = structlog.get_logger(__name__)

DOMAIN: Final = "crm"

# Каталог прав, который видит фронт (`GET /me/permissions`).
CATALOG: Final[dict[str, tuple[str, ...]]] = {
    "leads": ("read", "take", "work", "reply", "note", "assist", "create"),
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
    "reply_templates": ("read", "write"),
    "export": ("read",),
    "external_services": ("read", "write"),
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
        # Перезагрузка политик после правки роли не удалась: повторить при ближайшей проверке.
        self.stale = False

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
        from app.services.platform_policies import sync_policies

        # Роли Платформы (`pr:<id>`): правила в БД сверяются с таблицей ролей (после миграции).
        if await sync_policies(async_sessionmaker(engine)):
            await enforcer.load_policy()
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

    async def safe_reload(self) -> None:
        """Перезагрузить политики; сбой не ломает запрос — флаг `stale` повторит попытку позже."""
        try:
            await self.reload()
        except Exception:
            logger.exception("rbac_reload_failed")
            self.stale = True
        else:
            self.stale = False

    def allowed(
        self,
        roles: Iterable[str],
        resource: str,
        action: str,
        platform_role_ids: Iterable[int] = (),
    ) -> bool:
        """Право по ролям CRM или по ролям Платформы (субъект `pr:<id>`, правила в casbin)."""
        subjects = [*roles, *(role_subject(i) for i in platform_role_ids)]
        return any(self._enforcer.enforce(sub, DOMAIN, resource, action) for sub in subjects)

    def permissions(
        self, roles: Iterable[str], platform_role_ids: Iterable[int] = ()
    ) -> dict[str, dict[str, bool]]:
        role_list, platform_list = list(roles), list(platform_role_ids)
        return {
            resource: {
                action: self.allowed(role_list, resource, action, platform_list)
                for action in actions
            }
            for resource, actions in CATALOG.items()
        }
