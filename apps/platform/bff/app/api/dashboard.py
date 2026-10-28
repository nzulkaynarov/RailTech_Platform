"""Dashboard: счётчики меню, «Моя очередь», карточки, лента «Сегодня» (контракт: tag
`dashboard`)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import Authed, require
from app.feeds import activity, queue
from app.feeds.feed import Feed
from app.feeds.models import ActivityFeed, MenuCounters, Queue, QueueCards
from app.feeds.snapshot import load_snapshot, wants_approvals, wants_projects
from app.feeds.view import roles_of_view

router = APIRouter(tags=["dashboard"])

QueueAuthed = Annotated[Authed, Depends(require("dashboard.queue", "read"))]
RoleParam = Annotated[
    str | None, Query(pattern=r"^[1-9][0-9]*$", description="Только очередь этой роли (id)")
]


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
        tickets=True,
        stock=True,
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
        tickets=True,
        stock=True,
    )
    return Queue(items=queue.build_queue(feed, view, snap), sources=feed.sources)


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
        tickets=True,
        stock=True,
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
