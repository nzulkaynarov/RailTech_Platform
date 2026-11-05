"""Бизнес-номера и пути объектов SPA (SPEC-v3 §2.2, docs/architecture/platform-frontend.md §6).

Номер заявки или проекта (ЗВ-/ПР-) выдаёт ERP (`Deal.number`, ERP-09): BFF его не составляет и из
номера `id` не разбирает (кроме `L-NNNN` лида CRM). Если ERP номера не отдал (старая запись),
показывается нейтральное `D-<id>`. Поиск сделок по номеру, названию и компании — на стороне ERP
(`?search=`, латиница ZV/PR и пробелы допустимы).
"""

import re
from typing import Any, Literal

from app.feeds.models import ObjectKind, ObjectRef
from app.feeds.text import segment

DealStep = Literal["REQUEST", "CALCULATION", "QUOTE", "CONTRACT", "PAYMENT", "DONE", "LOST"]

STEP_TITLES: dict[str, str] = {
    "REQUEST": "Заявка",
    "RESOLUTION": "Резолюция",
    "CALCULATION": "Расчёт",
    "QUOTE": "КП",
    "CONTRACT": "Договор",
    "PAYMENT": "Оплата",
    "DONE": "Выполнено",
    "LOST": "Отказ",
}

# Шаг пути заявки по стадии сделки ERP; полный вывод по документам —
# docs/architecture/integration-map.md §2
# (хвост PLT-2x).
_STAGE_STEP: dict[str, DealStep] = {
    "DRAFT": "REQUEST",
    "KYC_PENDING": "REQUEST",
    "RFQ_OPEN": "REQUEST",
    "SOURCING": "CALCULATION",
    "CALCULATING": "CALCULATION",
    "QUOTE_SENT": "QUOTE",
    "CONTRACT_SIGNED": "CONTRACT",
    "CLOSED_WON": "PAYMENT",
    "CLOSED_LOST": "LOST",
}
_PROJECT_STEPS = frozenset({"CONTRACT", "PAYMENT", "DONE"})


def lead_number(lead_id: int) -> str:
    return f"L-{lead_id:04d}"


def lead_id_of(text: str) -> int | None:
    """`L-2041`, `l2041`, `2041` с префиксом L — идентификатор лида CRM."""
    match = re.fullmatch(r"[Ll]-?(\d{1,9})", text.strip())
    return int(match.group(1)) if match else None


# Латинская запись префикса бизнес-номера (раскладка клавиатуры «ZV»), O-4 отчёта гейта P1.
_LATIN_PREFIXES = {"zv": "ЗВ", "pr": "ПР", "kp": "КП"}
_LATIN_PREFIX = re.compile(r"(?i:(zv|pr|kp))(?![^\W\d_])")

_DEAL_NUMBER_QUERY = re.compile(
    r"(?P<prefix>[^\W\d_]{2})[\s\-–—/]*(?P<year>\d{4})[\s\-–—/]*(?P<seq>\d{1,6})"
)


def cyrillic_prefix(text: str) -> str:
    """Запрос как набран, но латинский префикс номера заменён кириллическим: `kp-2026-0` ->
    `КП-2026-0`, `zv 2026` -> `ЗВ 2026`. Остальное не перестраивается: номера документов ERP
    (`КП-2026-00001`, схема и ширина настраиваются) ищутся по подстроке как есть."""
    stripped = text.strip()
    match = _LATIN_PREFIX.match(stripped)
    if match is None:
        return stripped
    return _LATIN_PREFIXES[match[1].casefold()] + stripped[match.end() :]


