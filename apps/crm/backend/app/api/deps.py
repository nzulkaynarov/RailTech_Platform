"""Зависимости REST: контейнер, текущий пользователь, RBAC (SPEC §11)."""

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.container import Container
from app.domain.errors import AuthError, ForbiddenError, PasswordChangeRequiredError
from app.repositories import platform_roles as platform_roles_repo
from app.repositories import users as users_repo
from app.security.principal import Principal
from app.security.rbac import Rbac
from app.security.tokens import TokenError, closed_by_password_reset, decode_access
from app.services.event_broker import EventBroker

_bearer = HTTPBearer(auto_error=False)
_lock = asyncio.Lock()


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_rbac(request: Request, container: ContainerDep) -> Rbac:
    """Enforcer создаётся при первом запросе (политики из БД + seed)."""
    rbac: Rbac | None = getattr(request.app.state, "rbac", None)
    if rbac is None:
        async with _lock:
            rbac = getattr(request.app.state, "rbac", None)
            if rbac is None:
                rbac = await Rbac.create(container.engine, container.settings.casbin_dir)
                request.app.state.rbac = rbac
    if rbac.stale:
        await rbac.safe_reload()
    return rbac


async def get_broker(request: Request, container: ContainerDep) -> EventBroker:
    broker: EventBroker | None = getattr(request.app.state, "broker", None)
    if broker is None:
        async with _lock:
            broker = getattr(request.app.state, "broker", None)
            if broker is None:
                broker = EventBroker(container.settings.libpq_dsn)
                await broker.start()
                request.app.state.broker = broker
    return broker


def client_ip(request: Request) -> str | None:
    """IP клиента (за Caddy — из X-Forwarded-For через proxy_headers uvicorn); не IP → None."""
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


async def get_principal(
    request: Request,
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """Токен проверяется подписью, пользователь и роли — по БД (деактивация действует сразу)."""
    if credentials is None:
        raise AuthError("missing bearer token")
    key = container.settings.jwt_secret.get_secret_value().encode()
    try:
        claims = decode_access(key, credentials.credentials)
    except TokenError as exc:
        raise AuthError("invalid access token") from exc
    async with container.session_factory() as session:
        user = await users_repo.get(session, claims.user_id)
        if user is None or not user.is_active:
            raise AuthError("user inactive")
        if closed_by_password_reset(claims.issued_at, user.password_changed_at):
            raise AuthError("session closed by a password reset")
        roles = await users_repo.roles_of(session, user.id)
        role_ids = await platform_roles_repo.rbac_identity(session, user.id)
    return Principal(
        user_id=user.id,
        full_name=user.full_name,
        roles=tuple(roles),
        must_change_password=user.must_change_password,
        ip=client_ip(request),
        platform_role_ids=role_ids,
    )


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require(resource: str, action: str) -> Callable[..., Awaitable[Principal]]:
    """Зависимость эндпоинта: право `action` на `resource` по Casbin."""
    return require_all((resource, action))


def require_all(*rights: tuple[str, str]) -> Callable[..., Awaitable[Principal]]:
    """Зависимость эндпоинта: все права `(resource, action)` сразу (например, выгрузка лидов —
    `export:read` и `leads:read`); 403 называет первое недостающее."""

    async def dependency(
        principal: PrincipalDep, rbac: Annotated[Rbac, Depends(get_rbac)]
    ) -> Principal:
        if principal.must_change_password:
            raise PasswordChangeRequiredError("change the temporary password first")
        for resource, action in rights:
            if not rbac.allowed(
                principal.rbac_roles, resource, action, principal.platform_role_ids
            ):
                raise ForbiddenError(f"{resource}:{action} is not allowed", resource=resource)
        return principal

    return dependency
