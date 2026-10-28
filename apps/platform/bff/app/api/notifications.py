"""Центр уведомлений (контракт: tag `notifications`): лента ERP и лента CRM (W15-H7)."""

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.deps import Authed, require
from app.errors import PlatformError, from_backend
from app.feeds import notifications as service
from app.feeds.feed import Feed
from app.feeds.models import NotificationPage, NotificationTab
from app.feeds.snapshot import load_snapshot
from app.feeds.view import roles_of_view

router = APIRouter(tags=["notifications"])

# Уведомления нужны каждому сотруднику: раздел `dashboard.queue` открыт всем ролям.
NotifyAuthed = Annotated[Authed, Depends(require("dashboard.queue", "read"))]
_ID = re.compile(r"^(crm|erp):([0-9]+)$")


@router.get(
    "/notifications",
    response_model=NotificationPage,
    response_model_exclude_none=True,
    operation_id="listNotifications",
)
async def list_notifications(
    authed: NotifyAuthed,
    tab: NotificationTab = "all",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = service.DEFAULT_LIMIT,
) -> NotificationPage:
    feed = Feed(authed)
    snap = await load_snapshot(
        feed, roles_of_view(authed, None), inbox=False, approvals=False, deals=True
    )
    return await service.list_notifications(feed, snap, tab, cursor, limit)


def _not_found() -> PlatformError:
    return PlatformError("NOT_FOUND", "Не найдено.", status_code=404)


async def _mark_all(
    feed: Feed, source: Literal["crm", "erp"], method: str, path: str
) -> PlatformError | None:
    """Отметка одной ленты: `None` — отмечена, иначе ошибка источника (вторую ленту не обрывает)."""
    try:
        status = await feed.send(source, method, path)
    except PlatformError as exc:
        return exc
    # 403 CRM — сначала смените временный пароль: ленты CRM у сотрудника ещё нет, не сбой.
    if status >= 400 and not (source == "crm" and status == 403):
        return _failed(status, source)
    return None


@router.post("/notifications/read-all", status_code=204, operation_id="markAllNotificationsRead")
async def mark_all_read(authed: NotifyAuthed) -> Response:
    """Отметить все прочитанными в обеих лентах (у каждой своя), сбой одной не отменяет другую.

    Недоступный источник остаётся непрочитанным и виден в `sources` следующей выдачи ленты; ошибка
    возвращается, только если не отмечена ни одна из лент.
    """
    feed = Feed(authed)
    results: list[PlatformError | None] = []
    if feed.usable("erp"):
        results.append(
            await _mark_all(feed, "erp", "PATCH", "/api/v1/notifications/mark_all_read/")
        )
    results.append(await _mark_all(feed, "crm", "POST", f"{service.CRM_PATH}/read-all"))
    failures = [r for r in results if r is not None]
    if failures and len(failures) == len(results):
        raise failures[0]
    await _forget(feed)
    return Response(status_code=204)


@router.post(
    "/notifications/{notification_id}/read", status_code=204, operation_id="markNotificationRead"
)
async def mark_read(notification_id: str, authed: NotifyAuthed) -> Response:
    match = _ID.match(notification_id)
    if match is None:
        raise PlatformError(
            "VALIDATION_FAILED",
            "Проверьте заполнение полей.",
            status_code=422,
            details={"fields": ["id"]},
        )
    source, number = match.group(1), match.group(2)
    feed = Feed(authed)
    if source == "crm":
        crm_status = await feed.send("crm", "POST", f"{service.CRM_PATH}/{number}/read")
        if crm_status == 404:
            raise _not_found()
        if crm_status >= 400:
            raise _failed(crm_status, "crm")
        await _forget(feed)
        return Response(status_code=204)
    status = await feed.send("erp", "PATCH", f"/api/v1/notifications/{number}/mark_read/")
    if status == 404:
        raise _not_found()
    if status >= 400:
        raise _failed(status)
    await _forget(feed)
    return Response(status_code=204)


async def _forget(feed: Feed) -> None:
    """Отметка «прочитано» устарила кэш ленты: следующий опрос должен увидеть новое состояние."""
    await feed.invalidate("erp", service.NOTIFICATIONS_PATH, service.NOTIFICATIONS_PARAMS)
    await feed.invalidate("crm", service.CRM_PATH)


def _failed(status: int, source: Literal["crm", "erp"] = "erp") -> PlatformError:
    """Бэкенд отказал в отметке (права, лимит): код BFF по статусу ответа."""
    import httpx

    return from_backend(source, httpx.Response(status))
