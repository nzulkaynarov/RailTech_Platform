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
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from app.feeds.erp_work import calc_rows, invoice_rows, project_rows
from app.feeds.feed import Feed
from app.feeds.lang import tr
from app.feeds.models import (
    DueLabel,
    MenuCounter,
    ObjectKind,
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
    partner_application_ref,
    quote_number,
    quote_ref,
    supplier_order_ref,
    ticket_ref,
)
from app.feeds.queue_meta import finish
from app.feeds.rework import LIMIT as REWORK_LIMIT
from app.feeds.rework import rework_item
from app.feeds.snapshot import (
    APPROVALS_PAGE_SIZE,
    SUPPLY_TASK_KINDS,
    Covered,
    Snapshot,
    wants_approvals,
    wants_calc_tasks,
    wants_inbox,
    wants_invoices,
    wants_letters,
    wants_mail,
    wants_mail_mine,
    wants_memos,
    wants_projects,
    wants_signing,
    wants_supplier_overdue,
    wants_supply_tasks,
    wants_tickets,
)
from app.feeds.text import (
    COMPANY_TZ,
    ago,
    ago_value,
    due_label,
    join,
    money,
    now_utc,
    parse_deadline,
    parse_dt,
    segment,
    short,
)
from app.feeds.work_roles import wants_work, work_role_id
from app.rbac import View

