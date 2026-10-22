"""Сырые данные на один запрос: входящие CRM, очередь одобрения ERP, сделки ERP.

Источники — 04-integration-map.md §1.2.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.feeds.feed import SNAPSHOT_TTL_SECONDS, Feed, rows
from app.rbac import allows
from app.rbac_generated import RoleCode

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


def wants_inbox(roles: list[RoleCode]) -> bool:
    return "MANAGER" in roles


def wants_approvals(roles: list[RoleCode]) -> bool:
    return "DIRECTOR" in roles


def wants_projects(roles: list[RoleCode]) -> bool:
    return allows(roles, "eds.projects", "read")


async def _inbox(feed: Feed) -> dict[str, list[dict[str, Any]]] | None:
    payload = await feed.get("crm", "/api/v1/inbox", ttl=SNAPSHOT_TTL_SECONDS)
    if not isinstance(payload, dict):
        return None
    return {key: rows(payload.get(key)) for key in ("escalations", "mine", "unassigned")}


async def load_snapshot(
    feed: Feed, roles: list[RoleCode], *, inbox: bool, approvals: bool, deals: bool
) -> Snapshot:
    """Параллельно прочитать нужные источники. `roles` — роли «вида» (активная роль, если задана);
    сделки
    нужны и для подписей к очереди и уведомлениям, поэтому их читает тот, кто их просит."""
    snap = Snapshot()

    async def load_inbox() -> None:
        if inbox and wants_inbox(roles):
            snap.inbox = await _inbox(feed)

    async def load_approvals() -> None:
        if approvals and wants_approvals(roles):
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
