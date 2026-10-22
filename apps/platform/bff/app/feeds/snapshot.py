"""Сырые данные на один запрос: входящие CRM, очередь одобрения ERP, сделки ERP.

Источники — 04-integration-map.md §1.2.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.feeds.feed import SNAPSHOT_TTL_SECONDS, Feed, rows
from app.rbac import View, allows

# Сделки ERP постранично (DRF: максимум 200 на страницу); берём новейшие — поиск и счётчики
# работают по ним.
DEALS_PAGE_SIZE = 100
APPROVALS_PAGE_SIZE = 50
DEALS_PATH = "/api/v1/crm/deals/"
DEALS_PARAMS = {"page_size": DEALS_PAGE_SIZE}


@dataclass
class Snapshot:
    inbox: dict[str, list[dict[str, Any]]] | None = None
    approvals: list[dict[str, Any]] = field(default_factory=list)
    approvals_total: int = 0
    deals: list[dict[str, Any]] = field(default_factory=list)

    @property
    def deal_index(self) -> dict[int, dict[str, Any]]:
        return {int(d["id"]): d for d in self.deals if isinstance(d.get("id"), int)}


# Виды работы по лидам (секция `queue` каталога): их даёт раздел CRM-лидов; без него BFF не зовёт
# CRM `/inbox` (у сотрудника нет прав CRM на лиды — был бы 403).
LEAD_KINDS = ("answer_lead", "take_lead")


def wants_inbox(view: View) -> bool:
    return any(view.wants(kind) for kind in LEAD_KINDS)


def wants_approvals(view: View) -> bool:
    return view.wants("approve_quote")


def wants_projects(view: View) -> bool:
    return allows(view.access, "eds.projects", "read")


async def _inbox(feed: Feed) -> dict[str, list[dict[str, Any]]] | None:
    payload = await feed.get("crm", "/api/v1/inbox", ttl=SNAPSHOT_TTL_SECONDS)
    if not isinstance(payload, dict):
        return None
    return {key: rows(payload.get(key)) for key in ("escalations", "mine", "unassigned")}


async def load_snapshot(
    feed: Feed, view: View, *, inbox: bool, approvals: bool, deals: bool
) -> Snapshot:
    """Параллельно прочитать нужные источники. `view` — роли «вида» (активная роль, если задана);
    сделки нужны и для подписей к очереди и уведомлениям, поэтому их читает тот, кто их просит."""
    snap = Snapshot()

    async def load_inbox() -> None:
        if inbox and wants_inbox(view):
            snap.inbox = await _inbox(feed)

    async def load_approvals() -> None:
        if approvals and wants_approvals(view):
            payload = await feed.get(
                "erp",
                "/api/v1/crm/quotes/my-approval-queue/",
                {"page_size": APPROVALS_PAGE_SIZE},
                ttl=SNAPSHOT_TTL_SECONDS,
            )
            snap.approvals = rows(payload)
            total = payload.get("count") if isinstance(payload, dict) else None
            snap.approvals_total = total if isinstance(total, int) else len(snap.approvals)

    async def load_deals() -> None:
        if deals:
            payload = await feed.get("erp", DEALS_PATH, DEALS_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
            snap.deals = rows(payload)

    await asyncio.gather(load_inbox(), load_approvals(), load_deals())
    return snap
