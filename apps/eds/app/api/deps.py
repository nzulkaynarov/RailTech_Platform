"""Зависимости FastAPI: сессия БД, текущий сотрудник, проверка прав.

* `current_employee` — `Authorization: Bearer <токен доступа EDS>`; сотрудник берётся из проекции НА МОМЕНТ запроса:
  отключение и отзыв роли действуют сразу, не дожидаясь срока токена. Нет токена, он неверный или истёк — 401
  `UNAUTHORIZED` (`details.reason`); сотрудника нет в проекции — 401; отключён — 403 `USER_INACTIVE`.
* `require_permission(*codes)` — сотрудник с любым из прав (семантика `x-rt-permissions` в eds.yaml); без кодов — любой
  активный сотрудник. Нет права — 403 `FORBIDDEN` (`details.permission`).
"""

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.errors import EdsError, forbidden, unauthorized
from app.models import Employee
from app.security.access_token import AccessTokenError, verify_access_token
from app.security.permissions import EdsPermission
from app.services.employees import get_employee
from app.services.storage import ObjectStorage

PERMISSIONS_ATTR = "__eds_permissions__"
_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def get_bus(request: Request) -> AsyncBus:
    """Шина процесса: маршруты, которые пишут, публикуют события через неё в своей транзакции."""
    return get_container(request).bus


def get_storage(request: Request) -> ObjectStorage:
    return get_container(request).storage


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Сессия на запрос для маршрутов, которые пишут: транзакцию маршрут открывает сам (`session.begin()`)."""
    async with get_container(request).session_factory() as session:
        yield session


async def current_employee(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Employee:
    if credentials is None:
        raise unauthorized("missing")
    container = get_container(request)
    try:
        claims = verify_access_token(credentials.credentials, container.settings.access_secret.get_secret_value())
    except AccessTokenError as exc:
        raise unauthorized(exc.reason) from exc
    async with container.session_factory() as session:
        employee = await get_employee(session, claims.crm_user_id)
    if employee is None:
        raise unauthorized("user_not_found")
    if not employee.is_active:
        raise EdsError("USER_INACTIVE", "Учётная запись отключена.", status_code=status.HTTP_403_FORBIDDEN)
    return employee


def require_permission(
    *codes: EdsPermission,
) -> Callable[[Employee], Coroutine[Any, Any, Employee]]:
    wanted = tuple(c.value for c in codes)

    async def dependency(employee: Annotated[Employee, Depends(current_employee)]) -> Employee:
        if wanted and not set(wanted) & set(employee.permissions_eds):
            raise forbidden(wanted)
        return employee

    setattr(dependency, PERMISSIONS_ATTR, wanted)
    return dependency
