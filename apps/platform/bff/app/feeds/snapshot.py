"""Сырые данные на один запрос: входящие CRM, очередь одобрения ERP, сделки ERP.

Источники — docs/architecture/integration-map.md §1.2.
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
class Covered:
    """Очередь замещаемого коллеги, которую сегодня видит заместитель (W15-H6)."""

    user_id: int
    name: str
    inbox: dict[str, list[dict[str, Any]]]


# Не больше стольких замещаемых за раз: каждый — отдельный запрос в CRM на каждый опрос очереди.
MAX_COVERED = 5


@dataclass
class Snapshot:
    inbox: dict[str, list[dict[str, Any]]] | None = None
    covered: list[Covered] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    approvals_total: int = 0
    deals: list[dict[str, Any]] = field(default_factory=list)
    # Новые обращения сотрудников (CRM `staff-tickets?status=new`): админу — «Мои задачи» (W15-H7).
    tickets: list[dict[str, Any]] = field(default_factory=list)
    tickets_total: int = 0
    # Просроченные заказы поставщикам (ERP `stock/overdue`): снабженцу — «Мои задачи» (D2-2).
    overdue_orders: list[dict[str, Any]] = field(default_factory=list)

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


def wants_tickets(view: View) -> bool:
    return view.wants("ticket")


def wants_supplier_overdue(view: View) -> bool:
    return view.wants("supplier_overdue")


def wants_projects(view: View) -> bool:
    return allows(view.access, "eds.projects", "read")


async def _inbox(
    feed: Feed, params: dict[str, Any] | None = None
) -> dict[str, list[dict[str, Any]]] | None:
    payload = await feed.get("crm", "/api/v1/inbox", params, ttl=SNAPSHOT_TTL_SECONDS)
    if not isinstance(payload, dict):
        return None
    return {key: rows(payload.get(key)) for key in ("escalations", "mine", "unassigned")}


async def _covered(feed: Feed) -> list[Covered]:
    """За кого сотрудник сегодня заместитель и их очереди. Права — свои: CRM отдаёт очередь
    замещаемого только назначенному заместителю в период и только по правам заместителя; сбой
    любого шага даёт пустой список (замещение — добавка к очереди, не её условие)."""
    payload = await feed.get("crm", "/api/v1/me/covering", ttl=SNAPSHOT_TTL_SECONDS)
    people = [
        row
        for row in rows(payload)
        if isinstance(row.get("user_id"), int) and isinstance(row.get("full_name"), str)
    ][:MAX_COVERED]

    async def one(row: dict[str, Any]) -> Covered | None:
        inbox = await _inbox(feed, {"on_behalf_of": row["user_id"]})
        return Covered(int(row["user_id"]), str(row["full_name"]), inbox) if inbox else None

    found = await asyncio.gather(*(one(row) for row in people))
    return [c for c in found if c is not None]


OVERDUE_PATH = "/api/v1/stock/overdue/"
TICKETS_PATH = "/api/v1/staff-tickets"
TICKETS_PARAMS = {"status": "new", "limit": 20}


async def load_snapshot(
    feed: Feed,
    view: View,
    *,
    inbox: bool,
    approvals: bool,
    deals: bool,
    tickets: bool = False,
    stock: bool = False,
) -> Snapshot:
    """Параллельно прочитать нужные источники. `view` — роли «вида» (активная роль, если задана);
    сделки нужны и для подписей к очереди и уведомлениям, поэтому их читает тот, кто их просит."""
    snap = Snapshot()

    async def load_inbox() -> None:
        if inbox and wants_inbox(view):
            snap.inbox, snap.covered = await asyncio.gather(_inbox(feed), _covered(feed))

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

    async def load_tickets() -> None:
        if tickets and wants_tickets(view):
            payload = await feed.get("crm", TICKETS_PATH, TICKETS_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
            snap.tickets = rows(payload)
            total = payload.get("total") if isinstance(payload, dict) else None
            snap.tickets_total = total if isinstance(total, int) else len(snap.tickets)

    async def load_stock() -> None:
        if stock and wants_supplier_overdue(view):
            # ERP не ответил — очередь без просроченных заказов, `sources.erp = unavailable`.
            payload = await feed.get("erp", OVERDUE_PATH, ttl=SNAPSHOT_TTL_SECONDS)
            snap.overdue_orders = rows(payload)

    await asyncio.gather(load_inbox(), load_approvals(), load_deals(), load_tickets(), load_stock())
    return snap
