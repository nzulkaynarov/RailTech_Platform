"""Лента «Сегодня» бокового окна Dashboard: события компании за день по календарю компании.

Источник — ERP `GET /crm/activity-logs/`: журнал платформы, ERP отдаёт его только администратору
платформы. Остальным сотрудникам лента собирается из `GET /crm/timeline/` по новейшим доступным им
сделкам — тот же журнал в границах доступа к сделке (04-integration-map.md §1.2). Сквозная лента для
сотрудников без доступа к журналу — разрыв ERP (docs/QUESTIONS.md, Q-PLT-14-3).
"""

import asyncio
from typing import Any

from app.feeds.feed import SNAPSHOT_TTL_SECONDS, Feed, rows
from app.feeds.models import ActivityFeed, ActivityItem, PersonRef
from app.feeds.numbers import deal_number, deal_ref
from app.feeds.snapshot import Snapshot
from app.feeds.text import company_day, now_utc, parse_dt, short
from app.rbac_generated import ModuleCode
from app.schemas import initials_of

FEED_SIZE = 8
LOG_PAGE = 50
TIMELINE_DEALS = 5
TIMELINE_PER_DEAL = 10
_MANUAL = "[MANUAL_MODE]"
_ADMIN_ENTITIES = frozenset({"user", "setting", "integration", "email_template"})


def _item(entry: dict[str, Any], deals: dict[int, dict[str, Any]]) -> ActivityItem | None:
    at = parse_dt(entry.get("timestamp"))
    if at is None or not isinstance(entry.get("id"), int):
        return None
    deal = deals.get(entry["deal_id"]) if isinstance(entry.get("deal_id"), int) else None
    name = str(entry.get("user_name") or "").strip() or "Система"
    text = short(str(entry.get("action") or "").replace(_MANUAL, "").strip(), 120)
    if not text:
        return None
    if deal is not None:
        text = f"{text} · {deal_number(deal)}"
    module: ModuleCode = "erp" if str(entry.get("entity_type") or "") in _ADMIN_ENTITIES else "eds"
    return ActivityItem(
        id=f"erp:{entry['id']}",
        actor=PersonRef(id="", name=name, initials=initials_of(name, "")),
        text=text,
        module=module,
        at=at,
        object=deal_ref(deal) if deal is not None else None,
    )


async def _timeline(feed: Feed, snap: Snapshot) -> list[dict[str, Any]]:
    payloads = await asyncio.gather(
        *(
            feed.get(
                "erp",
                "/api/v1/crm/timeline/",
                {"deal_id": deal["id"], "limit": TIMELINE_PER_DEAL},
                ttl=SNAPSHOT_TTL_SECONDS,
            )
            for deal in snap.deals[:TIMELINE_DEALS]
            if isinstance(deal.get("id"), int)
        )
    )
    return [entry for payload in payloads for entry in rows(payload)]


# TODO(ERP-16): сквозная лента «Сегодня» по правам сотрудника в ERP; пока — журнал или timeline.
async def today(feed: Feed, snap: Snapshot) -> ActivityFeed:
    payload = await feed.get(
        "erp",
        "/api/v1/crm/activity-logs/",
        {"page_size": LOG_PAGE},
        ttl=SNAPSHOT_TTL_SECONDS,
        remember_refusal=True,
    )
    entries = rows(payload)
    if payload is None and feed.states["erp"] == "ok":
        # Журнал платформы закрыт для сотрудника (403): лента из таймлайнов его сделок.
        entries = await _timeline(feed, snap)
    deals = snap.deal_index
    now = now_utc()
    seen: set[str] = set()
    items: list[ActivityItem] = []
    for entry in entries:
        item = _item(entry, deals)
        if item is None or item.id in seen or company_day(item.at) != company_day(now):
            continue
        seen.add(item.id)
        items.append(item)
    items.sort(key=lambda i: i.at, reverse=True)
    return ActivityFeed(items=items[:FEED_SIZE], sources=feed.sources)
