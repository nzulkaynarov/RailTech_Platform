"""Клиент EDS (`eds-api`): обмен токена сотрудника CRM на токен доступа EDS.

Контракт — `packages/contracts/openapi/eds.yaml`; вход — `docs/architecture/sso-token.md`, «Токен
сотрудника для EDS»: CRM `POST /api/v1/auth/sso/token {"aud": "eds"}` → EDS `POST
/api/v1/auth/sso/exchange` → токен доступа EDS на 15 минут, без refresh (истёк — BFF обменивает
новый токен CRM). Внешнего маршрута у EDS нет: только сеть compose. Health — `/health`.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.clients.base import BackendClient
from app.errors import PlatformError, backend_unavailable


class EdsClient(BackendClient):
    def __init__(self, base_url: str) -> None:
        super().__init__("eds", base_url, "/health")

    async def sso_exchange(self, sso_token: str) -> httpx.Response:
        return await self.send("POST", "/api/v1/auth/sso/exchange", json={"token": sso_token})


# --- Входящие письма и резолюция (D1-3, контракт BFF 0.16.0) ---------------------------------

Call = Callable[..., Awaitable[httpx.Response]]

# Сообщения BFF, если EDS не прислал текст (его `message` — уже на языке сотрудника, берём его).
_EDS_MESSAGES: dict[int, tuple[str, str]] = {
    403: ("FORBIDDEN", "Раздел или действие не положены вашей роли."),
    404: ("NOT_FOUND", "Не найдено."),
    409: ("CONFLICT", "Объект изменился. Обновите страницу."),
    422: ("VALIDATION_FAILED", "Проверьте заполнение полей."),
}


def _eds_body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _field_names(raw: Any) -> list[str]:
    """`details.fields` EDS — `[{field, message, type}]`; BFF отдаёт имена полей без `body.`."""
    names: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            name = item.get("field") if isinstance(item, dict) else item
            if isinstance(name, str) and name:
                names.append(name.removeprefix("body."))
    return names


def eds_error(response: httpx.Response) -> PlatformError:
    """Ответ EDS 4xx -> ошибка BFF в формате `Error` (`source = eds`).

    Текст `message` EDS (на языке сотрудника) сохраняется для 409 и 422: «Срок расчёта не может быть
    в прошлом.» полезнее общей фразы. В `details`: код и статус EDS, `reason`, `permission`, поля
    валидации списком имён и первая причина по полю (`due_in_past`, `not_active_employee`).
    """
    known = _EDS_MESSAGES.get(response.status_code)
    if known is None:
        return backend_unavailable("eds", f"HTTP {response.status_code}")
    code, message = known
    body = _eds_body(response)
    raw_details = body.get("details")
    eds_details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
    details: dict[str, Any] = {"backend_status": response.status_code}
    if isinstance(body.get("code"), str):
        details["backend_code"] = body["code"]
    for key in ("reason", "permission"):
        if isinstance(eds_details.get(key), str):
            details[key] = eds_details[key]
    if response.status_code == 422:
        raw_fields = eds_details.get("fields")
        details["fields"] = _field_names(raw_fields)
        if isinstance(raw_fields, list) and raw_fields and isinstance(raw_fields[0], dict):
            first = raw_fields[0].get("message")
            if isinstance(first, str) and re.fullmatch(r"[a-z_]+", first):
                details["reason"] = first
    eds_message = body.get("message")
    if response.status_code in (409, 422) and isinstance(eds_message, str) and eds_message:
        message = eds_message
    return PlatformError(
        code, message, status_code=response.status_code, source="eds", details=details
    )


class EdsLetters:
    """Входящие письма EDS (`eds.yaml` letters, registry, files) от имени сотрудника.

    Вызов идёт через `Authed.call("eds", …)`: токен доступа EDS — обмен токена сотрудника CRM
    (`app.auth`). Решает EDS (права `letters.*`, переходы статусов, срок, исполнители); здесь
    только вызовы и перевод ошибок.
    """

    def __init__(self, call: Call) -> None:
        self._call = call

    async def _json(self, method: str, path: str, ok: int = 200, **kw: Any) -> Any:
        response = await self._call("eds", method, path, **kw)
        if response.status_code != ok:
            raise eds_error(response)
        try:
            return response.json()
        except ValueError as exc:
            raise backend_unavailable("eds", "bad_response") from exc

    async def page(self, params: dict[str, Any]) -> dict[str, Any]:
        page: dict[str, Any] = await self._json("GET", "/api/v1/letters", params=params)
        return page

    async def get(self, letter_id: str) -> dict[str, Any]:
        letter: dict[str, Any] = await self._json("GET", f"/api/v1/letters/{letter_id}")
        return letter

    async def id_by_number(self, number: str) -> str | None:
        """Id письма по номеру `ВХ-104/26`: реестр EDS (`GET /registry?number=`), входящие."""
        page: dict[str, Any] = await self._json(
            "GET",
            "/api/v1/registry",
            params={"number": number, "kind": "letter_in", "limit": 1},
        )
        for item in page.get("items") or []:
            if (
                isinstance(item, dict)
                and item.get("kind") == "letter_in"
                and item.get("number") == number
            ):
                found = item.get("id")
                return found if isinstance(found, str) else None
        return None

    async def resolve(self, letter_id: str, body: dict[str, Any]) -> dict[str, Any]:
        letter: dict[str, Any] = await self._json(
            "POST", f"/api/v1/letters/{letter_id}/resolution", json=body
        )
        return letter

    async def send_back(self, letter_id: str, comment: str) -> dict[str, Any]:
        letter: dict[str, Any] = await self._json(
            "POST", f"/api/v1/letters/{letter_id}/return", json={"comment": comment}
        )
        return letter

    async def reject(self, letter_id: str, reason: str) -> dict[str, Any]:
        letter: dict[str, Any] = await self._json(
            "POST", f"/api/v1/letters/{letter_id}/reject", json={"reason": reason}
        )
        return letter

    async def file(self, file_id: str) -> httpx.Response:
        """Файл потоком (`stream`): ответ открыт, закрывает вызывающий."""
        return await self._call("eds", "GET", f"/api/v1/files/{file_id}", stream=True)
