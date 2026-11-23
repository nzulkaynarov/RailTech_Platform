"""Dashboard: счётчики меню, «Моя очередь», карточки, лента «Сегодня» (контракт: tag
`dashboard`)."""

from typing import Annotated
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, Depends, Path, Query
from redis.exceptions import RedisError

from app import calendar_link, session
from app.deps import Authed, require
from app.eds_documents import API, EdsProxy, eds_error
from app.errors import PlatformError
from app.feeds import activity, queue, waiting
from app.feeds.feed import Feed
from app.feeds.models import (
    ActivityFeed,
    MenuCounters,
    Queue,
    QueueCards,
    QueueItem,
    Reminded,
    Sources,
    Waiting,
    WaitingKind,
)
from app.feeds.snapshot import load_snapshot, wants_approvals, wants_projects
from app.feeds.view import roles_of_view

router = APIRouter(tags=["dashboard"])
log = structlog.get_logger()

QueueAuthed = Annotated[Authed, Depends(require("dashboard.queue", "read"))]
RoleParam = Annotated[
    str | None, Query(pattern=r"^[1-9][0-9]*$", description="Только очередь этой роли (id)")
]


async def publish_calendar(authed: Authed, items: list[QueueItem], sources: Sources) -> None:
    """Снимок сроков для личного календаря сотрудника (`app/calendar_link.py`). Неполная очередь
    (источник не ответил) снимок не заменяет: срок не пропадает из календаря из-за сбоя."""
    if "unavailable" in sources.model_dump().values():
        return
    try:
        redis = authed.service.store.redis
        await calendar_link.store_snapshot(redis, authed.data.user_id, items, session.now())
    except RedisError:  # календарь — добавка к очереди, а не её условие
        log.warning("calendar_snapshot_failed")


@router.get("/menu-counters", response_model=MenuCounters, operation_id="getMenuCounters")
async def get_menu_counters(authed: QueueAuthed) -> MenuCounters:
    feed = Feed(authed)
    view = roles_of_view(authed, None)
    snap = await load_snapshot(
        feed,
        view,
        inbox=True,
        approvals=True,
        deals=wants_projects(view),
        eds=True,
        tickets=True,
        stock=True,
        work=True,
    )
    items = queue.build_queue(feed, view, snap)
    return MenuCounters(items=queue.build_counters(view, snap, items), sources=feed.sources)


@router.get(
    "/queue", response_model=Queue, response_model_exclude_none=True, operation_id="getQueue"
)
async def get_queue(authed: QueueAuthed, role: RoleParam = None) -> Queue:
    feed = Feed(authed)
    view = roles_of_view(authed, role)
    snap = await load_snapshot(
        feed,
        view,
        inbox=True,
        approvals=True,
        deals=wants_approvals(view),
        eds=True,
        tickets=True,
        stock=True,
        work=True,
    )
    items = queue.build_queue(feed, view, snap)
    await publish_calendar(authed, items, feed.sources)
    return Queue(
        items=items, sources=feed.sources, truncated=True if queue.is_truncated(snap) else None
    )


@router.get(
    "/queue/cards",
    response_model=QueueCards,
    response_model_exclude_none=True,
    operation_id="getQueueCards",
)
async def get_queue_cards(authed: QueueAuthed, role: RoleParam = None) -> QueueCards:
    feed = Feed(authed)
    view = roles_of_view(authed, role)
    snap = await load_snapshot(
        feed,
        view,
        inbox=True,
        approvals=True,
        deals=wants_projects(view) or wants_approvals(view),
        eds=True,
        tickets=True,
        stock=True,
        work=True,
    )
    items = queue.build_queue(feed, view, snap)
    return QueueCards(cards=queue.build_cards(view, snap, items), sources=feed.sources)


@router.get(
    "/activity/today",
    response_model=ActivityFeed,
    response_model_exclude_none=True,
    operation_id="getActivityToday",
)
async def get_activity_today(authed: QueueAuthed) -> ActivityFeed:
    feed = Feed(authed)
    snap = await load_snapshot(
        feed, roles_of_view(authed, None), inbox=False, approvals=False, deals=True
    )
    return await activity.today(feed, snap)


@router.get(
    "/queue/waiting",
    response_model=Waiting,
    response_model_exclude_none=True,
    operation_id="getQueueWaiting",
)
async def get_queue_waiting(authed: QueueAuthed) -> Waiting:
    """«Вы ждёте других» (ГЛ-1): что я передал и жду от другого; строки вычисляет EDS."""
    feed = Feed(authed)
    rows, more = await waiting.load_waiting(feed)
    return Waiting(items=rows, truncated=True if more else None, sources=feed.sources)


@router.post(
    "/queue/waiting/{kind}/{id}/remind", response_model=Reminded, operation_id="remindQueueWaiting"
)
async def remind_queue_waiting(
    kind: WaitingKind, id: Annotated[UUID, Path()], authed: QueueAuthed
) -> Reminded:
    """«Напомнить»: EDS повторяет уведомление адресату, не чаще раза в час на объект."""
    proxy = EdsProxy(authed.call)
    response = await proxy.raw("POST", f"{API}/waiting/{kind}/{id}/remind")
    if response.status_code == 429:
        raise PlatformError(
            "TOO_MANY_REQUESTS",
            "Напоминание уже отправлено. Повторить можно позже.",
            status_code=429,
            source="eds",
            details={"reason": "remind_rate_limited", **_retry(response)},
            headers={"Retry-After": str(_retry(response).get("retry_after_seconds", 3600))},
        )
    if response.status_code != 200:
        raise eds_error(response)
    await Feed(authed).invalidate("eds", waiting.WAITING_PATH)
    return Reminded.model_validate(response.json())


def _retry(response: httpx.Response) -> dict[str, int]:
    try:
        body = response.json()
    except ValueError:
        return {}
    details = body.get("details") if isinstance(body, dict) else None
    seconds = details.get("retry_after_seconds") if isinstance(details, dict) else None
    return {"retry_after_seconds": seconds} if isinstance(seconds, int) else {}
