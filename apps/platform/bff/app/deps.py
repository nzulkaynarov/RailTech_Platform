"""Зависимости FastAPI: общие ресурсы живут в `app.state` (создаются в lifespan)."""

import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
from fastapi import Depends, Request
from redis.asyncio import Redis

from app.auth import AuthService, LoginLimiter
from app.clients import CrmClient, EdsClient, ErpClient
from app.clients.base import Backend
from app.config import Settings
from app.cookies import CSRF_HEADER, SESSION_COOKIE
from app.errors import PlatformError, session_expired
from app.rbac import Access, Need, allows, fields_of, merge
from app.rbac_generated import RESOURCE_MODULE
from app.reset_limit import HourlyLimiter
from app.session import SessionData, SessionRole

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


def get_crm(request: Request) -> CrmClient:
    crm: CrmClient = request.app.state.crm
    return crm


def get_erp(request: Request) -> ErpClient:
    erp: ErpClient = request.app.state.erp
    return erp


def get_eds(request: Request) -> EdsClient | None:
    eds: EdsClient | None = getattr(request.app.state, "eds", None)
    return eds


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


RedisDep = Annotated[Redis, Depends(get_redis)]
CrmDep = Annotated[CrmClient, Depends(get_crm)]
ErpDep = Annotated[ErpClient, Depends(get_erp)]
EdsDep = Annotated[EdsClient | None, Depends(get_eds)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def get_auth_service(
    redis: RedisDep, crm: CrmDep, erp: ErpDep, settings: SettingsDep, eds: EdsDep
) -> AuthService:
    return AuthService(redis, crm, erp, settings, eds)


def get_login_limiter(redis: RedisDep, settings: SettingsDep) -> LoginLimiter:
    return LoginLimiter(redis, settings.login_rate_per_minute)


def get_forgot_limiter(redis: RedisDep) -> HourlyLimiter:
    """Запрос ссылки сброса: 5 в час на IP и на адрес."""
    return HourlyLimiter(redis, "forgot", 5)


def get_reset_limiter(redis: RedisDep) -> HourlyLimiter:
    """Ввод нового пароля по ссылке: 20 в час на IP."""
    return HourlyLimiter(redis, "reset", 20)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
ForgotLimiterDep = Annotated[HourlyLimiter, Depends(get_forgot_limiter)]
ResetLimiterDep = Annotated[HourlyLimiter, Depends(get_reset_limiter)]
LoginLimiterDep = Annotated[LoginLimiter, Depends(get_login_limiter)]


@dataclass
class Authed:
    """Сотрудник с живой сессией: снимок профиля и вызовы CRM и ERP от его имени."""

    sid: str
    data: SessionData
    service: AuthService

    @property
    def roles(self) -> list[SessionRole]:
        """Все роли сотрудника: права на операции считаются по ним (активная роль не влияет)."""
        return list(self.data.roles)

    @property
    def access(self) -> Access:
        """Объединение матриц всех ролей сотрудника (права операций)."""
        return merge(self.data.roles)

    @property
    def fields(self) -> list[str]:
        """Поля с ограничением по объединению ролей (вырезание из ответов бэкендов)."""
        return fields_of(self.data.roles)

    async def call(
        self,
        backend: Backend,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        probe: bool = False,
        content: bytes | None = None,
        content_type: str | None = None,
        stream: bool = False,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self.service.call(
            self.sid,
            backend,
            method,
            path,
            json=json,
            params=params,
            probe=probe,
            content=content,
            content_type=content_type,
            stream=stream,
            headers=headers,
        )


async def get_authed(request: Request, service: AuthServiceDep) -> Authed:
    """Сессия по cookie; на изменяющих запросах — ещё и проверка `X-CSRF-Token`."""
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        raise session_expired()
    data = await service.store.get(sid)
    if data is None:
        raise session_expired()
    if request.method not in _SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent.encode(), data.csrf.encode()):
            raise PlatformError(
                "CSRF_FAILED", "Запрос отклонён: обновите страницу.", status_code=403
            )
    return Authed(sid=sid, data=data, service=service)


AuthedDep = Annotated[Authed, Depends(get_authed)]


def require(resource: str, need: Need = "read") -> Callable[[Authed], Awaitable[Authed]]:
    """Зависимость маршрута: раздел каталога доступен ролям сотрудника не ниже `need`.

    Проверка идёт по объединению всех ролей (Q-PLT-12-1). Пока не сменён обязательный пароль,
    недоступно всё, кроме смены пароля и профиля. Неизвестный раздел — ошибка при описании маршрута.
    """
    if resource not in RESOURCE_MODULE:
        raise KeyError(f"нет раздела каталога: {resource}")

    async def dependency(authed: AuthedDep) -> Authed:
        # Профиль CRM (кэш 60 с): роль, снятая в CRM, перестаёт действовать и без запроса /me.
        authed.data = await authed.service.sync_profile(authed.sid, authed.data)
        if authed.data.must_change_password:
            raise PlatformError(
                "FORBIDDEN",
                "Сначала смените временный пароль.",
                status_code=403,
                details={"reason": "password_change_required"},
            )
        if not allows(authed.access, resource, need):
            raise PlatformError(
                "FORBIDDEN",
                "Раздел или действие не положены вашей роли.",
                status_code=403,
                details={"resource": resource, "need": need},
            )
        return authed

    return dependency


Rule = tuple[str, Need]


def _check_rules(rules: tuple[Rule, ...]) -> None:
    for resource, _ in rules:
        if resource not in RESOURCE_MODULE:
            raise KeyError(f"нет раздела каталога: {resource}")


async def _gate(authed: Authed) -> None:
    """Общая часть проверок раздела: профиль CRM свеж, временный пароль сменён."""
    authed.data = await authed.service.sync_profile(authed.sid, authed.data)
    if authed.data.must_change_password:
        raise PlatformError(
            "FORBIDDEN",
            "Сначала смените временный пароль.",
            status_code=403,
            details={"reason": "password_change_required"},
        )


def _forbidden(rules: tuple[Rule, ...]) -> PlatformError:
    return PlatformError(
        "FORBIDDEN",
        "Раздел или действие не положены вашей роли.",
        status_code=403,
        details={"resource": rules[0][0], "need": rules[0][1]},
    )


def require_any(*rules: Rule) -> Callable[[Authed], Awaitable[Authed]]:
    """Зависимость маршрута: достаточно любого из правил «раздел не ниже уровня».

    Для операций, которые разные роли получают из разных разделов (чтение базы знаний — `crm.leads`
    или `admin`). Решающее слово остаётся за бэкендом: каталог только отсекает заведомо лишних.
    """
    _check_rules(rules)

    async def dependency(authed: AuthedDep) -> Authed:
        await _gate(authed)
        if not any(allows(authed.access, resource, need) for resource, need in rules):
            raise _forbidden(rules)
        return authed

    return dependency


def require_all(*rules: Rule) -> Callable[[Authed], Awaitable[Authed]]:
    """Зависимость маршрута: нужны все правила сразу (выгрузка — `admin: full` и чтение данных)."""
    _check_rules(rules)

    async def dependency(authed: AuthedDep) -> Authed:
        await _gate(authed)
        for resource, need in rules:
            if not allows(authed.access, resource, need):
                raise _forbidden(((resource, need),))
        return authed

    return dependency


async def require_any_section(authed: AuthedDep) -> Authed:
    """Зависимость маршрута: у ролей сотрудника есть хотя бы один раздел каталога.

    Для сквозных экранов (поиск в шапке), которые сами фильтруют результат по разделам: роль без
    «Моей очереди» (например, «Менеджер и бухгалтер») ищет по своим разделам, а не получает 403.
    """
    authed.data = await authed.service.sync_profile(authed.sid, authed.data)
    if authed.data.must_change_password:
        raise PlatformError(
            "FORBIDDEN",
            "Сначала смените временный пароль.",
            status_code=403,
            details={"reason": "password_change_required"},
        )
    if not authed.access:
        raise PlatformError(
            "FORBIDDEN",
            "Раздел или действие не положены вашей роли.",
            status_code=403,
            details={"reason": "no_sections"},
        )
    return authed
