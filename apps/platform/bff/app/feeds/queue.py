"""«Моя очередь», карточки-счётчики и бейджи меню (04-integration-map.md §1.1–§1.2, SPEC-v3 §7.1).

Источники, которые есть сегодня: MANAGER — CRM `/inbox`; DIRECTOR — ERP `my-approval-queue`;
остальные роли — пусто (письма, служебки, задания и платёжки ждут ERP-01…06). Роль «вида» —
активная, если задана (Q-PLT-12-1), иначе все роли сотрудника.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.feeds.feed import Feed
from app.feeds.models import (
    DueLabel,
    MenuCounter,
    QueueCard,
    QueueItem,
    QueueItemKind,
)
from app.feeds.numbers import deal_title, lead_number, lead_ref, quote_number, quote_ref
from app.feeds.snapshot import Snapshot, wants_inbox, wants_projects
from app.feeds.text import ago, due_label, join, money, now_utc, parse_deadline, parse_dt, short
from app.rbac import allows
from app.rbac_generated import RoleCode

_RANK: dict[DueLabel, int] = {"overdue": 0, "today": 1, "tomorrow": 2, "memo": 3, "later": 4}
MAX_CARDS = 4
_ACTIVE_STAGES = frozenset({"CONTRACT_SIGNED", "CLOSED_WON"})


@dataclass
class Row:
    item: QueueItem
    since: datetime | None  # с какого момента дело ждёт: при равном сроке старшее — выше


def _sort_key(row: Row) -> tuple[int, float, float]:
    due = row.item.due_at.timestamp() if row.item.due_at else float("inf")
    since = row.since.timestamp() if row.since else float("inf")
    return _RANK[row.item.due_label], due, since


def _lead_row(
    lead: dict[str, Any],
    kind: QueueItemKind,
    *,
    why: str | None,
    due_at: datetime | None,
    now: datetime,
) -> Row:
    lead_id = int(lead["id"])
    number = lead_number(lead_id)
    name = str(lead.get("display_name") or number)
    waiting = parse_dt(lead.get("last_lead_msg_at")) or parse_dt(lead.get("created_at"))
    action = "Взять в работу лида" if kind == "take_lead" else "Ответить лиду"
    item = QueueItem(
        id=f"lead:{lead_id}:{kind}",
        role="MANAGER",
        kind=kind,
        title=f"{action} {number}",
        subtitle=join(name, short(why or lead.get("need_summary")), ago(waiting, now)),
        due_label=due_label(due_at, now, default="today"),
        due_at=due_at,
        object=lead_ref(lead_id, name),
    )
    return Row(item, waiting)


def lead_rows(snap: Snapshot, me: int, now: datetime) -> list[Row]:
    """Лиды, по которым ждут именно этого менеджера: передачи бота, ответ клиенту, свободные
    лиды."""
    if snap.inbox is None:
        return []
    seen: set[int] = set()
    out: list[Row] = []

    def add(row: Row, lead_id: int) -> None:
        if lead_id not in seen:
            seen.add(lead_id)
            out.append(row)

    for lead in snap.inbox["escalations"]:
        escalation = lead.get("escalation") or {}
        snoozed = parse_dt(escalation.get("snoozed_until"))
        if snoozed is not None and snoozed > now:
            continue
        taker = escalation.get("taken_by_user_id")
        if taker is not None and taker != me:
            continue
        kind: QueueItemKind = "take_lead" if taker is None else "answer_lead"
        row = _lead_row(
            lead,
            kind,
            why=escalation.get("reason_text"),
            due_at=parse_dt(escalation.get("sla_due_at")),
            now=now,
        )
        add(row, int(lead["id"]))
    for lead in snap.inbox["mine"]:
        if lead.get("unread") is True:
            add(_lead_row(lead, "answer_lead", why=None, due_at=None, now=now), int(lead["id"]))
    for lead in snap.inbox["unassigned"]:
        add(_lead_row(lead, "take_lead", why=None, due_at=None, now=now), int(lead["id"]))
    return out


def quote_rows(snap: Snapshot, now: datetime) -> list[Row]:
    """КП, которые ждут одобрения этого сотрудника (ERP решает, чья очередь — BFF только
    показывает)."""
    deals = snap.deal_index
    out: list[Row] = []
    for quote in snap.approvals:
        if not isinstance(quote.get("id"), int):
            continue
        deal = deals.get(int(quote["deal"])) if isinstance(quote.get("deal"), int) else None
        client = deal_title(deal) if deal else None
        valid_until = parse_deadline(quote.get("valid_until"))
        created = parse_dt(quote.get("created_at"))
        number = quote_number(quote)
        item = QueueItem(
            id=f"quote:{quote['id']}",
            role="DIRECTOR",
            kind="approve_quote",
            title=f"Одобрить {number}",
            subtitle=join(
                client,
                money(quote.get("total_incl_vat"), quote.get("quote_currency")),
                ago(created, now),
            ),
            due_label=due_label(valid_until, now),
            due_at=valid_until,
            object=quote_ref(quote, title=client, drafting=True),
        )
        out.append(Row(item, created))
    return out


def build_queue(feed: Feed, roles: list[RoleCode], snap: Snapshot) -> list[QueueItem]:
    now = now_utc()
    rows_: list[Row] = []
    if wants_inbox(roles):
        rows_ += lead_rows(snap, feed.authed.data.user_id, now)
    if "DIRECTOR" in roles:
        rows_ += quote_rows(snap, now)
    rows_.sort(key=_sort_key)
    return [row.item for row in rows_]


def projects_in_work(snap: Snapshot) -> int:
    """Проекты (договор подписан), исполнение которых не закрыто целиком."""
    return sum(
        1
        for deal in snap.deals
        if deal.get("stage_code") in _ACTIVE_STAGES and deal.get("execution_complete") is not True
    )


def build_cards(roles: list[RoleCode], snap: Snapshot, queue: list[QueueItem]) -> list[QueueCard]:
    """Набор карточек задаёт роль (SPEC-v3 §7.1); карточки без источника не показываются — ноль был
    бы ложью."""
    cards: dict[str, QueueCard] = {}
    if wants_inbox(roles):
        answer = sum(1 for i in queue if i.kind == "answer_lead")
        take = sum(1 for i in queue if i.kind == "take_lead")
        cards["leads_without_answer"] = QueueCard(
            key="leads_without_answer",
            label="Лиды без ответа",
            count=answer,
            hint="CRM · Все сообщения",
            path="/crm/messages",
        )
        cards["leads_to_take"] = QueueCard(
            key="leads_to_take",
            label="Лиды без менеджера",
            count=take,
            hint="CRM · Все сообщения",
            path="/crm/messages",
        )
    if "DIRECTOR" in roles:
        cards["quotes_to_approve"] = QueueCard(
            key="quotes_to_approve",
            label="КП на одобрение",
            count=snap.approvals_total,
            hint="EDS · Черновик",
            path="/eds/drafts",
        )
    if wants_projects(roles):
        cards["projects_in_work"] = QueueCard(
            key="projects_in_work",
            label="Проекты в работе",
            count=projects_in_work(snap),
            hint="EDS · Все проекты",
            path="/eds/projects",
        )
    return list(cards.values())[:MAX_CARDS]


def build_counters(
    roles: list[RoleCode], snap: Snapshot, queue: list[QueueItem]
) -> list[MenuCounter]:
    """Бейджи подменю: красный — требует действия, серый — счётчик. Пункты вне роли не
    перечисляются."""
    items = [
        MenuCounter(module="dashboard", section="queue", count=len(queue), attention=bool(queue))
    ]
    if wants_inbox(roles) and allows(roles, "crm.leads", "full"):
        waiting = sum(1 for i in queue if i.kind in ("answer_lead", "take_lead"))
        items.append(
            MenuCounter(module="crm", section="messages", count=waiting, attention=waiting > 0)
        )
    if "DIRECTOR" in roles and allows(roles, "eds.drafts", "full"):
        total = snap.approvals_total
        items.append(MenuCounter(module="eds", section="drafts", count=total, attention=total > 0))
    if wants_projects(roles):
        total = projects_in_work(snap)
        items.append(
            MenuCounter(module="dashboard", section="projects", count=total, attention=False)
        )
        items.append(MenuCounter(module="eds", section="projects", count=total, attention=False))
    return items