def number_query(text: str) -> str | None:
    """Запрос, похожий на номер заявки или проекта, в каноническом виде: `zv-2026-1` ->
    `ЗВ-2026-001` (ERP выдаёт номер с тремя знаками). Не номер ЗВ/ПР — None. Это нормализация
    набранной строки для точного вызова ERP (`GET /calc/deals/?number=`), не разбор идентификатора:
    `id` сделки из номера не извлекается. Поиск по частичному номеру — `?search=` ERP.
    """
    match = _DEAL_NUMBER_QUERY.fullmatch(text.strip())
    if match is None:
        return None
    prefix = match["prefix"].casefold()
    prefix = _LATIN_PREFIXES.get(prefix, prefix.upper())
    if prefix not in ("ЗВ", "ПР"):
        return None
    return f"{prefix}-{match['year']}-{match['seq'].zfill(3)}"


def deal_step(deal: dict[str, Any]) -> DealStep:
    if deal.get("execution_complete") is True:
        return "DONE"
    return _STAGE_STEP.get(str(deal.get("stage_code") or ""), "REQUEST")


def deal_kind(step: DealStep) -> ObjectKind:
    return "project" if step in _PROJECT_STEPS else "request"


def deal_number(deal: dict[str, Any]) -> str:
    """Номер ЗВ/ПР, который выдал ERP; нет — `D-<id>` (подпись, не ключ)."""
    own = deal.get("number")
    if isinstance(own, str) and own:
        return own
    return f"D-{int(deal['id'])}"


def deal_title(deal: dict[str, Any]) -> str:
    return str(deal.get("title") or deal.get("company_name") or deal_number(deal))


def request_path(number: str) -> str:
    """Рабочий экран заявки (B-UIA-1): «Расчёт · Заявки в расчёте» с боковым окном «Задание» —
    резолюция директора, исполнители, визы и «Открыть расчёт». «Клиенты · Заявки» — заглушка, а у
    блока «Заявки и проекты» карточки клиента нет адреса по номеру ЗВ; номер ЗВ ведёт сюда отовсюду:
    очередь, колокольчик, лента, поиск, письмо, КП."""
    return f"/erp/requests?request={segment(number)}&panel=open&tab=task"


def deal_ref(deal: dict[str, Any], *, tab: str = "card") -> ObjectRef:
    """Заявка (ЗВ) открывается в «Заявках в расчёте» (окно «Задание», `request_path`), проект (ПР)
    — в EDS; боковое окно проекта — на вкладке `tab`."""
    step = deal_step(deal)
    number = deal_number(deal)
    if deal_kind(step) == "project":
        path = f"/eds/projects/{segment(number)}?panel=open&tab={tab}"
    else:
        path = request_path(number)
    return ObjectRef(
        kind=deal_kind(step),
        number=number,
        title=deal_title(deal),
        path=path,
        step=step,
    )


def lead_ref(lead_id: int, title: str | None, *, conversation: bool = False) -> ObjectRef:
    """Лид открывается карточкой в «Все лиды»; строка, где от менеджера ждут ответа клиенту
    (`conversation`: передача бота, новое сообщение, лид без менеджера), — диалогом в «Ждут
    ответа» (D1-6): там «Забрать», лента и ответ."""
    number = lead_number(lead_id)
    path = (
        f"/crm/messages?lead={segment(number)}"
        if conversation
        else f"/crm/leads?lead={segment(number)}&panel=open&tab=card"
    )
    return ObjectRef(kind="lead", number=number, title=title, path=path)


def letter_ref(number: str, title: str | None) -> ObjectRef:
    """Входящее письмо — карточка во «Входящих», вкладка «Резолюция»."""
    return ObjectRef(
        kind="letter",
        number=number,
        title=title,
        path=f"/eds/inbox/{segment(number)}?panel=open&tab=resolution",
    )


def letter_task_ref(letter_id: str, number: str, title: str | None) -> ObjectRef:
    """Рабочий экран письма (P8b): поручение, перенос, «Ознакомиться» — `/eds/tasks/<id письма>`.

    Адрес — по UUID, не по номеру: номер BFF находит через реестр EDS (`registry.read`), а у
    исполнителя без раздела «Входящие» этого права может не быть; карточку по UUID EDS отдаёт
    участнику поручения."""
    return ObjectRef(kind="letter", number=number, title=title, path=letter_task_path(letter_id))


