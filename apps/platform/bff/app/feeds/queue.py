"""«Моя очередь», карточки-счётчики и бейджи меню.

Основание: docs/architecture/integration-map.md §1.1–§1.2, SPEC-v3 §7.1.

Виды работы — секция `queue` каталога (`platform-rbac.yaml`): вид попадает в очередь, если у ролей
«вида» есть его раздел с нужным уровнем (ADR-0012 п. 6, названия ролей не используются).
Источники сегодня: лиды — CRM `/inbox` (`answer_lead`, `take_lead`); одобрение КП — ERP
`my-approval-queue` (`approve_quote`); письма без резолюции (`resolve_letter`) и служебки,
заявления, отчёты на моём шаге маршрута (`approve_memo`, `pay_memo`) — EDS по токену `aud=eds`
(D1-6): что вернул EDS, то и строки. Задания и платёжки ждут ERP-02…06. Роли «вида» — активная,
если задана (Q-PLT-12-1), иначе все роли сотрудника. `QueueItem.role_id` — первая роль «вида»,
которая даёт этот вид работы.
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
    QueueOwner,
)
from app.feeds.numbers import (
    deal_title,
    lead_number,
    lead_ref,
    letter_ref,
    memo_ref,
    quote_number,
    quote_ref,
    ticket_ref,
)
from app.feeds.rework import rework_item
from app.feeds.snapshot import (
    Covered,
    Snapshot,
    wants_approvals,
    wants_inbox,
    wants_letters,
    wants_memos,
    wants_projects,
    wants_tickets,
)
from app.feeds.text import ago, due_label, join, money, now_utc, parse_deadline, parse_dt, short
from app.rbac import View

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


def _role_id(view: View, kind: QueueItemKind) -> str:
    role = view.role_for(kind)
    return str(role) if role is not None else ""


def _lead_row(
    lead: dict[str, Any],
    kind: QueueItemKind,
    *,
    role_id: str,
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
        role_id=role_id,
        kind=kind,
        title=f"{action} {number}",
        subtitle=join(name, short(why or lead.get("need_summary")), ago(waiting, now)),
        due_label=due_label(due_at, now, default="today"),
        due_at=due_at,
        object=lead_ref(lead_id, name, conversation=True),
    )
    return Row(item, waiting)


# TODO(CRM-08): `/inbox` «мои» на стороне CRM; пока BFF отбирает чужие передачи и отложенные сам.
def lead_rows(snap: Snapshot, me: int, now: datetime, view: View) -> list[Row]:
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
        if not view.wants(kind):
            continue
        row = _lead_row(
            lead,
            kind,
            role_id=_role_id(view, kind),
            why=escalation.get("reason_text"),
            due_at=parse_dt(escalation.get("sla_due_at")),
            now=now,
        )
        add(row, int(lead["id"]))
    if view.wants("answer_lead"):
        answer = _role_id(view, "answer_lead")
        for lead in snap.inbox["mine"]:
            if lead.get("unread") is True:
                row = _lead_row(lead, "answer_lead", role_id=answer, why=None, due_at=None, now=now)
                add(row, int(lead["id"]))
    if view.wants("take_lead"):
        take = _role_id(view, "take_lead")
        for lead in snap.inbox["unassigned"]:
            row = _lead_row(lead, "take_lead", role_id=take, why=None, due_at=None, now=now)
            add(row, int(lead["id"]))
    return out


def covered_rows(covered: Covered, now: datetime, view: View, skip: set[int]) -> list[Row]:
    """Лиды замещаемого, которые ждут ответа, с пометкой «за {имя}». Только то, что принадлежит
    ему лично (его «мои» с новым сообщением и эскалации, которые взял он): общие передачи и лиды без
    менеджера заместитель и так видит в своей очереди, а чужие дела не дублируются. Права на сам
    объект — заместителя: CRM проверит их при открытии, строка их не расширяет."""
    if not view.wants("answer_lead"):
        return []
    owner = QueueOwner(id=str(covered.user_id), name=covered.name)
    role = _role_id(view, "answer_lead")
    seen: set[int] = set()
    out: list[Row] = []

    def add(row: Row, lead_id: int) -> None:
        if lead_id in seen or lead_id in skip:
            return
        seen.add(lead_id)
        row.item = row.item.model_copy(
            update={"id": f"{row.item.id}:for:{covered.user_id}", "on_behalf_of": owner}
        )
        out.append(row)

    for lead in covered.inbox["escalations"]:
        escalation = lead.get("escalation") or {}
        snoozed = parse_dt(escalation.get("snoozed_until"))
        if escalation.get("taken_by_user_id") != covered.user_id:
            continue
        if snoozed is not None and snoozed > now:
            continue
        row = _lead_row(
            lead,
            "answer_lead",
            role_id=role,
            why=escalation.get("reason_text"),
            due_at=parse_dt(escalation.get("sla_due_at")),
            now=now,
        )
        add(row, int(lead["id"]))
    for lead in covered.inbox["mine"]:
        if lead.get("unread") is True:
            add(
                _lead_row(lead, "answer_lead", role_id=role, why=None, due_at=None, now=now),
                int(lead["id"]),
            )
    return out


def quote_rows(snap: Snapshot, now: datetime, view: View) -> list[Row]:
    """КП, которые ждут одобрения этого сотрудника (ERP решает, чья очередь — BFF только
    показывает)."""
    deals = snap.deal_index
    role_id = _role_id(view, "approve_quote")
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
            role_id=role_id,
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


def rework_rows(snap: Snapshot, now: datetime, view: View) -> list[Row]:
    """Мои документы, которые вернули на доработку (EDS по токену автора): «Доработать»."""
    role_id = _role_id(view, "rework_document")
    return [Row(*rework_item(entry, now, role_id=role_id)) for entry in snap.rework or []]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def letter_rows(snap: Snapshot, now: datetime, view: View) -> list[Row]:
    """Письма «Ждёт резолюции» (EDS): срок — из письма, без срока срочное — сегодня."""
    role_id = _role_id(view, "resolve_letter")
    out: list[Row] = []
    for letter in snap.letters or []:
        number = letter.get("number")
        letter_id = letter.get("id")
        if not isinstance(number, str) or not number or not isinstance(letter_id, str):
            continue
        sender = _dict(letter.get("sender"))
        links = _dict(letter.get("links"))
        received = parse_dt(letter.get("received_at"))
        due_at = parse_deadline(letter.get("due"))
        subject = short(letter.get("subject"), 80)
        item = QueueItem(
            id=f"letter:{letter_id}",
            role_id=role_id,
            kind="resolve_letter",
            title=f"Наложить резолюцию на письмо {number}",
            subtitle=join(
                _text(sender.get("name")),
                subject,
                _text(links.get("deal_number")),
                ago(received, now),
            ),
            due_label=due_label(due_at, now, default="today" if letter.get("urgent") else "later"),
            due_at=due_at,
            object=letter_ref(number, subject or None),
        )
        out.append(Row(item, received))
    return out


_MEMO_TITLES = {"approve_memo": "Согласовать", "pay_memo": "Принять к оплате"}


_MEMO_KIND_BY_PERMISSION: dict[str, QueueItemKind] = {
    "memos.approve": "approve_memo",
    "approvals.decide": "approve_memo",
    "payments.confirm": "pay_memo",
}


def _memo_kind(step: dict[str, Any], view: View) -> QueueItemKind:
    """Вид строки — по праву, которое держит текущий шаг маршрута (EDS): директор, у которого есть и
    право бухгалтера, на шаге бухгалтера видит «Принять к оплате», а не «Согласовать». Шаг
    конкретного сотрудника (права нет) или вид, не положенный роли, — тот, что даёт раздел роли."""
    permission = _text(_dict(step.get("assignee")).get("permission"))
    preferred = _MEMO_KIND_BY_PERMISSION.get(permission or "")
    for kind in (preferred, "approve_memo", "pay_memo"):
        if kind is not None and view.wants(kind):
            return kind
    return "approve_memo"


def memo_rows(snap: Snapshot, now: datetime, view: View) -> list[Row]:
    """Служебки, заявления и отчёты на моём шаге маршрута (EDS): директору — согласовать,
    бухгалтеру на его шаге — принять к оплате."""
    out: list[Row] = []
    for route in snap.memos or []:
        obj = _dict(route.get("object"))
        number = obj.get("number")
        route_id = route.get("id")
        if not isinstance(number, str) or not number or not isinstance(route_id, str):
            continue
        created = parse_dt(route.get("created_at"))
        step = _dict(route.get("current_step"))
        kind = _memo_kind(step, view)
        role_id = _role_id(view, kind)
        subject = short(route.get("title"), 90)
        item = QueueItem(
            id=f"memo:{route_id}",
            role_id=role_id,
            kind=kind,
            title=f"{_MEMO_TITLES[kind]} {number}" + (f" · {subject}" if subject else ""),
            subtitle=join(
                _text(step.get("label")),
                ago(created, now),
            ),
            due_label="memo",
            object=memo_ref(number, subject or None),
        )
        out.append(Row(item, created))
    return out


_SUBJECT = {
    "access": "доступ",
    "notification": "уведомления",
    "template": "шаблон документа",
    "error": "ошибка",
    "other": "другое",
}


def ticket_rows(snap: Snapshot, now: datetime, view: View) -> list[Row]:
    """Новые обращения сотрудников: администратору — строки «Моих задач» (W15-H7). Сроков нет."""
    role_id = _role_id(view, "ticket")
    out: list[Row] = []
    for ticket in snap.tickets:
        number = ticket.get("number")
        if not isinstance(number, str) or not number:
            continue
        created = parse_dt(ticket.get("created_at"))
        item = QueueItem(
            id=f"ticket:{ticket.get('id', number)}",
            role_id=role_id,
            kind="ticket",
            title=f"Ответить на обращение {number}",
            subtitle=join(
                str(ticket.get("author_name") or "") or None,
                _SUBJECT.get(str(ticket.get("subject"))),
                short(ticket.get("preview"), 80),
                ago(created, now),
            ),
            due_label="later",
            due_at=None,
            object=ticket_ref(number),
        )
        out.append(Row(item, created))
    return out


def build_queue(feed: Feed, view: View, snap: Snapshot) -> list[QueueItem]:
    now = now_utc()
    rows_: list[Row] = []
    if wants_inbox(view):
        own = lead_rows(snap, feed.authed.data.user_id, now, view)
        rows_ += own
        taken = {int(r.item.id.split(":")[1]) for r in own if r.item.id.startswith("lead:")}
        for covered in snap.covered:
            rows_ += covered_rows(covered, now, view, taken)
    if wants_approvals(view):
        rows_ += quote_rows(snap, now, view)
    rows_ += rework_rows(snap, now, view)
    if wants_letters(view):
        rows_ += letter_rows(snap, now, view)
    if wants_memos(view):
        rows_ += memo_rows(snap, now, view)
    if wants_tickets(view):
        rows_ += ticket_rows(snap, now, view)
    rows_.sort(key=_sort_key)
    return [row.item for row in rows_]


def projects_in_work(snap: Snapshot) -> int:
    """Проекты (договор подписан), исполнение которых не закрыто целиком."""
    return sum(
        1
        for deal in snap.deals
        if deal.get("stage_code") in _ACTIVE_STAGES and deal.get("execution_complete") is not True
    )


def build_cards(view: View, snap: Snapshot, queue: list[QueueItem]) -> list[QueueCard]:
    """Набор карточек задают виды работы ролей «вида» (SPEC-v3 §7.1); карточки без источника не
    показываются — ноль был бы ложью."""
    cards: dict[str, QueueCard] = {}
    if wants_inbox(view):
        answer = sum(1 for i in queue if i.kind == "answer_lead" and i.on_behalf_of is None)
        take = sum(1 for i in queue if i.kind == "take_lead")
        cards["leads_without_answer"] = QueueCard(
            key="leads_without_answer",
            label="Лиды без ответа",
            count=answer,
            hint="Клиенты · Ждут ответа",
            path="/crm/messages",
        )
        cards["leads_to_take"] = QueueCard(
            key="leads_to_take",
            label="Лиды без менеджера",
            count=take,
            hint="Клиенты · Ждут ответа",
            path="/crm/messages",
        )
    if wants_letters(view) and snap.letters is not None:
        cards["letters_without_resolution"] = QueueCard(
            key="letters_without_resolution",
            label="Входящие без резолюции",
            count=len(snap.letters),
            hint="Документы · Входящие письма" + (" · не меньше" if snap.letters_more else ""),
            path="/eds/inbox",
        )
    if wants_approvals(view):
        cards["quotes_to_approve"] = QueueCard(
            key="quotes_to_approve",
            label="КП на одобрение",
            count=snap.approvals_total,
            hint="Документы · КП на одобрение",
            path="/eds/drafts",
        )
    if wants_memos(view) and snap.memos is not None:
        cards["memos_to_approve"] = QueueCard(
            key="memos_to_approve",
            label="Служебные записки",
            count=len(snap.memos),
            hint="Документы · На согласовании" + (" · не меньше" if snap.memos_more else ""),
            path="/eds/approvals",
        )
    if wants_projects(view):
        cards["projects_in_work"] = QueueCard(
            key="projects_in_work",
            label="Проекты в работе",
            count=projects_in_work(snap),
            hint="Документы · Проекты: договоры и акты",
            path="/eds/projects",
        )
    return list(cards.values())[:MAX_CARDS]


def build_counters(view: View, snap: Snapshot, queue: list[QueueItem]) -> list[MenuCounter]:
    """Бейджи подменю: красный — требует действия, серый — счётчик. Пункты вне ролей «вида» не
    перечисляются."""
    items = [
        MenuCounter(module="dashboard", section="queue", count=len(queue), attention=bool(queue))
    ]
    if wants_inbox(view):
        waiting = sum(
            1 for i in queue if i.kind in ("answer_lead", "take_lead") and i.on_behalf_of is None
        )
        items.append(
            MenuCounter(module="crm", section="messages", count=waiting, attention=waiting > 0)
        )
    if wants_letters(view) and snap.letters is not None:
        total = len(snap.letters)
        items.append(MenuCounter(module="eds", section="inbox", count=total, attention=total > 0))
    if wants_approvals(view):
        total = snap.approvals_total
        items.append(MenuCounter(module="eds", section="drafts", count=total, attention=total > 0))
    if wants_memos(view) and snap.memos is not None:
        total = len(snap.memos)
        items.append(
            MenuCounter(module="eds", section="approvals", count=total, attention=total > 0)
        )
    if wants_tickets(view):
        items.append(
            MenuCounter(
                module="admin",
                section="tickets",
                count=snap.tickets_total,
                attention=snap.tickets_total > 0,
            )
        )
    if wants_projects(view):
        total = projects_in_work(snap)
        items.append(
            MenuCounter(module="dashboard", section="projects", count=total, attention=False)
        )
        items.append(MenuCounter(module="eds", section="projects", count=total, attention=False))
    return items
