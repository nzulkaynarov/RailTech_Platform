"""Пользователи и роли Платформы в CRM для Admin · Оргструктура и Ролевая матрица.

`GET/POST/PATCH /api/v1/users*`, `/users/{id}/invite`, `/api/v1/platform-roles*` (R-1). Вызовы идут
от имени сотрудника через `Authed.call` (токен CRM из сессии). Право на операцию и инварианты
(«хотя бы один активный администратор и директор», «роль с сотрудниками не удаляется», «системная
роль неизменна») решает CRM; здесь — только перевод ответов и ошибок CRM в формат `Error` контракта.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.clients.base import Backend
from app.errors import PlatformError, backend_code, backend_reason, from_backend

Call = Callable[..., Awaitable[httpx.Response]]

LAST_ADMIN_MESSAGE = (
    "Нельзя снять роль администратора или отключить последнего администратора. "
    "Сначала назначьте администратором другого сотрудника."
)
LAST_DIRECTOR_MESSAGE = (
    "Нельзя снять роль директора или отключить последнего директора. "
    "Сначала назначьте директором другого сотрудника."
)
EMAIL_EXISTS_MESSAGE = "Сотрудник с такой почтой уже есть."
ACTIVE_LEADS_MESSAGE = (
    "У сотрудника есть лиды в работе. Выберите коллегу, которому их передать, и повторите."
)
ROLE_IN_USE_MESSAGE = (
    "Роль выдана сотрудникам ({employees}). Сначала назначьте им другие роли в Оргструктуре, "
    "затем удалите роль."
)
ROLE_SYSTEM_MESSAGE = "Системную роль нельзя изменить или удалить."
NAME_TAKEN_MESSAGE = "Роль с таким названием уже есть."
# Поля CRM -> поля контракта BFF (`details.fields`).
_FIELDS = {
    "full_name": "name",
    "platform_role_ids": "role_ids",
    "email": "email",
    "position": "position",
    "transfer_to_user_id": "transfer_to_user_id",
}


def _details(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    details = body.get("details") if isinstance(body, dict) else None
    return details if isinstance(details, dict) else {}


def _fields(response: httpx.Response) -> list[str]:
    details = _details(response)
    names = [e.get("field") for e in details.get("errors") or [] if isinstance(e, dict)]
    names.append(details.get("field"))
    return sorted({_FIELDS.get(str(n), str(n)) for n in names if n})


def crm_error(response: httpx.Response) -> PlatformError:
    """Ответ CRM 4xx -> ошибка контракта; остальное решает общий перевод `from_backend`.

    У каждого 409 `details.reason` — код CRM (нижний регистр), `code` — код контракта.
    """
    status = response.status_code
    code = backend_code(response)
    reason = backend_reason(response)
    base = from_backend("crm", response)
    if status == 409:
        details = _details(response)
        if code == "last_admin":
            return _replace(base, "LAST_ADMIN", LAST_ADMIN_MESSAGE, reason=code)
        if code == "last_director":
            return _replace(base, "LAST_DIRECTOR", LAST_DIRECTOR_MESSAGE, reason=code)
        if code == "role_system":
            return _replace(base, "ROLE_SYSTEM", ROLE_SYSTEM_MESSAGE, reason=code)
        if code == "role_in_use":
            users = details.get("users")
            count = users if isinstance(users, int) else 0
            message = ROLE_IN_USE_MESSAGE.format(employees=count)
            return _replace(base, "ROLE_IN_USE", message, reason=code, employees=count)
        if reason == "email_taken":
            return _replace(base, "EMAIL_EXISTS", EMAIL_EXISTS_MESSAGE, reason=reason)
        if code == "user_has_active_leads":
            return _replace(base, "CONFLICT", ACTIVE_LEADS_MESSAGE, reason=code)
        if details.get("field") == "name":
            return _replace(base, "CONFLICT", NAME_TAKEN_MESSAGE, reason="name_taken")
        if code is not None:
            base.body.details = {**(base.body.details or {}), "reason": reason or code}
    if status == 422 and (fields := _fields(response)):
        base.body.details = {**(base.body.details or {}), "fields": fields}
    return base


def _replace(base: PlatformError, code: str, message: str, **extra: Any) -> PlatformError:
    return PlatformError(
        code,
        message,
        status_code=base.status_code,
        source="crm",
        details={**(base.body.details or {}), **extra},
    )


class CrmUsers:
    def __init__(self, call: Call) -> None:
        self._call = call

    async def _json(self, method: str, path: str, expected: int, *, json: Any = None) -> Any:
        backend: Backend = "crm"
        response = await self._call(backend, method, path, json=json)
        if response.status_code != expected:
            raise crm_error(response)
        return response.json() if response.content else None

    async def list_all(self) -> list[dict[str, Any]]:
        users: list[dict[str, Any]] = await self._json("GET", "/api/v1/users", 200)
        return users

    async def get(self, user_id: str) -> dict[str, Any]:
        user: dict[str, Any] = await self._json("GET", f"/api/v1/users/{user_id}", 200)
        return user

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Создать пользователя; `temporary_password` наружу не отдаётся и в журнал не пишется."""
        created = await self._json("POST", "/api/v1/users", 201, json=payload)
        user: dict[str, Any] = created["user"]
        return user

    async def update(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        user: dict[str, Any] = await self._json(
            "PATCH", f"/api/v1/users/{user_id}", 200, json=payload
        )
        return user

    async def invite(self, user_id: str) -> None:
        """Письмо-приглашение с новым временным паролем (коннектор «Почта» CRM)."""
        await self._json("POST", f"/api/v1/users/{user_id}/invite", 200)


ROLES = "/api/v1/platform-roles"


class CrmRoles:
    """Роли Платформы в CRM (только администратор: `users:write`)."""

    def __init__(self, call: Call) -> None:
        self._users = CrmUsers(call)

    async def list_all(self) -> list[dict[str, Any]]:
        roles: list[dict[str, Any]] = await self._users._json("GET", ROLES, 200)
        return roles

    async def get(self, role_id: str) -> dict[str, Any]:
        role: dict[str, Any] = await self._users._json("GET", f"{ROLES}/{role_id}", 200)
        return role

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        role: dict[str, Any] = await self._users._json("POST", ROLES, 201, json=payload)
        return role

    async def update(self, role_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        role: dict[str, Any] = await self._users._json(
            "PATCH", f"{ROLES}/{role_id}", 200, json=payload
        )
        return role

    async def delete(self, role_id: str) -> None:
        await self._users._json("DELETE", f"{ROLES}/{role_id}", 204)

    async def preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        preview: dict[str, Any] = await self._users._json(
            "POST", f"{ROLES}/preview", 200, json=payload
        )
        return preview
