"""Личный календарь по секретной ссылке (tag `calendar`): профиль выдаёт ссылку, календарный
клиент читает ленту без сессии. Устройство и хранение — `app/calendar_link.py`."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app import calendar_link
from app.deps import AuthedDep, RedisDep
from app.errors import PlatformError, from_backend
from app.reset_limit import HourlyLimiter

router = APIRouter(tags=["calendar"])

CRM_LINK = "/api/v1/me/calendar-link"
MIN_TOKEN_LENGTH = 40


class CalendarLink(BaseModel):
    """Состояние ссылки сотрудника: действует ли и когда выдана."""

    active: bool
    issued_at: str | None = None


class CalendarLinkIssued(BaseModel):
    """Новая ссылка: путь с секретным токеном виден один раз."""

    path: str
    url: str
    issued_at: str


def _origin(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin and origin.startswith(("https://", "http://")):
        return origin.rstrip("/")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    return f"{scheme}://{host}" if host else ""


@router.get("/me/calendar-link", response_model=CalendarLink, operation_id="getCalendarLink")
async def get_calendar_link(authed: AuthedDep, redis: RedisDep) -> CalendarLink:
    found = await calendar_link.state(redis, authed.data.user_id)
    return CalendarLink(active=found.active, issued_at=found.issued_at)


@router.post(
    "/me/calendar-link", response_model=CalendarLinkIssued, operation_id="issueCalendarLink"
)
async def issue_calendar_link(
    request: Request, authed: AuthedDep, redis: RedisDep
) -> CalendarLinkIssued:
    """Выдать новую ссылку; прежняя перестаёт действовать (CRM хранит хеш токена)."""
    response = await authed.call("crm", "POST", CRM_LINK)
    if response.status_code != 200:
        raise from_backend("crm", response)
    body: dict[str, Any] = response.json()
    token = str(body["token"])
    issued_at = str(body.get("issued_at") or datetime.now(UTC).isoformat())
    origin = _origin(request)
    await calendar_link.activate(redis, authed.data.user_id, token, issued_at, origin)
    path = f"/api/v1/calendar/{token}.ics"
    return CalendarLinkIssued(path=path, url=f"{origin}{path}", issued_at=issued_at)


@router.get(
    "/calendar/{name}",
    operation_id="getCalendarFeed",
    response_class=Response,
    include_in_schema=True,
)
async def get_calendar_feed(name: str, request: Request, redis: RedisDep) -> Response:
    """Лента сроков сотрудника для календарного клиента; доступ — только по секретному токену.
    Токен неизвестен, заменён или просрочен — 404 (причина не различается)."""
    limiter = HourlyLimiter(redis, "calendar-miss", calendar_link.FAILURE_LIMIT_PER_HOUR)
    token = name.removesuffix(".ics")
    body = (
        await calendar_link.render(redis, token)
        if name.endswith(".ics") and len(token) >= MIN_TOKEN_LENGTH
        else None
    )
    if body is None:
        await limiter.check(request.state.client_ip)
        raise PlatformError("NOT_FOUND", "Не найдено.", status_code=404)
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": calendar_link.CACHE_CONTROL,
            "Content-Disposition": 'inline; filename="railtech.ics"',
        },
    )
