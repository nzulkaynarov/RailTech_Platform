"""Пользователи CRM для Admin · Оргструктура: `GET/POST/PATCH /api/v1/users*`, `/users/{id}/invite`.

Вызовы идут от имени сотрудника через `Authed.call` (токен CRM из сессии). Право на операцию и
инвариант «хотя бы один активный администратор» решает CRM; здесь — только перевод ответов и ошибок
CRM в формат `Error` контракта (`LAST_ADMIN`, `EMAIL_EXISTS`, `fields` валидации).
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
EMAIL_EXISTS_MESSAGE = "Сотрудник с такой почтой уже есть."
ACTIVE_LEADS_MESSAGE = (
    "У сотрудника есть лиды в работе. Передайте их коллеге в CRM, затем отключите сотрудника "
    "или смените его роль."
)
# Поля CRM -> поля контракта BFF (`details.fields`).
_FIELDS = {"full_name": "name", "platform_roles": "roles", "email": "email", "position": "position"}


def _fields(response: httpx.Response) -> list[str]:
    try:
        body = response.json()
    except ValueError:
        return []
    details = body.get("details") if isinstance(body, dict) else None
    if not isinstance(details, dict):
        return []
    names = [e.get("field") for e in details.get("errors") or [] if isinstance(e, dict)]
    names.append(details.get("field"))
    return sorted({_FIELDS.get(str(n), str(n)) for n in names if n})


def crm_error(response: httpx.Response) -> PlatformError:
    """Ответ CRM 4xx -> ошибка контракта; остальное решает общий перевод `from_backend`."""
    status = response.status_code
    code = backend_code(response)
    reason = backend_reason(response)
    base = from_backend("crm", response)
    if status == 409 and code == "last_admin":
        return _replace(base, "LAST_ADMIN", LAST_ADMIN_MESSAGE)
    if status == 409 and reason == "email_taken":
        return _replace(base, "EMAIL_EXISTS", EMAIL_EXISTS_MESSAGE)
    if status == 409 and code == "user_has_active_leads":
        return _replace(base, "CONFLICT", ACTIVE_LEADS_MESSAGE)
    if status == 422 and (fields := _fields(response)):
        base.body.details = {**(base.body.details or {}), "fields": fields}
    return base


def _replace(base: PlatformError, code: str, message: str) -> PlatformError:
    return PlatformError(
        code, message, status_code=base.status_code, source="crm", details=base.body.details
    )


class CrmUsers:
    def __init__(self, call: Call) -> None:
        self._call = call

    async def _json(
        self, method: str, path: str, expected: int, *, json: Any = None
    ) -> dict[str, Any]:
        backend: Backend = "crm"
        response = await self._call(backend, method, path, json=json)
        if response.status_code != expected:
            raise crm_error(response)
        body: dict[str, Any] = response.json()
        return body

    async def list_all(self) -> list[dict[str, Any]]:
        response = await self._call("crm", "GET", "/api/v1/users")
        if response.status_code != 200:
            raise crm_error(response)
        users: list[dict[str, Any]] = response.json()
        return users

    async def get(self, user_id: str) -> dict[str, Any]:
        return await self._json("GET", f"/api/v1/users/{user_id}", 200)

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Создать пользователя; `temporary_password` наружу не отдаётся и в журнал не пишется."""
        created = await self._json("POST", "/api/v1/users", 201, json=payload)
        user: dict[str, Any] = created["user"]
        return user

    async def update(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._json("PATCH", f"/api/v1/users/{user_id}", 200, json=payload)

    async def invite(self, user_id: str) -> None:
        """Письмо-приглашение с новым временным паролем (коннектор «Почта» CRM)."""
        await self._json("POST", f"/api/v1/users/{user_id}/invite", 200)
