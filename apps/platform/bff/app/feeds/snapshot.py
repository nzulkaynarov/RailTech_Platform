"""Сырые данные на один запрос: входящие CRM, сделки ERP, письма, КП и документы на согласовании
EDS.

Источники — docs/architecture/integration-map.md §1.2.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.feeds.feed import SNAPSHOT_TTL_SECONDS, Feed, rows
from app.feeds.models import QueueItemKind
from app.feeds.rework import Returned, load_rework
from app.feeds.work_roles import wants_work
from app.rbac import View, allows

# Сделки ERP постранично (DRF: максимум 200 на страницу); берём новейшие — поиск и счётчики
# работают по ним.
DEALS_PAGE_SIZE = 100
APPROVALS_PAGE_SIZE = 50
LETTERS_PATH = "/api/v1/letters"
LETTERS_PARAMS: dict[str, Any] = {"status": "awaiting_resolution", "limit": APPROVALS_PAGE_SIZE}
APPROVALS_PATH = "/api/v1/approvals"
# D26G-4: КП на одобрении на моём шаге маршрута EDS — тот же запрос, что экран «КП на одобрение · На
# моём шаге» (`GET /eds/quotes`): одобрение директора — маршрут EDS (`approvals.decide`), не ERP.
QUOTE_PARAMS: dict[str, Any] = {
    "mine": "true",
    "status": "open",
    "template": ["quote"],
    "limit": APPROVALS_PAGE_SIZE,
}
# Карточек маршрутов КП (клиент, сумма, срок — снимок EDS) за один опрос не больше стольких.
QUOTE_DETAILS_MAX = 20
QUOTE_DETAILS_PARALLEL = 8
# Служебные записки, заявления и отчёты на моём шаге маршрута (`mine` — по умолчанию).
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
    # EDS (D26G-4): маршруты КП на моём шаге (`None` — не читали или EDS не ответил: строк, карточки
    # и бейджа нет) и снимки КП из карточек маршрутов (id маршрута -> `quote`) для подписи строки.
    quotes: list[dict[str, Any]] | None = None
    quotes_more: bool = False
    quote_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    deals: list[dict[str, Any]] = field(default_factory=list)
    # EDS: мои документы, возвращённые на доработку (D1-6b); `None` — не читали или EDS не ответил.
    rework: list[Returned] | None = None
    # EDS: `None` — источник не читали или он не ответил (карточка и бейдж без числа: ноль был бы
    # ложью), список — ответ EDS как есть (что EDS вернул по токену сотрудника, то и строки).
    letters: list[dict[str, Any]] | None = None
    memos: list[dict[str, Any]] | None = None
    # Есть следующая страница EDS: число в карточке — «не меньше», а не точное
    letters_more: bool = False
    memos_more: bool = False
    # Новые обращения сотрудников (CRM `staff-tickets?status=new`): админу — «Мои задачи» (W15-H7).
    tickets: list[dict[str, Any]] = field(default_factory=list)
    tickets_total: int = 0
    # Входящая почта общего ящика (CRM `inbound-mail?view=tasks`, W18A-P2): канцелярии — «Мои
    # задачи»; `None` — не читали или CRM не ответил (строк и бейджа нет), `mail_configured` —
    # настроен ли приём (иначе карточка подсказывает «Настройки · Подключения · Почта»).
    mail: list[dict[str, Any]] | None = None
    mail_total: int = 0
    mail_configured: bool = True
    # Просроченные заказы поставщикам (ERP `stock/overdue`): снабженцу — «Мои задачи» (D2-2).
    overdue_orders: list[dict[str, Any]] = field(default_factory=list)
    # P8b: мои поручения, переносы на решение и ознакомления (EDS `GET /letter-tasks`); `None` —
    # EDS не читали или он не ответил (строк нет).
    letter_tasks: dict[str, list[dict[str, Any]]] | None = None
    # D2-8, работа ERP: мои задания на расчёт (`GET /calc/tasks/?mine=1`); `None` — не читали или
    # ERP не ответил (строк и бейджа «Мои расчёты» нет).
    calc_tasks: list[dict[str, Any]] | None = None
    # Счета «Платёжки на подтверждение» и «К выставлению» (ERP `/finance/receivables/?tab=`) и числа
    # вкладок той же доски (`counts`); `None` — ERP не ответил, бейджа и карточек нет.
    invoices_with_proofs: list[dict[str, Any]] = field(default_factory=list)
    invoices_to_issue: list[dict[str, Any]] = field(default_factory=list)
    invoice_counts: dict[str, int] | None = None
    # Проекты на шагах «Договор» и «Оплата» (ERP `/crm/projects/?step=`): договор и акт к действию.
    projects_contract: list[dict[str, Any]] = field(default_factory=list)
    projects_payment: list[dict[str, Any]] = field(default_factory=list)

    @property
    def deal_index(self) -> dict[int, dict[str, Any]]:
        return {int(d["id"]): d for d in self.deals if isinstance(d.get("id"), int)}


# Виды работы по лидам (секция `queue` каталога): их даёт раздел CRM-лидов; без него BFF не зовёт
# CRM `/inbox` (у сотрудника нет прав CRM на лиды — был бы 403).
LEAD_KINDS = ("answer_lead", "take_lead", "triage_lead")


def wants_inbox(view: View) -> bool:
    return any(view.wants(kind) for kind in LEAD_KINDS)


def wants_approvals(view: View) -> bool:
    return view.wants("approve_quote")


def wants_letters(view: View) -> bool:
    return view.wants("resolve_letter")


def wants_memos(view: View) -> bool:
    return view.wants("approve_memo") or view.wants("pay_memo")


# Виды работы по входящим делопроизводства (P8b): поручение, перенос срока, ознакомление.
LETTER_TASK_KINDS = ("instruction", "instruction_extension", "acquaint")
LETTER_TASKS_PATH = "/api/v1/letter-tasks"


def wants_letter_tasks(view: View) -> bool:
    return any(view.wants(kind) for kind in LETTER_TASK_KINDS)


def wants_tickets(view: View) -> bool:
    return view.wants("ticket")


def wants_mail(view: View) -> bool:
    return view.wants("inbound_mail")


def wants_mail_mine(view: View) -> bool:
    """Письма «в работе» у сотрудника или адресованные ему лично — у любого сотрудника
    (W18A-P2-3)."""
    return view.wants("inbound_mail_mine")


def wants_supplier_overdue(view: View) -> bool:
    return view.wants("supplier_overdue")


# Работа ERP «Моих задач» (D2-8): расчёт, счета и платёжки, договор и акт проекта.
INVOICE_KINDS: tuple[QueueItemKind, ...] = ("confirm_payment", "issue_invoice")
PROJECT_KINDS: tuple[QueueItemKind, ...] = ("issue_contract", "attach_scan", "issue_act")
CALC_TASKS_PATH = "/api/v1/calc/tasks/"
RECEIVABLES_PATH = "/api/v1/finance/receivables/"
PROJECTS_PATH = "/api/v1/crm/projects/"
WORK_PAGE_SIZE = 50
PROJECTS_PAGE_SIZE = 100


def wants_calc_tasks(view: View) -> bool:
    return wants_work(view, "calc_task")


def wants_invoices(view: View) -> bool:
    return any(wants_work(view, kind) for kind in INVOICE_KINDS)


def wants_project_work(view: View) -> bool:
    return any(wants_work(view, kind) for kind in PROJECT_KINDS)


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


async def _quote_snapshots(feed: Feed, routes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Снимки КП (клиент, сумма, срок действия) из карточек маршрутов EDS: решающему шаг EDS их
    отдаёт, остальным — нет. Сбой карточки — строка без суммы, а не пустая очередь."""
    ids = [r["id"] for r in routes if isinstance(r.get("id"), str)][:QUOTE_DETAILS_MAX]
    sem = asyncio.Semaphore(QUOTE_DETAILS_PARALLEL)

    async def one(route_id: str) -> tuple[str, dict[str, Any] | None]:
        async with sem:
            body = await feed.get("eds", f"{APPROVALS_PATH}/{route_id}", ttl=SNAPSHOT_TTL_SECONDS)
        quote = body.get("quote") if isinstance(body, dict) else None
        return route_id, quote if isinstance(quote, dict) else None

    found = await asyncio.gather(*(one(i) for i in ids))
    return {route_id: quote for route_id, quote in found if quote is not None}


