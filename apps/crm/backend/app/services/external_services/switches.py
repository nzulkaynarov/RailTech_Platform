"""Выключатели внешних сервисов (M3-CRM-12, ADR-0024): пароль админа, аудит, применение.

Вендор модели — «снять с маршрута» в шлюзе: `model_group_alias` (алиасы-чаты → запасная модель) и
блокировка deployment эмбеддингов; значение `model_group_alias` целиком принадлежит CRM, минутная
проверка сверяет его с выключателями (`reconcile`). Langfuse, почта и Telegram — флаг в БД, который
читают процессы через `SwitchBoard` (≤ 10 с). Включение почты ставит ожидающие письма в очередь.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import external_registry as reg
from app.domain.errors import (
    ConflictError,
    NotFoundError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.litellm_admin import LiteLLMAdmin, LiteLLMAdminError
from app.integrations.litellm_catalog import ModelCatalog
from app.models.external_services import ExternalServiceSwitch
from app.repositories import users as users_repo
from app.security import audit, reauth
from app.security.principal import Principal
from app.services.mail import MailService
from app.services.service_switches import SwitchBoard

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SwitchOutcome:
    key: str
    disabled: bool
    state: Mapping[str, Any]


class SwitchService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        admin: LiteLLMAdmin,
        catalog: ModelCatalog,
        mail: MailService,
        board: SwitchBoard,
        lockout: reauth.LockoutPolicy | None = None,
    ) -> None:
        self._sessions = sessions
        self._admin = admin
        self._catalog = catalog
        self._mail = mail
        self._board = board
        self._lockout = lockout or reauth.LockoutPolicy()

    async def disable(
        self, who: Principal, key: str, password: str, reason: str | None
    ) -> SwitchOutcome:
        spec, providers = await self._switchable(key)
        await self._reauth(who.user_id, password)
        state: dict[str, Any] = {}
        if spec.vendor is not None:
            vendors = await self._disabled_vendors() | {spec.vendor}
            state = await self._apply_vendor_off(spec.vendor, vendors, providers)
        await self._save(who, key, True, reason, state)
        logger.info("external_service_disabled", service=key)
        return SwitchOutcome(key, True, state)

    async def enable(self, who: Principal, key: str, password: str) -> SwitchOutcome:
        spec = await self._spec(key)
        if spec.switch is None:
            raise _not_switchable("У этого сервиса нет выключателя")
        await self._reauth(who.user_id, password)
        if spec.vendor is not None:
            vendors = await self._disabled_vendors() - {spec.vendor}
            await self._apply_vendor_on(spec.vendor, vendors)
        await self._save(who, key, False, None, {})
        if spec.switch == "mail":
            await self._mail.resume_queued()
        logger.info("external_service_enabled", service=key)
        return SwitchOutcome(key, False, {})

    async def reconcile(self) -> bool:
        """Сверить `model_group_alias` шлюза с выключателями вендоров; True — пришлось исправить."""
        vendors = await self._disabled_vendors()
        current = await self._admin.router_aliases()
        if not vendors and not current:
            return False
        desired = reg.redirects(vendors, await self._providers(fresh=False))
        if current == desired:
            return False
        await self._admin.set_router_aliases(desired)
        logger.warning("external_switch_reconciled", aliases=sorted(desired))
        return True

    async def _switchable(self, key: str) -> tuple[reg.ServiceSpec, dict[str, str | None]]:
        providers = await self._providers(fresh=True)
        spec = reg.find(reg.registry(providers), key)
        if spec is None:
            raise NotFoundError("unknown external service")
        if spec.switch is None:
            raise _not_switchable("У этого сервиса нет выключателя")
        if spec.vendor is not None:
            problem = reg.switch_problem(spec.vendor, providers)
            if problem is not None:
                raise _not_switchable(problem)
        return spec, providers

    async def _spec(self, key: str) -> reg.ServiceSpec:
        spec = reg.find(reg.registry(await self._providers(fresh=False)), key)
        if spec is None and key.startswith(reg.VENDOR_PREFIX):
            # Вендор мог уйти из алиасов, пока был выключен: включить всё равно можно.
            vendor = key.removeprefix(reg.VENDOR_PREFIX)
            return reg.ServiceSpec(
                key, vendor, "", "ensemble", "crm", "", (), None, "vendor", vendor
            )
        if spec is None:
            raise NotFoundError("unknown external service")
        return spec

    async def _providers(self, *, fresh: bool) -> dict[str, str | None]:
        if fresh:
            self._catalog.invalidate()
        return {a: e.provider for a, e in (await self._catalog.entries()).items()}

    async def _disabled_vendors(self) -> set[str]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(ExternalServiceSwitch.service_key).where(
                    ExternalServiceSwitch.disabled.is_(True),
                    ExternalServiceSwitch.service_key.startswith(reg.VENDOR_PREFIX),
                )
            )
            return {k.removeprefix(reg.VENDOR_PREFIX) for k in rows.all()}

    async def _apply_vendor_off(
        self, vendor: str, vendors: set[str], providers: Mapping[str, str | None]
    ) -> dict[str, Any]:
        desired = reg.redirects(vendors, providers)
        blocked = reg.blocked_aliases([vendor], providers)
        try:
            await self._admin.set_router_aliases(desired)
            ids = [d.id for d in await self._admin.deployments() if d.alias in blocked]
            for model_id in ids:
                await self._admin.block(model_id)
        except LiteLLMAdminError as exc:
            raise _gateway_error(exc) from exc
        moved = sorted(a for a in desired if providers.get(a) == vendor)
        return {"redirected": moved, "blocked": ids}

    async def _apply_vendor_on(self, vendor: str, vendors: set[str]) -> None:
        async with self._sessions() as session:
            row = await session.get(ExternalServiceSwitch, reg.vendor_key(vendor))
            blocked = list((row.state or {}).get("blocked", [])) if row is not None else []
        try:
            await self._admin.set_router_aliases(
                reg.redirects(vendors, await self._providers(fresh=True))
            )
            for model_id in blocked:
                await self._unblock(str(model_id))
        except LiteLLMAdminError as exc:
            raise _gateway_error(exc) from exc

    async def _unblock(self, model_id: str) -> None:
        try:
            await self._admin.unblock(model_id)
        except LiteLLMAdminError as exc:
            if exc.status != 404:  # deployment уже заменили в «Модели ИИ» — разблокировать нечего
                raise

    async def _save(
        self, who: Principal, key: str, disabled: bool, reason: str | None, state: dict[str, Any]
    ) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(ExternalServiceSwitch, key, with_for_update=True)
            before = {"disabled": bool(row and row.disabled)}
            if row is None:
                row = ExternalServiceSwitch(service_key=key)
                session.add(row)
            row.disabled, row.reason, row.state = disabled, reason, state
            row.changed_by, row.changed_at = who.user_id, datetime.now(UTC)
            after = {"disabled": disabled, "reason": reason, **state}
            await audit.record(
                session,
                who.actor,
                "external_service.disable" if disabled else "external_service.enable",
                "external_service",
                key,
                before=before,
                after=after,
            )
        self._board.invalidate()

    async def _reauth(self, user_id: int, password: str) -> None:
        async with self._sessions() as session, session.begin():
            user = await users_repo.get(session, user_id, for_update=True)
            if user is None:
                raise ValidationFailedError(
                    "password is wrong", reason=Reason.WRONG_PASSWORD, field="password"
                )
            failure = reauth.check(user, password, datetime.now(UTC), self._lockout)
        if failure is not None:
            raise failure


def _not_switchable(detail: str) -> ConflictError:
    return ConflictError(
        "service cannot be switched", reason=Reason.SERVICE_NOT_SWITCHABLE, detail=detail
    )


def _gateway_error(exc: LiteLLMAdminError) -> UpstreamUnavailableError:
    return UpstreamUnavailableError(
        "litellm rejected the switch", reason=Reason.LITELLM_UNAVAILABLE, detail=exc.detail
    )
