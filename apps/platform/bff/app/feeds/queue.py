"""«Моя очередь», карточки-счётчики и бейджи меню.

Основание: docs/architecture/integration-map.md §1.1–§1.2, SPEC-v3 §7.1.

Виды работы — секция `queue` каталога (`platform-rbac.yaml`): вид попадает в очередь, если у ролей
«вида» есть его раздел с нужным уровнем (ADR-0012 п. 6, названия ролей не используются).
Источники сегодня: лиды — CRM `/inbox` (`answer_lead`, `take_lead`, `triage_lead` — первая линия,
D17G-1); одобрение КП — маршруты EDS на моём шаге (`approve_quote`, D26G-4: тот же запрос, что
экран «КП на одобрение»); письма без резолюции (`resolve_letter`) и служебки,
заявления, отчёты на моём шаге маршрута (`approve_memo`, `pay_memo`) — EDS по токену `aud=eds`
(D1-6): что вернул EDS, то и строки; работа ERP — расчёт, счета и платёжки, договор и акт (D2-8,
`feeds/erp_work.py`). Роли «вида» — активная,
если задана (Q-PLT-12-1), иначе все роли сотрудника. `QueueItem.role_id` — первая роль «вида»,
которая даёт этот вид работы.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.feeds.erp_work import calc_rows, invoice_rows, project_rows
from app.feeds.feed import Feed
from app.feeds.models import (
    DueLabel,
    MenuCounter,
    ObjectRef,
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
    letter_task_ref,
    mail_ref,
    memo_ref,
    outgoing_document_path,
    quote_number,
    quote_ref,
    supplier_order_ref,
    ticket_ref,
)
from app.feeds.rework import rework_item
from app.feeds.snapshot import (
    Covered,
    Snapshot,
    wants_approvals,
    wants_calc_tasks,
    wants_inbox,
    wants_invoices,
    wants_letter_tasks,
    wants_letters,
    wants_mail,
    wants_mail_mine,
    wants_memos,
    wants_projects,
    wants_supplier_overdue,
    wants_tickets,
)
from app.feeds.text import (
    COMPANY_TZ,
    ago,
    due_label,
    join,
    money,
    now_utc,
    parse_deadline,
    parse_dt,
    short,
)
from app.feeds.work_roles import wants_work, work_role_id
from app.rbac import View

_RANK: dict[DueLabel, int] = {"overdue": 0, "today": 1, "tomorrow": 2, "memo": 3, "later": 4}
MAX_CARDS = 4
_ACTIVE_STAGES = frozenset({"CONTRACT_SIGNED", "CLOSED_WON"})
# Причина передачи «Передать менеджеру» первой линией (CRM `handed_over`, D17G-1).
HANDED_OVER = "handed_over"
_LEAD_ACTION: dict[QueueItemKind, str] = {
    "take_lead": "Взять в работу лида",
    "answer_lead": "Ответить лиду",
    "triage_lead": "Разобрать лида",
}


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
    handed_by: str | None = None,
) -> Row:
    lead_id = int(lead["id"])
    number = lead_number(lead_id)
    name = str(lead.get("display_name") or number)
    waiting = parse_dt(lead.get("last_lead_msg_at")) or parse_dt(lead.get("created_at"))
    action = _LEAD_ACTION.get(kind, "Ответить лиду")
    title = f"{action} {number}"
    if handed_by is not None:
        # D17G-1: передача первой линии — строка с запиской делопроизводителя и его именем.
        title = f"Новый лид от делопроизводителя {number}"
        waiting = parse_dt((lead.get("escalation") or {}).get("created_at")) or waiting
    item = QueueItem(
        id=f"lead:{lead_id}:{kind}",
        role_id=role_id,
        kind=kind,
        title=title,
        subtitle=join(name, short(why or lead.get("need_summary")), handed_by, ago(waiting, now)),
        due_label=due_label(due_at, now, default="today"),
        due_at=due_at,
        object=lead_ref(lead_id, name, conversation=True),
    )
    return Row(item, waiting)


def _handed_over(lead: dict[str, Any]) -> bool:
    """Передача первой линии (D17G-1): адресована ответственному лида, другим не показывается."""
    escalation = lead.get("escalation") or {}
    reasons = escalation.get("reason_codes") or []
    return HANDED_OVER in reasons and lead.get("assigned_user_id") is not None


def _handed_by(lead: dict[str, Any]) -> str:
    escalation = lead.get("escalation") or {}
    name = escalation.get("handed_by_user_name")
    return f"передал(а) {name}" if isinstance(name, str) and name else "передал делопроизводитель"


# TODO(CRM-08): `/inbox` «мои» на стороне CRM; пока BFF отбирает чужие передачи и отложенные сам.
def lead_rows(snap: Snapshot, me: int, now: datetime, view: View) -> list[Row]:
    """Лиды, по которым ждут именно этого сотрудника: передачи бота, ответ клиенту, свободные
    лиды; первой линии (`triage_lead`, D17G-1) — разобрать и передать менеджеру, менеджеру —
    «Новый лид от делопроизводителя» с запиской."""
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
        handed = _handed_over(lead)
        if handed and lead.get("assigned_user_id") != me:
            continue  # передана другому менеджеру: строка только у него
        if not view.wants(kind):
            if handed or taker is not None or not view.wants("triage_lead"):
                continue
            kind = "triage_lead"
        row = _lead_row(
            lead,
            kind,
            role_id=_role_id(view, kind),
            why=escalation.get("reason_text"),
            due_at=parse_dt(escalation.get("sla_due_at")),
            now=now,
            handed_by=_handed_by(lead) if handed else None,
        )
        add(row, int(lead["id"]))
    if view.wants("answer_lead"):
        answer = _role_id(view, "answer_lead")
        for lead in snap.inbox["mine"]:
            if lead.get("unread") is True:
                row = _lead_row(lead, "answer_lead", role_id=answer, why=None, due_at=None, now=now)
                add(row, int(lead["id"]))
    free: QueueItemKind | None = (
        "take_lead"
        if view.wants("take_lead")
        else "triage_lead"
        if view.wants("triage_lead")
        else None
    )
    if free is not None:
        role = _role_id(view, free)
        for lead in snap.inbox["unassigned"]:
            row = _lead_row(lead, free, role_id=role, why=None, due_at=None, now=now)
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
    """КП на одобрении на моём шаге маршрута EDS (D26G-4): что вернул EDS по токену сотрудника, то и
    строки — как экран «КП на одобрение · На моём шаге». Клиент, сумма и срок действия — снимок КП
    из карточки маршрута; нет снимка — клиент по сделке ERP, без суммы."""
    deals = snap.deal_index
    role_id = _role_id(view, "approve_quote")
    out: list[Row] = []
    seen: set[str] = set()
    for route in snap.quotes or []:
        route_id = route.get("id")
        obj = _dict(route.get("object"))
        if not isinstance(route_id, str) or route_id in seen:
            continue
        seen.add(route_id)
        snapshot = snap.quote_snapshots.get(route_id, {})
        deal_id = obj.get("erp_deal_id")
        deal = deals.get(deal_id) if isinstance(deal_id, int) else None
        client = _text(snapshot.get("client_name")) or (deal_title(deal) if deal else None)
        valid_until = parse_deadline(snapshot.get("valid_until"))
        created = parse_dt(route.get("created_at"))
        quote = {"number": obj.get("quote_number"), "version": obj.get("quote_version")}
        number = quote_number(quote)
        item = QueueItem(
            id=f"quote:{route_id}",
            role_id=role_id,
            kind="approve_quote",
            title=f"Одобрить {number}",
            subtitle=join(
                client,
                money(snapshot.get("total"), snapshot.get("currency"))
                if snapshot.get("total") is not None
                else None,
                _text(obj.get("deal_number")),
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


def _task_letter(entry: dict[str, Any]) -> tuple[str, str, str | None, str | None] | None:
    """Письмо строки задач EDS: (id, номер, отправитель, тема) или `None` — строка битая."""
    letter = _dict(entry.get("letter"))
    number, letter_id = letter.get("number"), letter.get("id")
    if not isinstance(number, str) or not number or not isinstance(letter_id, str):
        return None
    return letter_id, number, _text(letter.get("sender_name")), short(letter.get("subject"), 80)


def _ddmm(value: Any) -> str | None:
    day = parse_deadline(value)
    return f"{day.astimezone(COMPANY_TZ):%d.%m}" if day else None


def letter_task_rows(snap: Snapshot, now: datetime, view: View) -> list[Row]:
    """Входящие делопроизводства (P8b, EDS `GET /letter-tasks`): мои поручения со сроком, переносы
    срока у автора резолюции, «Ознакомиться». Что вернул EDS, то и строки; одна строка на
    поручение, перенос и ознакомление (id объекта EDS) — без дублей."""
    tasks = snap.letter_tasks
    if tasks is None:
        return []
    out: list[Row] = []
    seen: set[str] = set()

    def add(row: Row) -> None:
        if row.item.id not in seen:
            seen.add(row.item.id)
            out.append(row)

    if view.wants("instruction"):
        role_id = _role_id(view, "instruction")
        for entry in tasks.get("instructions", []):
            letter = _task_letter(entry)
            if letter is None or not isinstance(entry.get("id"), str):
                continue
            letter_id, number, sender, subject = letter
            due_at = parse_deadline(entry.get("due"))
            action = (
                "Подготовить ответ на письмо"
                if entry.get("kind") == "reply"
                else "Исполнить поручение по письму"
            )
            label = "overdue" if entry.get("overdue") is True else due_label(due_at, now)
            add(
                Row(
                    QueueItem(
                        id=f"instruction:{entry['id']}",
                        role_id=role_id,
                        kind="instruction",
                        title=f"{action} {number}",
                        subtitle=join(
                            sender,
                            subject,
                            "запрошен перенос" if entry.get("extension_pending") is True else None,
                        ),
                        due_label=label,
                        due_at=due_at,
                        object=letter_task_ref(letter_id, number, subject or None),
                    ),
                    parse_dt(entry.get("created_at")),
                )
            )
    if view.wants("instruction_extension"):
        role_id = _role_id(view, "instruction_extension")
        for entry in tasks.get("extensions", []):
            letter = _task_letter(entry)
            if letter is None or not isinstance(entry.get("id"), str):
                continue
            letter_id, number, _sender, subject = letter
            executor = _dict(entry.get("executor"))
            new_due = _ddmm(entry.get("new_due"))
            add(
                Row(
                    QueueItem(
                        id=f"instruction_extension:{entry['id']}",
                        role_id=role_id,
                        kind="instruction_extension",
                        title=f"Решить перенос срока по {number}",
                        subtitle=join(
                            _text(executor.get("full_name")),
                            f"новый срок {new_due}" if new_due else None,
                            short(entry.get("reason"), 80),
                        ),
                        due_label="today",
                        object=letter_task_ref(letter_id, number, subject or None),
                    ),
                    parse_dt(entry.get("requested_at")),
                )
            )
    if view.wants("acquaint"):
        role_id = _role_id(view, "acquaint")
        for entry in tasks.get("acquaintances", []):
            letter = _task_letter(entry)
            if letter is None:
                continue
            letter_id, number, sender, subject = letter
            add(
                Row(
                    QueueItem(
                        id=f"acquaint:{letter_id}",
                        role_id=role_id,
                        kind="acquaint",
                        title=f"Ознакомиться с письмом {number}",
                        subtitle=join(sender, subject),
                        due_label="later",
                        object=letter_task_ref(letter_id, number, subject or None),
                    ),
                    parse_dt(entry.get("created_at")),
                )
            )
    if view.wants("register_reply"):
        role_id = _role_id(view, "register_reply")
        for entry in tasks.get("registrations", []):
            row = _registration_row(entry, role_id)
            if row is not None:
                add(row)
    return out


def _registration_row(entry: dict[str, Any], role_id: str) -> Row | None:
    """«Зарегистрировать ИСХ» (EDS-REPLY-1): исполнитель передал черновик ответа на регистрацию;
    строка уходит сама, когда ИСХ зарегистрирован. Ведёт в карточку черновика."""
    document_id = entry.get("document_id")
    if not isinstance(document_id, str) or not document_id:
        return None
    reply_to = _dict(entry.get("in_reply_to"))
    letter_number = _text(reply_to.get("number"))
    subject = short(entry.get("subject"), 80)
    by = _text(_dict(entry.get("requested_by")).get("full_name"))
    return Row(
        QueueItem(
            id=f"register_reply:{document_id}",
            role_id=role_id,
            kind="register_reply",
            title=f"Зарегистрировать ИСХ: ответ на {letter_number}"
            if letter_number
            else "Зарегистрировать ИСХ",
            subtitle=join(subject, by),
            due_label="today",
            object=ObjectRef(
                kind="memo",
                number=letter_number or subject or "ИСХ",
                title=subject or None,
                path=outgoing_document_path(document_id),
            ),
        ),
        parse_dt(entry.get("requested_at")),
    )


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


def mail_rows(snap: Snapshot, now: datetime, view: View) -> list[Row]:
    """Письма общего ящика в «Моих задачах» (W18A-P2, W18A-P2-3): «Новое» — разобрать (ВХ, лид или
    архив; только первой линии), «в работе» у меня — довести. Срока нет — разбор в день поступления;
    суть — подсказка помощника, если есть, иначе начало текста. Что приходит строкой, решает CRM."""
    triage = wants_mail(view)
    out: list[Row] = []
    for mail in snap.mail or []:
        mail_id = mail.get("id")
        status = mail.get("status")
        if not isinstance(mail_id, int):
            continue
        mine = status in ("in_work", "registering")
        if not (mine or (status == "new" and triage)):
            continue
        kind: QueueItemKind = "inbound_mail_mine" if mine else "inbound_mail"
        received = parse_dt(mail.get("activity_at") or mail.get("received_at"))
        raw_assist = mail.get("assist")
        assist: dict[str, Any] = raw_assist if isinstance(raw_assist, dict) else {}
        subject = str(mail.get("subject") or "") or "(без темы)"
        sender = str(mail.get("from_name") or "") or str(mail.get("from_email") or "") or None
        verb = "Разобрать письмо"
        if mine:
            verb = "Письмо вам лично" if mail.get("personal") else "Письмо в работе"
        item = QueueItem(
            id=f"mail:{mail_id}",
            role_id=_role_id(view, kind),
            kind=kind,
            title=f"{verb}: {short(subject, 80)}",
            subtitle=join(
                sender,
                "ответ в цепочке" if mail.get("thread_reply") else None,
                short(assist.get("summary") or mail.get("preview"), 80),
                ago(received, now),
            ),
            due_label="later",
            due_at=None,
            object=mail_ref(
                mail_id, str(mail.get("from_email") or "почта"), subject, own=not triage
            ),
        )
        out.append(Row(item, received))
    return out


def supplier_rows(snap: Snapshot, now: datetime, view: View) -> list[Row]:
    """Просроченные заказы поставщикам (D2-2, SPEC-v3 §9): ожидаемая дата прошла, товар не
    получен. Строка ведёт на карточку ЗП. Что просрочено, решает ERP (`/stock/overdue/`), BFF
    только показывает."""
    role_id = _role_id(view, "supplier_overdue")
    out: list[Row] = []
    for order in snap.overdue_orders:
        number = order.get("number")
        if not isinstance(number, str) or not number:
            continue
        expected = parse_deadline(order.get("expected_date"))
        days = order.get("days_overdue")
        supplier = str(order.get("supplier_name") or "") or None
        item = QueueItem(
            id=f"supplier_order:{order.get('id', number)}",
            role_id=role_id,
            kind="supplier_overdue",
            title=f"Просрочен заказ {number}",
            subtitle=join(
                supplier,
                f"ждали к {expected.astimezone(COMPANY_TZ):%d.%m}" if expected else None,
                f"{days} дн. просрочки" if isinstance(days, int) else None,
            ),
            due_label="overdue",
            due_at=expected,
            object=supplier_order_ref(number, supplier),
        )
        out.append(Row(item, expected))
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
    if wants_letter_tasks(view):
        rows_ += letter_task_rows(snap, now, view)
    if wants_memos(view):
        rows_ += memo_rows(snap, now, view)
    if wants_tickets(view):
        rows_ += ticket_rows(snap, now, view)
    if wants_mail(view) or wants_mail_mine(view):
        rows_ += mail_rows(snap, now, view)
    if wants_supplier_overdue(view):
        rows_ += supplier_rows(snap, now, view)

    # D2-8: работа ERP — расчёт, счета и платёжки, договор и акт проекта
    def role_of(kind: QueueItemKind) -> str:
        return work_role_id(view, kind)

    for item, since in (
        calc_rows(snap, now, view, role_of)
        + invoice_rows(snap, now, view, role_of)
        + project_rows(snap, now, view, role_of)
    ):
        rows_.append(Row(item, since))
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
    if view.wants("triage_lead") and not (view.wants("answer_lead") or view.wants("take_lead")):
        triage = sum(1 for i in queue if i.kind == "triage_lead")
        cards["leads_to_triage"] = QueueCard(
            key="leads_to_triage",
            label="Лиды разобрать",
            count=triage,
            hint="Контакты · Лиды",
            path="/crm/messages",
        )
    elif wants_inbox(view):
        answer = sum(1 for i in queue if i.kind == "answer_lead" and i.on_behalf_of is None)
        take = sum(1 for i in queue if i.kind == "take_lead")
        cards["leads_without_answer"] = QueueCard(
            key="leads_without_answer",
            label="Лиды без ответа",
            count=answer,
            hint="Контакты · Лиды",
            path="/crm/messages",
        )
        cards["leads_to_take"] = QueueCard(
            key="leads_to_take",
            label="Лиды без менеджера",
            count=take,
            hint="Контакты · Лиды",
            path="/crm/messages",
        )
    if wants_letters(view) and snap.letters is not None:
        cards["letters_without_resolution"] = QueueCard(
            key="letters_without_resolution",
            label="Входящие без резолюции",
            count=len(snap.letters),
            hint="Документы · Входящие" + (" · не меньше" if snap.letters_more else ""),
            path="/eds/inbox",
        )
    if wants_mail(view) and snap.mail is not None:
        cards["inbound_mail"] = QueueCard(
            key="inbound_mail",
            label="Входящая почта",
            count=snap.mail_total,
            hint=(
                "Контакты · Почта"
                if snap.mail_configured
                else "Почта не подключена — Настройки · Подключения · Почта"
            ),
            path="/eds/mail",
        )
    if wants_approvals(view) and snap.quotes is not None:
        # D26G-4: число — те же строки «Одобрить КП», что в очереди (одна логика, без расхождений)
        cards["quotes_to_approve"] = QueueCard(
            key="quotes_to_approve",
            label="КП на одобрение",
            count=sum(1 for i in queue if i.kind == "approve_quote"),
            hint="Документы · Исходящие" + (" · не меньше" if snap.quotes_more else ""),
            path="/eds/drafts",
        )
    if wants_memos(view) and snap.memos is not None:
        cards["memos_to_approve"] = QueueCard(
            key="memos_to_approve",
            label="Служебные записки",
            count=len(snap.memos),
            hint="Документы · Внутренние" + (" · не меньше" if snap.memos_more else ""),
            path="/eds/approvals",
        )
    counts = snap.invoice_counts
    if counts is not None and wants_work(view, "confirm_payment"):
        cards["payments_to_confirm"] = QueueCard(
            key="payments_to_confirm",
            label="Платёжки на подтверждение",
            count=counts["proofs"],
            hint="Операции · Финансы",
            path="/eds/payments?show=proofs",
        )
    if counts is not None and wants_work(view, "issue_invoice"):
        cards["invoices_to_issue"] = QueueCard(
            key="invoices_to_issue",
            label="Счета к выставлению",
            count=counts["to_issue"],
            hint="Операции · Финансы",
            path="/eds/payments?show=to_issue",
        )
    if wants_projects(view):
        cards["projects_in_work"] = QueueCard(
            key="projects_in_work",
            label="Проекты в работе",
            count=projects_in_work(snap),
            hint="Главная · Проекты",
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
            1
            for i in queue
            if i.kind in ("answer_lead", "take_lead", "triage_lead") and i.on_behalf_of is None
        )
        items.append(
            MenuCounter(module="crm", section="messages", count=waiting, attention=waiting > 0)
        )
    if wants_letters(view) and snap.letters is not None:
        total = len(snap.letters)
        items.append(MenuCounter(module="eds", section="inbox", count=total, attention=total > 0))
    if wants_approvals(view) and snap.quotes is not None:
        total = sum(1 for i in queue if i.kind == "approve_quote")
        items.append(MenuCounter(module="eds", section="drafts", count=total, attention=total > 0))
    if wants_memos(view) and snap.memos is not None:
        total = len(snap.memos)
        items.append(
            MenuCounter(module="eds", section="approvals", count=total, attention=total > 0)
        )
    if wants_mail(view) and snap.mail is not None:
        items.append(
            MenuCounter(
                module="eds", section="mail", count=snap.mail_total, attention=snap.mail_total > 0
            )
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
    if wants_supplier_overdue(view):
        late = sum(1 for i in queue if i.kind == "supplier_overdue")
        items.append(MenuCounter(module="erp", section="stock", count=late, attention=late > 0))
    if wants_calc_tasks(view) and snap.calc_tasks is not None:
        calc = sum(1 for i in queue if i.kind == "calc_task")
        items.append(MenuCounter(module="erp", section="calc", count=calc, attention=calc > 0))
    if wants_invoices(view) and snap.invoice_counts is not None:
        counts = snap.invoice_counts
        waiting = (counts["proofs"] if wants_work(view, "confirm_payment") else 0) + (
            counts["to_issue"] if wants_work(view, "issue_invoice") else 0
        )
        items.append(
            MenuCounter(module="eds", section="payments", count=waiting, attention=waiting > 0)
        )
    if wants_projects(view):
        total = projects_in_work(snap)
        items.append(
            MenuCounter(module="dashboard", section="projects", count=total, attention=False)
        )
        items.append(MenuCounter(module="eds", section="projects", count=total, attention=False))
    return items
