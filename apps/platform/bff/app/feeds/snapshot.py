"""Сырые данные на один запрос: входящие CRM, очередь одобрения ERP, сделки ERP, письма и документы
на согласовании EDS.

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
LETTERS_PATH = "/api/v1/letters"
LETTERS_PARAMS: dict[str, Any] = {"status": "awaiting_resolution", "limit": APPROVALS_PAGE_SIZE}
APPROVALS_PATH = "/api/v1/approvals"
# Служебные записки, заявления и отчёты на моём шаге маршрута (`mine` — по умолчанию); КП ведёт ERP.
MEMO_PARAMS: dict[str, Any] = {
    "mine": "true",
    "status": "open",
    "template": ["memo", "application", "report"],
    "limit": APPROVALS_PAGE_SIZE,
}
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
    # EDS: `None` — источник не читали или он не ответил (карточка и бейдж без числа: ноль был бы
    # ложью), список — ответ EDS как есть (что EDS вернул по токену сотрудника, то и строки).
    letters: list[dict[str, Any]] | None = None
    memos: list[dict[str, Any]] | None = None
    # Есть следующая страница EDS: число в карточке — «не меньше», а не точное
    letters_more: bool = False
    memos_more: bool = False

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


def wants_letters(view: View) -> bool:
    return view.wants("resolve_letter")


def wants_memos(view: View) -> bool:
    return view.wants("approve_memo") or view.wants("pay_memo")


def wants_projects(view: View) -> bool:
    return allows(view.access, "eds.projects", "read")


def _has_more(payload: Any) -> bool:
    return isinstance(payload, dict) and bool(payload.get("next_cursor"))


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


async def load_snapshot(
    feed: Feed, view: View, *, inbox: bool, approvals: bool, deals: bool, eds: bool = False
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

    async def load_letters() -> None:
        if eds and wants_letters(view):
            payload = await feed.get("eds", LETTERS_PATH, LETTERS_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
            if payload is not None:
                snap.letters = rows(payload)
                snap.letters_more = _has_more(payload)

    async def load_memos() -> None:
        if eds and wants_memos(view):
            payload = await feed.get("eds", APPROVALS_PATH, MEMO_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
            if payload is not None:
                snap.memos = rows(payload)
                snap.memos_more = _has_more(payload)

    async def load_deals() -> None:
        if deals:
            payload = await feed.get("erp", DEALS_PATH, DEALS_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
            snap.deals = rows(payload)

    await asyncio.gather(load_inbox(), load_approvals(), load_deals(), load_letters(), load_memos())
    return snap
