"""Центр уведомлений (контракт: tag `notifications`): лента ERP, CRM-лента появится с CRM-04."""

import re
from typing import Annotated

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


@router.post("/notifications/read-all", status_code=204, operation_id="markAllNotificationsRead")
async def mark_all_read(authed: NotifyAuthed) -> Response:
    """Отметить все прочитанными: у ERP такая операция есть, у CRM уведомлений пока нет (CRM-04)."""
    feed = Feed(authed)
    if feed.usable("erp"):
        status = await feed.send("erp", "PATCH", "/api/v1/notifications/mark_all_read/")
        if status >= 400:
            raise _failed(status)
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
    if source == "crm":
        # Уведомлений CRM пока нет (CRM-04): такого идентификатора не существует.
        raise _not_found()
    feed = Feed(authed)
    status = await feed.send("erp", "PATCH", f"/api/v1/notifications/{number}/mark_read/")
    if status == 404:
        raise _not_found()
    if status >= 400:
        raise _failed(status)
    return Response(status_code=204)


def _failed(status: int) -> PlatformError:
    """Бэкенд отказал в отметке (права, лимит): код BFF по статусу ответа."""
    import httpx

    return from_backend("erp", httpx.Response(status))