def letter_task_path(letter_id: str) -> str:
    return f"/eds/tasks/{segment(letter_id)}"


def outgoing_document_path(document_id: str) -> str:
    """Наш ИСХ (и черновик, переданный на регистрацию) — «Все документы» с открытой карточкой."""
    return f"/eds/documents?scope=all&doc={segment(document_id)}&panel=open"


def memo_ref(number: str, title: str | None) -> ObjectRef:
    """Служебная записка, заявление, отчёт — «На согласовании», вкладка «Согласование»."""
    return ObjectRef(
        kind="memo",
        number=number,
        title=title,
        path=f"/eds/approvals/{segment(number)}?panel=open&tab=agree",
    )


def quote_number(quote: dict[str, Any]) -> str:
    number = quote.get("number")
    if isinstance(number, str) and number:
        return number
    return f"КП v{quote.get('version') or 1}"


def quote_ref(quote: dict[str, Any], *, title: str | None, drafting: bool) -> ObjectRef:
    """КП на одобрении — «Черновик» (вкладка «Одобрение»), отправленное — «Исходящие»."""
    number = quote_number(quote)
    if drafting:
        path = f"/eds/drafts/{segment(number)}?panel=open&tab=approve"
    else:
        path = f"/eds/outbox/{segment(number)}?panel=open&tab=card"
    return ObjectRef(kind="quote", number=number, title=title, path=path)


def ticket_ref(number: str) -> ObjectRef:
    """Обращение сотрудника (`ОБР-0012`): карточка в «Обращениях сотрудников» (W15-H7)."""
    return ObjectRef(
        kind="ticket", number=number, path=f"/admin/tickets/{segment(number)}?panel=open&tab=card"
    )


def mail_ref(mail_id: int, sender: str, subject: str | None, *, own: bool = False) -> ObjectRef:
    """Письмо общего ящика до регистрации (W18A-P2): карточка в «Документы · Входящая почта»;
    номера ещё нет — вместо него адрес отправителя. Сотруднику без раздела первой линии (`own`,
    W18A-P2-3) — его письмо в рабочем экране `/eds/my-mail/…`."""
    path = f"/eds/my-mail/{mail_id}" if own else f"/eds/mail/{mail_id}"
    return ObjectRef(kind="letter", number=sender, title=subject, path=path)


def supplier_order_ref(number: str, supplier: str | None) -> ObjectRef:
    """Заказ поставщику (`ЗП-2026-031`): карточка в Расчёт · Склад (D2-2)."""
    return ObjectRef(
        kind="supplier_order",
        number=number,
        title=supplier,
        path=f"/erp/stock/{segment(number)}",
    )


def calc_ref(number: str, title: str | None) -> ObjectRef:
    """Задание на расчёт (D2-8): экран расчёта заявки `/erp/calc/ЗВ-…` — строки, визы, «Расчёт
    готов»."""
    return ObjectRef(
        kind="request",
        number=number,
        title=title,
        path=f"/erp/calc/{segment(number)}",
        step="CALCULATION",
    )


def invoice_ref(invoice_id: int, number: str, title: str | None) -> ObjectRef:
    """Счёт (D2-8): карточка в «Счетах и оплатах» с окном «Оплата» — «Подтвердить оплату» или
    «Выставить счёт»."""
    return ObjectRef(
        kind="invoice",
        number=number,
        title=title,
        path=f"/eds/payments/{invoice_id}?panel=open&tab=payment",
    )


def project_doc_ref(
    kind: Literal["project", "contract", "act"],
    number: str,
    project: str,
    title: str | None,
    *,
    tab: Literal["contract", "act"],
) -> ObjectRef:
    """Договор или акт проекта (D2-8): карточка проекта `/eds/projects/ПР-…` на вкладке
    «Договор» или «Акт», где кнопки шага (сформировать, отправить, скан, выпустить)."""
    return ObjectRef(
        kind=kind,
        number=number,
        title=title,
        path=f"/eds/projects/{segment(project)}?panel=open&tab={tab}",
    )