LETTER_TASKS_LIMIT = 100  # предел EDS `GET /letter-tasks` на каждый вид задач
_RANK: dict[DueLabel, int] = {"overdue": 0, "today": 1, "tomorrow": 2, "memo": 3, "later": 4}
MAX_CARDS = 4
_ACTIVE_STAGES = frozenset({"CONTRACT_SIGNED", "CLOSED_WON"})
# Причина передачи «Передать менеджеру» первой линией (CRM `handed_over`, D17G-1).
HANDED_OVER = "handed_over"
_LEAD_ACTION: dict[QueueItemKind, tuple[str, str, str]] = {
    "take_lead": ("Взять в работу лида", "Lidni işga oliş", "Take on lead"),
    "answer_lead": ("Ответить лиду", "Lidga javob beriş", "Reply to lead"),
    "triage_lead": ("Разобрать лида", "Lidni saralaş", "Sort lead"),
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


def _acting(entry: dict[str, Any]) -> QueueOwner | None:
    """Чью работу решает заместитель (`acting_for` из EDS, СЦ-9): «за {имя}»; свой шаг — `None`."""
    person = entry.get("acting_for")
    if not isinstance(person, dict):
        return None
    user_id, name = person.get("crm_user_id"), person.get("full_name")
    if isinstance(user_id, int) and isinstance(name, str) and name:
        return QueueOwner(id=str(user_id), name=name)
    return None


def _mine_or_acting(view: View, kind: QueueItemKind, owner: QueueOwner | None) -> bool:
    """Свой вид работы — по роли; строка замещаемого приходит от EDS, и роль заместителя её не
    фильтрует (решает EDS по токену: право или замещение)."""
    return owner is not None or view.wants(kind)


def _role_id_for(view: View, kind: QueueItemKind, owner: QueueOwner | None) -> str:
    role = _role_id(view, kind)
    if role or owner is None or not view.roles:
        return role
    return str(view.roles[0].id)


_TASK_SCREEN_KINDS = frozenset({"instruction", "instruction_extension"})


def _acting_item(item: QueueItem, owner: QueueOwner | None) -> QueueItem:
    """Строка замещаемого: id с суффиксом (чужая и своя строки не сливаются), «за»."""
    if owner is None:
        return item
    update: dict[str, Any] = {
        "id": f"{item.id}:for:{owner.id}",
        "on_behalf_of": owner,
        # «за Нодиру Алиеву»: чья это работа — первое, что человек должен увидеть в причине
        "reason": join(
            tr(
                f"вы замещаете {owner.name}",
                f"siz {owner.name} örnini bosasiz",
                f"you cover for {owner.name}",
            ),
            item.reason,
        ),
    }
    if item.kind in _TASK_SCREEN_KINDS:
        # Рабочий экран поручения не знает замещения (в карточке письма его признака нет): за кого
        # открыт шаг, он берёт из адреса; право действовать проверяет EDS
        path = f"{item.object.path}?for={quote(owner.id)}&forName={quote(owner.name)}"
        update["object"] = item.object.model_copy(update={"path": path})
    return item.model_copy(update=update)


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
    action = tr(*_LEAD_ACTION.get(kind, _LEAD_ACTION["answer_lead"]))
    title = f"{action} {number}"
    if handed_by is not None:
        # D17G-1: передача первой линии — строка с запиской делопроизводителя и его именем.
        title = tr(
            f"Новый лид от делопроизводителя {number}",
            f"Yangi lid, kotibdan {number}",
            f"New lead from the clerk {number}",
        )
        waiting = parse_dt((lead.get("escalation") or {}).get("created_at")) or waiting
    if handed_by is not None:
        reason = tr(f"вам {handed_by}", f"sizga {handed_by}", f"to you: {handed_by}")
    elif kind == "answer_lead":
        reason = tr("ваш клиент", "sizning mijozingiz", "your client") + (
            f" · {short(why, 60)}"
            if why
            else tr(" ждёт ответа", " javob kutmoqda", " is waiting for a reply")
        )
    elif kind == "triage_lead":
        reason = tr(
            "вы первая линия: разобрать и передать менеджеру",
            "siz birinçi liniyasiz: saralab menejerga uzating",
            "you are the first line: sort and pass to a manager",
        )
    else:
        reason = tr("лид без менеджера", "menejersiz lid", "lead without a manager") + (
            f" · {short(why, 60)}" if why else ""
        )
    item = QueueItem(
        id=f"lead:{lead_id}:{kind}",
        role_id=role_id,
        kind=kind,
        reason=reason,
        title=title,
        subtitle=join(name, short(why or lead.get("need_summary")), handed_by, ago(waiting, now)),
        due_label=due_label(due_at, now),
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
    if isinstance(name, str) and name:
        return tr(f"передано: {name}", f"{name} uzatdi", f"handed over by {name}")
    return tr("передал делопроизводитель", "kotib uzatdi", "handed over by the clerk")


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
            update={
                "id": f"{row.item.id}:for:{covered.user_id}",
                "on_behalf_of": owner,
                # The lead is the colleague's, not the reader's: never "ваш клиент"
                "reason": tr(
                    f"вы замещаете {covered.name} · клиент ждёт ответа",
                    f"siz {covered.name} örnini bosasiz · mijoz javob kutmoqda",
                    f"you cover for {covered.name} · the client is waiting for a reply",
                ),
            }
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
    out: list[Row] = []
    seen: set[str] = set()
    for route in snap.quotes or []:
        route_id = route.get("id")
        obj = _dict(route.get("object"))
        owner = _acting(route)
        if (
            not isinstance(route_id, str)
            or route_id in seen
            or not _mine_or_acting(view, "approve_quote", owner)
        ):
            continue
        seen.add(route_id)
        role_id = _role_id_for(view, "approve_quote", owner)
        snapshot = snap.quote_snapshots.get(route_id, {})
        deal_id = obj.get("erp_deal_id")
        deal = deals.get(deal_id) if isinstance(deal_id, int) else None
        client = _text(snapshot.get("client_name")) or (deal_title(deal) if deal else None)
        valid_until = parse_deadline(snapshot.get("valid_until"))
        created = parse_dt(route.get("created_at"))
        quote = {"number": obj.get("quote_number"), "version": obj.get("quote_version")}
        number = quote_number(quote)
        step_label = _text(_dict(route.get("current_step")).get("label"))
        item = QueueItem(
            id=f"quote:{route_id}",
            role_id=role_id,
            kind="approve_quote",
            reason=join(
                tr(
                    f"ваш шаг маршрута: {step_label}",
                    f"marşrutdagi sizning qadamingiz: {step_label}",
                    f"your route step: {step_label}",
                )
                if step_label
                else tr(
                    "ваш шаг одобрения КП",
                    "TTni maqullaş böyiça sizning qadamingiz",
                    "your quote approval step",
                ),
                tr(
                    f"расчёт: {_text(obj.get('calc_author'))}",
                    f"hisob-kitob: {_text(obj.get('calc_author'))}",
                    f"costing: {_text(obj.get('calc_author'))}",
                )
                if _text(obj.get("calc_author"))
                else None,
            ),
            title=tr(f"Одобрить {number}", f"{number} ni maqullaş", f"Approve {number}"),
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
        out.append(Row(_acting_item(item, owner), created))
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
            reason=tr(
                "входящее без резолюции",
                "rezolyusiyasiz kiruvçi xat",
                "incoming letter without a resolution",
            )
            + (tr(" · срочное", " · şoşilinç", " · urgent") if letter.get("urgent") else ""),
            title=tr(
                f"Наложить резолюцию на письмо {number}",
                f"{number} xatga rezolyusiya qöyiş",
                f"Add a resolution to letter {number}",
            ),
            subtitle=join(
                _text(sender.get("name")),
                subject,
                _text(links.get("deal_number")),
                ago_value(letter.get("received_at"), now),
            ),
            due_label=due_label(due_at, now),
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


def _waiting(since: datetime, now: datetime) -> str:
    """Сколько дело ждёт: «40 мин», «2 ч», «3 д» (возраст передачи — факт, не выдуманный срок)."""
    seconds = max(0, int((now - since).total_seconds()))
    if seconds < 3600:
        n = max(1, seconds // 60)
        return tr(f"{n} мин", f"{n} daq.", f"{n} min")
    if seconds < 86400:
        n = seconds // 3600
        return tr(f"{n} ч", f"{n} soat", f"{n} h")
    n = seconds // 86400
    return tr(f"{n} д", f"{n} kun", f"{n} d")


def _instruction_reason(entry: dict[str, Any]) -> str:
    """Почему поручение у этого человека: роль в поручении и дата резолюции."""
    issued = _ddmm(entry.get("created_at"))
    if entry.get("role") == "co_executor":
        role = tr("вы соисполнитель", "siz hamijrosiz", "you are a co-executor")
    else:
        role = tr("вы ответственный", "siz masʼulsiz", "you are responsible")
    return join(
        tr(f"резолюция от {issued}", f"{issued} dagi rezolyusiya", f"resolution of {issued}")
        if issued
        else tr("поручено резолюцией", "rezolyusiya bilan topşirilgan", "assigned by a resolution"),
        role,
    )


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

    for entry in tasks.get("instructions", []):
        owner = _acting(entry)
        letter = _task_letter(entry)
        if (
            not _mine_or_acting(view, "instruction", owner)
            or letter is None
            or not isinstance(entry.get("id"), str)
        ):
            continue
        letter_id, number, sender, subject = letter
        due_at = parse_deadline(entry.get("due"))
        action = (
            tr("Подготовить ответ на письмо", "Xatga javob tayyorlaş", "Prepare a reply to letter")
            if entry.get("kind") == "reply"
            else tr(
                "Исполнить поручение по письму",
                "Xat böyiça topşiriqni bajariş",
                "Carry out the instruction on letter",
            )
        )
        label = "overdue" if entry.get("overdue") is True else due_label(due_at, now)
        item = QueueItem(
            id=f"instruction:{entry['id']}",
            role_id=_role_id_for(view, "instruction", owner),
            kind="instruction",
            reason=_instruction_reason(entry),
            action_label=tr("Подготовить ответ", "Javob tayyorlaş", "Prepare a reply")
            if entry.get("kind") == "reply"
            else None,
            title=f"{action} {number}",
            subtitle=join(
                sender,
                subject,
                tr("запрошен перенос", "muddatni köçiriş söralgan", "an extension was requested")
                if entry.get("extension_pending") is True
                else None,
            ),
            due_label=label,
            due_at=due_at,
            object=letter_task_ref(letter_id, number, subject or None),
        )
        add(Row(_acting_item(item, owner), parse_dt(entry.get("created_at"))))
    for entry in tasks.get("extensions", []):
        owner = _acting(entry)
        letter = _task_letter(entry)
        if (
            not _mine_or_acting(view, "instruction_extension", owner)
            or letter is None
            or not isinstance(entry.get("id"), str)
        ):
            continue
        letter_id, number, _sender, subject = letter
        executor = _dict(entry.get("executor"))
        new_due = _ddmm(entry.get("new_due"))
        old_due = parse_deadline(entry.get("old_due"))
        item = QueueItem(
            id=f"instruction_extension:{entry['id']}",
            role_id=_role_id_for(view, "instruction_extension", owner),
            kind="instruction_extension",
            reason=join(
                tr(
                    f"{_text(executor.get('full_name')) or 'исполнитель'} просит перенос",
                    f"{_text(executor.get('full_name')) or 'ijroçi'} muddatni köçiriş söramoqda",
                    f"{_text(executor.get('full_name')) or 'the executor'} asks for an extension",
                ),
                tr("вы автор резолюции", "siz rezolyusiya muallifisiz", "you wrote the resolution"),
            ),
            title=tr(
                f"Решить перенос срока по {number}",
                f"{number} böyiça muddatni köçirişni hal qiliş",
                f"Decide on the deadline extension for {number}",
            ),
            subtitle=join(
                _text(executor.get("full_name")),
                tr(f"новый срок {new_due}", f"yangi muddat {new_due}", f"new deadline {new_due}")
                if new_due
                else None,
                short(entry.get("reason"), 80),
            ),
            # Срок — действующий срок поручения: решить надо, пока он не прошёл
            due_label=due_label(old_due, now),
            due_at=old_due,
            object=letter_task_ref(letter_id, number, subject or None),
        )
        add(Row(_acting_item(item, owner), parse_dt(entry.get("requested_at"))))
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
                        reason=tr(
                            "вас просят ознакомиться с письмом · без срока",
                            "sizdan xat bilan tanişiş söralmoqda · muddatsiz",
                            "you are asked to read the letter · no deadline",
                        ),
                        title=tr(
                            f"Ознакомиться с письмом {number}",
                            f"{number} xat bilan tanişiş",
                            f"Read letter {number}",
                        ),
                        subtitle=join(sender, subject),
                        due_label="later",
                        object=letter_task_ref(letter_id, number, subject or None),
                    ),
                    parse_dt(entry.get("created_at")),
                )
            )
    if view.wants("sign_document"):
        for entry in tasks.get("signatures", []):
            row = _signature_row(entry, view, now)
            if row is not None:
                add(row)
    return out


def _signature_row(entry: dict[str, Any], view: View, now: datetime) -> Row | None:
    """«Подписать исходящее» (СЦ-9): автор передал письмо на подпись, подписант вычислен в EDS
    (реестр полномочий; при замещении строка у заместителя, «за {имя}»). Исходящее не
    регистрируется без подписи — номер выдаёт подпись. Ведёт в карточку письма, где «Подписать»."""
    document_id = entry.get("document_id")
    if not isinstance(document_id, str) or not document_id:
        return None
    owner = _acting(entry)
    reply_to = _dict(entry.get("in_reply_to"))
    letter_number = _text(reply_to.get("number"))
    subject = short(entry.get("subject"), 80)
    by = _text(_dict(entry.get("requested_by")).get("full_name"))
    handed = parse_dt(entry.get("requested_at"))
    item = QueueItem(
        id=f"sign_document:{document_id}",
        reason=join(
            tr(
                "вы подписант по реестру полномочий",
                "siz vakolatlar reyestri böyiça imzolovçisiz",
                "you are a signatory per the authority register",
            ),
            tr(f"передано: {by}", f"{by} uzatdi", f"handed over by {by}") if by else None,
            tr(
                f"ждёт {_waiting(handed, now)}",
                f"{_waiting(handed, now)} kutmoqda",
                f"waiting {_waiting(handed, now)}",
            )
            if handed
            else None,
        ),
        role_id=_role_id_for(view, "sign_document", owner),
        kind="sign_document",
        title=tr(
            f"Подписать исходящее: ответ на {letter_number}",
            f"Çiquvçi xatni imzolaş: {letter_number} xatga javob",
            f"Sign the outgoing letter: reply to {letter_number}",
        )
        if letter_number
        else tr(
            f"Подписать исходящее: {subject}",
            f"Çiquvçi xatni imzolaş: {subject}",
            f"Sign the outgoing letter: {subject}",
        )
        if subject
        else tr("Подписать исходящее", "Çiquvçi xatni imzolaş", "Sign the outgoing letter"),
        subtitle=join(None if letter_number is None else subject, by),
        # Срока у подписи письма нет: «сегодня» не выдумываем, возраст передачи — в «почему у вас»
        due_label="later",
        object=ObjectRef(
            kind="memo",
            number=letter_number or subject or tr("Исходящее", "Çiquvçi xat", "Outgoing"),
            title=subject or None,
            path=outgoing_document_path(document_id),
        ),
    )
    return Row(_acting_item(item, owner), parse_dt(entry.get("requested_at")))


# Права EDS шагов визы маршрута подписи (ADR-0025, как в `eds_approvals`): не подпись.
VISA_PERMISSIONS = frozenset({"approvals.visa_finance", "approvals.visa_legal"})
_SIGNING_NOUN = {
    "quote": ("КП", "TT", "quote"),
    "contract": ("договор", "şartnoma", "contract"),
    "invoice": ("счёт", "hisob", "invoice"),
    "act": ("акт", "akt", "act"),
}
_SIGNING_OBJECT: dict[str, ObjectKind] = {
    "quote": "quote",
    "contract": "contract",
    "invoice": "invoice",
    "act": "act",
}


_VISA_REASON = {
    "approvals.visa_finance": (
        "ваша виза: финансы, до подписи",
        "sizning vizangiz: moliya, imzogaça",
        "your visa: finance, before signing",
    ),
    "approvals.visa_legal": (
        "ваша виза: право, до подписи",
        "sizning vizangiz: huquq, imzogaça",
        "your visa: legal, before signing",
    ),
}


def signing_rows(snap: Snapshot, now: datetime, view: View) -> list[Row]:
    """«Подписать договор CT-…», счёт, акт, КП (СЦ-9): открытые шаги подписи на мне, из списка
    (`GET /approvals?mine&template=signing`), что раньше был отдельным блоком. Виза бухгалтера или
    юриста — тоже строка (категория «согласовать», своя причина). Кому подписывать, решает EDS
    (реестр полномочий)."""
    if not wants_signing(view):
        return []
    out: list[Row] = []
    seen: set[str] = set()
    for route in snap.signing or []:
        route_id = route.get("id")
        obj = _dict(route.get("object"))
        number = _text(obj.get("signing_number"))
        kind = _text(obj.get("signing_kind"))
        step = _dict(route.get("current_step"))
        permission = _text(_dict(step.get("assignee")).get("permission"))
        if (
            not isinstance(route_id, str)
            or route_id in seen
            or not number
            or kind not in _SIGNING_NOUN
        ):
            continue
        visa = permission in VISA_PERMISSIONS
        seen.add(route_id)
        owner = _acting(route)
        created = parse_dt(route.get("created_at"))
        tiyins = obj.get("signing_amount_tiyins")
        amount = (
            money(f"{Decimal(tiyins) / 100:.2f}", obj.get("signing_currency"))
            if isinstance(tiyins, int)
            else None
        )
        verb = tr("Завизировать", "Vizalaş", "Visa") if visa else tr("Подписать", "Imzolaş", "Sign")
        item = QueueItem(
            id=f"sign_document:{route_id}",
            role_id=_role_id_for(view, "sign_document", owner),
            kind="sign_document",
            # Виза — тот же вид строки: новое значение `kind` ломало бы клиентов контракта
            category="approve" if visa else "sign",
            action_label=verb,
            reason=join(
                tr(
                    *_VISA_REASON.get(
                        permission or "",
                        (
                            "ваша виза перед подписью",
                            "imzodan oldingi sizning vizangiz",
                            "your visa before signing",
                        ),
                    )
                )
                if visa
                else tr(
                    "вы подписант по реестру полномочий",
                    "siz vakolatlar reyestri böyiça imzolovçisiz",
                    "you are a signatory per the authority register",
                ),
                tr(
                    f"ждёт {_waiting(created, now)}",
                    f"{_waiting(created, now)} kutmoqda",
                    f"waiting {_waiting(created, now)}",
                )
                if created
                else None,
            ),
            title=f"{verb} {tr(*_SIGNING_NOUN[kind])} {number}",
            subtitle=join(short(route.get("title"), 80), amount, ago(created, now)),
            # Срока у подписи и визы нет: «сегодня» не выдумываем, возраст — в «почему у вас»
            due_label="later",
            object=ObjectRef(
                kind=_SIGNING_OBJECT[kind],
                number=number,
                title=short(route.get("title"), 80) or None,
                path=f"/dashboard/queue?signing={route_id}",
            ),
        )
        out.append(Row(_acting_item(item, owner), created))
    return out


_MEMO_TITLES = {
    "approve_memo": ("Согласовать", "Kelişiş", "Approve"),
    "pay_memo": ("Принять к оплате", "Tölovga qabul qiliş", "Accept for payment"),
}


_MEMO_KIND_BY_PERMISSION: dict[str, QueueItemKind] = {
    "memos.approve": "approve_memo",
    "approvals.decide": "approve_memo",
    "payments.confirm": "pay_memo",
}


def _memo_kind(step: dict[str, Any], view: View, *, acting: bool = False) -> QueueItemKind:
    """Вид строки — по праву, которое держит текущий шаг маршрута (EDS): директор, у которого есть и
    право бухгалтера, на шаге бухгалтера видит «Принять к оплате», а не «Согласовать». Шаг
    конкретного сотрудника (права нет) или вид, не положенный роли, — тот, что даёт раздел роли."""
    permission = _text(_dict(step.get("assignee")).get("permission"))
    preferred = _MEMO_KIND_BY_PERMISSION.get(permission or "")
    if acting:
        # шаг замещаемого: вид — по праву шага, а не по ролям заместителя
        return preferred or "approve_memo"
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
        owner = _acting(route)
        created = parse_dt(route.get("created_at"))
        step = _dict(route.get("current_step"))
        kind = _memo_kind(step, view, acting=owner is not None)
        if not _mine_or_acting(view, kind, owner):
            continue
        role_id = _role_id_for(view, kind, owner)
        subject = short(route.get("title"), 90)
        item = QueueItem(
            id=f"memo:{route_id}",
            role_id=role_id,
            kind=kind,
            reason=(
                tr(
                    f"ваш шаг маршрута: {_text(step.get('label'))}",
                    f"marşrutdagi sizning qadamingiz: {_text(step.get('label'))}",
                    f"your route step: {_text(step.get('label'))}",
                )
                if _text(step.get("label"))
                else tr(
                    "вы согласующий по маршруту",
                    "siz marşrut böyiça kelişuvçisiz",
                    "you are an approver on the route",
                )
            ),
            title=f"{tr(*_MEMO_TITLES[kind])} {number}" + (f" · {subject}" if subject else ""),
            subtitle=join(
                _text(step.get("label")),
                ago(created, now),
            ),
            due_label="memo",
            object=memo_ref(number, subject or None),
        )
        out.append(Row(_acting_item(item, owner), created))
    return out


_SUBJECT = {
    "access": ("доступ", "kiriş", "access"),
    "notification": ("уведомления", "bildirişnomalar", "notifications"),
    "template": ("шаблон документа", "hujjat şabloni", "document template"),
    "error": ("ошибка", "xato", "error"),
    "other": ("другое", "boşqa", "other"),
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
            title=tr(
                f"Ответить на обращение {number}",
                f"{number} murojaatga javob beriş",
                f"Reply to request {number}",
            ),
            subtitle=join(
                str(ticket.get("author_name") or "") or None,
                tr(*_SUBJECT[str(ticket.get("subject"))])
                if str(ticket.get("subject")) in _SUBJECT
                else None,
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
        subject = str(mail.get("subject") or "") or tr("(без темы)", "(mavzusiz)", "(no subject)")
        sender = str(mail.get("from_name") or "") or str(mail.get("from_email") or "") or None
        verb = tr("Разобрать письмо", "Xatni saralaş", "Sort the email")
        if mine:
            verb = (
                tr("Письмо вам лично", "Xat sizga şaxsan", "Email addressed to you")
                if mail.get("personal")
                else tr("Письмо в работе", "Xat işda", "Email in progress")
            )
        item = QueueItem(
            id=f"mail:{mail_id}",
            role_id=_role_id(view, kind),
            kind=kind,
            title=f"{verb}: {short(subject, 80)}",
            subtitle=join(
                sender,
                tr("ответ в цепочке", "zanjirdagi javob", "reply in a thread")
                if mail.get("thread_reply")
                else None,
                short(assist.get("summary") or mail.get("preview"), 80),
                ago(received, now),
            ),
            due_label="later",
            due_at=None,
            object=mail_ref(
                mail_id,
                str(mail.get("from_email") or tr("почта", "poçta", "mail")),
                subject,
                own=not triage,
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
            title=tr(
                f"Просрочен заказ {number}",
                f"{number} buyurtmaning muddati ötgan",
                f"Order {number} is overdue",
            ),
            subtitle=join(
                supplier,
                tr(
                    f"ждали к {expected.astimezone(COMPANY_TZ):%d.%m}",
                    f"{expected.astimezone(COMPANY_TZ):%d.%m} gaça kutilgan",
                    f"expected by {expected.astimezone(COMPANY_TZ):%d.%m}",
                )
                if expected
                else None,
                tr(f"{days} дн. просрочки", f"{days} kun keçikkan", f"{days} d overdue")
                if isinstance(days, int)
                else None,
            ),
            due_label="overdue",
            due_at=expected,
            object=supplier_order_ref(number, supplier),
        )
        out.append(Row(item, expected))
    return out


def _supply_task_item(task: dict[str, Any], kind: QueueItemKind, role_id: str) -> QueueItem | None:
    """Строка дела снабженца (план 0.7, FR-6): ERP решает, что ждёт снабженца, BFF только
    называет."""
    supplier = _text(task.get("supplier_name"))
    number = _text(task.get("number"))
    note = _text(task.get("note"))
    if kind == "partner_application":
        if supplier is None:
            return None
        agreed = task.get("status") == "candidate_agreed"
        return QueueItem(
            id=f"partner_application:{task.get('id')}",
            role_id=role_id,
            kind=kind,
            title=tr(
                f"Заявка на партнёрство: {supplier}",
                f"Hamkorlik arizasi: {supplier}",
                f"Partnership application: {supplier}",
            ),
            subtitle=tr(
                "Кандидат согласовал договор — одобрите",
                "Nomzod şartnomani kelişdi — maqullang",
                "The candidate agreed to the contract — approve it",
            )
            if agreed
            else tr("Отправьте договор", "Şartnomani yuboring", "Send the contract"),
            due_label="later",
            object=partner_application_ref(supplier),
        )
    if number is None:
        return None
    if kind in ("order_shortage", "ship_project"):
        # СЦ-9: номер — проект (ПР-…), заказа ещё нет; клиент и состав — в `client_name` и `note`.
        subtitle = join(_text(task.get("client_name")), note)
        if kind == "order_shortage":
            title, due, path = (
                tr(
                    f"Заказать недостающее по {number}",
                    f"{number} böyiça yetişmayotganni buyurtma beriş",
                    f"Order what is missing for {number}",
                ),
                "later",
                f"/erp/stock/new?mode=shortage&request={segment(number)}",
            )
        else:
            title, due, path = (
                tr(
                    f"Отгрузить товар по {number}",
                    f"{number} böyiça tovarni jönatiş",
                    f"Ship the goods for {number}",
                ),
                "later",
                f"/erp/stock?view=shipments&request={segment(number)}",
            )
        return QueueItem(
            id=f"{kind}:{task.get('id')}",
            role_id=role_id,
            kind=kind,
            title=title,
            subtitle=subtitle,
            due_label=due,
            object=ObjectRef(
                kind="project", number=number, title=_text(task.get("client_name")), path=path
            ),
        )
    if kind == "send_supplier_order":
        title, subtitle = (
            tr(
                f"Отправить заказ {number} партнёру",
                f"{number} buyurtmani hamkorga yuboriş",
                f"Send order {number} to the partner",
            ),
            supplier or "",
        )
    elif kind == "partner_date_change":
        wanted = parse_deadline(task.get("date"))
        title = tr(
            f"Партнёр просит перенести {number}",
            f"Hamkor {number} ni köçiriş söramoqda",
            f"The partner asks to move {number}",
        ) + (
            tr(
                f" на {wanted.astimezone(COMPANY_TZ):%d.%m}",
                f" {wanted.astimezone(COMPANY_TZ):%d.%m} ga",
                f" to {wanted.astimezone(COMPANY_TZ):%d.%m}",
            )
            if wanted
            else ""
        )
        subtitle = join(supplier, note)
    else:
        title, subtitle = (
            tr(
                f"Принять товар по {number}",
                f"{number} böyiça tovarni qabul qiliş",
                f"Receive the goods for {number}",
            ),
            join(
                supplier,
                tr(f"накладная {note}", f"yuk xati {note}", f"delivery note {note}")
                if note
                else None,
            ),
        )
    return QueueItem(
        id=f"{kind}:{task.get('id')}",
        role_id=role_id,
        kind=kind,
        title=title,
        subtitle=subtitle,
        due_label="later",
        object=supplier_order_ref(number, supplier),
    )


def supply_task_rows(snap: Snapshot, view: View) -> list[Row]:
    """Дела снабженца из ERP `/stock/tasks/`: черновик заказа, перенос даты, отгрузка, заявка на
    партнёрство."""
    out: list[Row] = []
    for task in snap.supply_tasks:
        kind = SUPPLY_TASK_KINDS.get(str(task.get("kind")))
        if kind is None or not wants_work(view, kind):
            continue
        item = _supply_task_item(task, kind, _role_id(view, kind))
        if item is not None:
            out.append(Row(item, parse_dt(task.get("since"))))
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
    rows_ += quote_rows(snap, now, view)
    rows_ += rework_rows(snap, now, view)
    if wants_letters(view):
        rows_ += letter_rows(snap, now, view)
    rows_ += letter_task_rows(snap, now, view)
    rows_ += signing_rows(snap, now, view)
    rows_ += memo_rows(snap, now, view)
    if wants_tickets(view):
        rows_ += ticket_rows(snap, now, view)
    if wants_mail(view) or wants_mail_mine(view):
        rows_ += mail_rows(snap, now, view)
    if wants_supplier_overdue(view):
        rows_ += supplier_rows(snap, now, view)
    if wants_supply_tasks(view):
        rows_ += supply_task_rows(snap, view)

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
    return [finish(row.item) for row in rows_]


def is_truncated(snap: Snapshot) -> bool:
    """Источник отдал не всё (следующая страница EDS, упор в предел задач, возвратов, обращений):
    очередь «показаны не все», а не полная."""
    capped = (
        snap.letters_more
        or snap.memos_more
        or snap.quotes_more
        or len(snap.rework or []) >= REWORK_LIMIT
        or len(snap.signing or []) >= APPROVALS_PAGE_SIZE
        or snap.tickets_total > len(snap.tickets)
        or any(len(rows) >= LETTER_TASKS_LIMIT for rows in (snap.letter_tasks or {}).values())
    )
    return bool(capped)


def _own_count(routes: list[dict[str, Any]]) -> int:
    """Счётчики — только своя работа (W15-H6): шаги замещаемого (`acting_for`) в число не входят."""
    return sum(1 for route in routes if _acting(route) is None)


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
            label=tr("Лиды разобрать", "Saralaş kerak bölgan lidlar", "Leads to sort"),
            count=triage,
            hint=tr("Контакты · Лиды", "Kontaktlar · Lidlar", "Contacts · Leads"),
            path="/crm/leads?scope=waiting",
        )
    elif wants_inbox(view):
        answer = sum(1 for i in queue if i.kind == "answer_lead" and i.on_behalf_of is None)
        take = sum(1 for i in queue if i.kind == "take_lead")
        cards["leads_without_answer"] = QueueCard(
            key="leads_without_answer",
            label=tr("Лиды без ответа", "Javobsiz lidlar", "Leads without a reply"),
            count=answer,
            hint=tr("Контакты · Лиды", "Kontaktlar · Lidlar", "Contacts · Leads"),
            path="/crm/leads?scope=waiting",
        )
        cards["leads_to_take"] = QueueCard(
            key="leads_to_take",
            label=tr("Лиды без менеджера", "Menejersiz lidlar", "Leads without a manager"),
            count=take,
            hint=tr("Контакты · Лиды", "Kontaktlar · Lidlar", "Contacts · Leads"),
            path="/crm/leads?scope=waiting",
        )
    if wants_letters(view) and snap.letters is not None:
        cards["letters_without_resolution"] = QueueCard(
            key="letters_without_resolution",
            label=tr(
                "Входящие без резолюции",
                "Rezolyusiyasiz kiruvçilar",
                "Incoming without a resolution",
            ),
            count=len(snap.letters),
            hint=tr("Документы · Входящие", "Hujjatlar · Kiruvçi", "Documents · Incoming")
            + (tr(" · не меньше", " · kamida", " · at least") if snap.letters_more else ""),
            path="/eds/inbox",
        )
    if wants_mail(view) and snap.mail is not None:
        cards["inbound_mail"] = QueueCard(
            key="inbound_mail",
            label=tr("Входящая почта", "Kiruvçi poçta", "Incoming mail"),
            count=snap.mail_total,
            hint=(
                tr("Документы · Почта", "Hujjatlar · Poçta", "Documents · Mail")
                if snap.mail_configured
                else tr(
                    "Почта не подключена — Настройки · Подключения · Почта",
                    "Poçta ulanmagan — Sozlamalar · Ulanişlar · Poçta",
                    "Mail is not connected — Settings · Connections · Mail",
                )
            ),
            path="/eds/mail",
        )
    if wants_approvals(view) and snap.quotes is not None:
        # D26G-4: число — те же строки «Одобрить КП», что в очереди (одна логика, без расхождений)
        cards["quotes_to_approve"] = QueueCard(
            key="quotes_to_approve",
            label=tr("КП на одобрение", "Maqullaş uçun TT", "Quotes to approve"),
            count=sum(1 for i in queue if i.kind == "approve_quote" and i.on_behalf_of is None),
            hint=tr("Документы · Исходящие", "Hujjatlar · Çiquvçi", "Documents · Outgoing")
            + (tr(" · не меньше", " · kamida", " · at least") if snap.quotes_more else ""),
            path="/eds/drafts",
        )
    if wants_memos(view) and snap.memos is not None:
        cards["memos_to_approve"] = QueueCard(
            key="memos_to_approve",
            label=tr("Служебные записки", "Xizmat xatlari", "Internal memos"),
            count=_own_count(snap.memos),
            hint=tr("Документы · Внутренние", "Hujjatlar · Içki", "Documents · Internal")
            + (tr(" · не меньше", " · kamida", " · at least") if snap.memos_more else ""),
            path="/eds/approvals",
        )
    counts = snap.invoice_counts
    if counts is not None and wants_work(view, "confirm_payment"):
        cards["payments_to_confirm"] = QueueCard(
            key="payments_to_confirm",
            label=tr(
                "Платёжные поручения на подтверждение",
                "Tasdiqlaş uçun tölovlar",
                "Payments to confirm",
            ),
            count=counts["proofs"],
            hint=tr("Операции · Финансы", "Amallar · Moliya", "Operations · Finance"),
            path="/eds/payments?show=proofs",
        )
    if counts is not None and wants_work(view, "issue_invoice"):
        cards["invoices_to_issue"] = QueueCard(
            key="invoices_to_issue",
            label=tr("Счета к выставлению", "Çiqariladigan hisoblar", "Invoices to issue"),
            count=counts["to_issue"],
            hint=tr("Операции · Финансы", "Amallar · Moliya", "Operations · Finance"),
            path="/eds/payments?show=to_issue",
        )
    if wants_projects(view):
        cards["projects_in_work"] = QueueCard(
            key="projects_in_work",
            label=tr("Проекты в работе", "Işdagi loyihalar", "Projects in progress"),
            count=projects_in_work(snap),
            hint=tr("Главная · Проекты", "Asosiy · Loyihalar", "Home · Projects"),
            path="/eds/projects",
        )
    if snap.zones_without_responsible:
        # ЕВ-З: сигнал, а не счётчик работы — пока есть зона без ответственного; первой, чтобы
        # лимит карточек не отрезал её.
        cards = {
            "zones_without_responsible": QueueCard(
                key="zones_without_responsible",
                label=tr("Зоны без ответственного", "Masʼulsiz zonalar", "Zones without an owner"),
                count=snap.zones_without_responsible,
                hint=tr(
                    "Настройки · Люди и доступ · Зоны ответственности",
                    "Sozlamalar · Odamlar va kiriş · Masʼuliyat zonalari",
                    "Settings · People and access · Responsibility zones",
                ),
                path="/admin/zones",
            ),
            **cards,
        }
    return list(cards.values())[:MAX_CARDS]


def build_counters(view: View, snap: Snapshot, queue: list[QueueItem]) -> list[MenuCounter]:
    """Бейджи подменю: красный — требует действия, серый — счётчик. Пункты вне ролей «вида» не
    перечисляются."""
    # Бейдж «Задачи» равен числу строк списка, включая «за {имя}» (замещение); остальные бейджи и
    # карточки считают только свои дела
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
        total = sum(1 for i in queue if i.kind == "approve_quote" and i.on_behalf_of is None)
        items.append(MenuCounter(module="eds", section="drafts", count=total, attention=total > 0))
    if wants_memos(view) and snap.memos is not None:
        total = _own_count(snap.memos)
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
