"""Бизнес-номера и пути объектов SPA (SPEC-v3 §2.2, 03-frontend.md §6).

**Временно, до ERP-09** (`Deal.number`, 04-integration-map.md §7): в ERP у сделки нет номера ЗВ/ПР.
Пока поля нет, номер выводится из года создания и идентификатора — `ЗВ-2026-104`: он стабилен,
обратим (id — последнее число) и по формату совпадает с номером, который выдаст ERP-09. Как только
сделка приходит с полем `number`, берётся оно.
"""

import re
from typing import Any, Literal

from app.feeds.models import ObjectKind, ObjectRef
from app.feeds.text import parse_dt, segment

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

# Шаг пути заявки по стадии сделки ERP; полный вывод по документам — 04-integration-map.md §2
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


def deal_step(deal: dict[str, Any]) -> DealStep:
    if deal.get("execution_complete") is True:
        return "DONE"
    return _STAGE_STEP.get(str(deal.get("stage_code") or ""), "REQUEST")


def deal_kind(step: DealStep) -> ObjectKind:
    return "project" if step in _PROJECT_STEPS else "request"


def deal_number(deal: dict[str, Any]) -> str:
    own = deal.get("number")
    if isinstance(own, str) and own:
        return own
    created = parse_dt(deal.get("created_at"))
    year = created.year if created else 0
    prefix = "ПР" if deal_kind(deal_step(deal)) == "project" else "ЗВ"
    return f"{prefix}-{year:04d}-{int(deal['id']):03d}"


def deal_title(deal: dict[str, Any]) -> str:
    return str(deal.get("title") or deal.get("company_name") or deal_number(deal))


def deal_ref(deal: dict[str, Any], *, tab: str = "card") -> ObjectRef:
    """Заявка (ЗВ) открывается в «Все заявки» CRM, проект (ПР) — в EDS; боковое окно — на вкладке
    `tab`."""
    step = deal_step(deal)
    number = deal_number(deal)
    side = f"panel=open&tab={tab}"
    if deal_kind(step) == "project":
        path = f"/eds/projects/{segment(number)}?{side}"
    else:
        path = f"/crm/requests?request={segment(number)}&{side}"
    return ObjectRef(
        kind=deal_kind(step),
        number=number,
        title=deal_title(deal),
        path=path,
        step=step,
    )


def lead_ref(lead_id: int, title: str | None) -> ObjectRef:
    number = lead_number(lead_id)
    return ObjectRef(
        kind="lead",
        number=number,
        title=title,
        path=f"/crm/leads?lead={segment(number)}&panel=open&tab=card",
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