OVERDUE_PATH = "/api/v1/stock/overdue/"
TICKETS_PATH = "/api/v1/staff-tickets"
TICKETS_PARAMS = {"status": "new", "limit": 20}
MAIL_PATH = "/api/v1/inbound-mail"
# Строки «Моих задач» (W18A-P2-3): Новые (без писем «из истории», W18A-P2-2) и мои в работе — всё
# остальное
# (чужие «в работе», «Разобрано») строкой не приходит; решает CRM (`view=tasks`), BFF только просит.
MAIL_PARAMS = {"view": "tasks"}


async def load_snapshot(
    feed: Feed,
    view: View,
    *,
    inbox: bool,
    approvals: bool,
    deals: bool,
    tickets: bool = False,
    eds: bool = False,
    stock: bool = False,
    work: bool = False,
) -> Snapshot:
    """Параллельно прочитать нужные источники. `view` — роли «вида» (активная роль, если задана);
    сделки нужны и для подписей к очереди и уведомлениям, поэтому их читает тот, кто их просит."""
    snap = Snapshot()

    async def load_inbox() -> None:
        if inbox and wants_inbox(view):
            snap.inbox, snap.covered = await asyncio.gather(_inbox(feed), _covered(feed))

    async def load_approvals() -> None:
        if approvals and eds and wants_approvals(view):
            payload = await feed.get("eds", APPROVALS_PATH, QUOTE_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
            if payload is not None:
                snap.quotes = [r for r in rows(payload) if r.get("template") == "quote"]
                snap.quotes_more = _has_more(payload)
                snap.quote_snapshots = await _quote_snapshots(feed, snap.quotes)

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

    async def load_letter_tasks() -> None:
        if eds and wants_letter_tasks(view):
            payload = await feed.get("eds", LETTER_TASKS_PATH, ttl=SNAPSHOT_TTL_SECONDS)
            if isinstance(payload, dict):
                snap.letter_tasks = {
                    key: rows(payload.get(key))
                    for key in ("instructions", "extensions", "acquaintances")
                }

    async def load_deals() -> None:
        if deals:
            payload = await feed.get("erp", DEALS_PATH, DEALS_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
            snap.deals = rows(payload)

    async def load_returned() -> None:
        if eds:
            snap.rework = await load_rework(feed, view)

    async def load_tickets() -> None:
        if tickets and wants_tickets(view):
            payload = await feed.get("crm", TICKETS_PATH, TICKETS_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
            snap.tickets = rows(payload)
            total = payload.get("total") if isinstance(payload, dict) else None
            snap.tickets_total = total if isinstance(total, int) else len(snap.tickets)

    async def load_mail() -> None:
        if tickets and (wants_mail(view) or wants_mail_mine(view)):
            payload = await feed.get("crm", MAIL_PATH, MAIL_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
            if isinstance(payload, dict):
                snap.mail = rows(payload)
                total = payload.get("total")
                snap.mail_total = total if isinstance(total, int) else len(snap.mail)
                mailbox = payload.get("mailbox")
                snap.mail_configured = not (
                    isinstance(mailbox, dict) and mailbox.get("configured") is False
                )

    async def load_stock() -> None:
        if stock and wants_supplier_overdue(view):
            # ERP не ответил — очередь без просроченных заказов, `sources.erp = unavailable`.
            payload = await feed.get("erp", OVERDUE_PATH, ttl=SNAPSHOT_TTL_SECONDS)
            snap.overdue_orders = rows(payload)

    async def load_calc() -> None:
        if work and wants_calc_tasks(view):
            payload = await feed.get("erp", CALC_TASKS_PATH, {"mine": 1}, ttl=SNAPSHOT_TTL_SECONDS)
            if isinstance(payload, dict):
                snap.calc_tasks = rows(payload)

    async def load_invoices() -> None:
        if not (work and wants_invoices(view)):
            return

        async def tab(name: str) -> Any:
            params = {"tab": name, "limit": WORK_PAGE_SIZE}
            return await feed.get("erp", RECEIVABLES_PATH, params, ttl=SNAPSHOT_TTL_SECONDS)

        proofs, drafts = await asyncio.gather(tab("proofs"), tab("to_issue"))
        snap.invoices_with_proofs = rows(proofs)
        snap.invoices_to_issue = rows(drafts)
        for payload in (proofs, drafts):
            counts = payload.get("counts") if isinstance(payload, dict) else None
            if isinstance(counts, dict) and all(
                isinstance(counts.get(k), int) for k in ("proofs", "to_issue")
            ):
                snap.invoice_counts = {k: int(counts[k]) for k in ("proofs", "to_issue")}

    async def load_project_work() -> None:
        if not (work and wants_project_work(view)):
            return

        async def step(name: str) -> list[dict[str, Any]]:
            params = {"step": name, "limit": PROJECTS_PAGE_SIZE}
            return rows(await feed.get("erp", PROJECTS_PATH, params, ttl=SNAPSHOT_TTL_SECONDS))

        snap.projects_contract, snap.projects_payment = await asyncio.gather(
            step("CONTRACT"), step("PAYMENT")
        )

    await asyncio.gather(
        load_calc(),
        load_invoices(),
        load_project_work(),
        load_inbox(),
        load_approvals(),
        load_deals(),
        load_tickets(),
        load_mail(),
        load_letters(),
        load_memos(),
        load_returned(),
        load_stock(),
        load_letter_tasks(),
    )
    return snap
