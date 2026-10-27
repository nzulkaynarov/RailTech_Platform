"""Расчёт по заявке: схемы `Calc*` из packages/contracts/openapi/platform-bff.yaml (0.22.0, D2-1) и
перевод ответов ERP (`/api/v1/calc/*`, `crm.services.calculation`) в ответ Платформы.

BFF не решает: зону строки, визы, «Расчёт готов» и права решает ERP. Здесь — номер ЗВ и шаг пути (до
ERP-09 номер составляет BFF, `app.feeds.numbers`), вырезание полей с ограничением по каталогу
(`platform-rbac.yaml` `restricted_fields`): себестоимость, закупка и наценка по строкам и порог
маржи — `cost_margin`; итоги закупки и наценки — `cost_margin` или `totals_only`; цены предложений
поставщиков — `supplier_prices`.
"""

import datetime as dt
from collections.abc import Collection
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.feeds.models import StepCode
from app.feeds.numbers import deal_number, deal_step, deal_title
from app.feeds.text import segment

CalcState = Literal["not_started", "in_progress", "returned", "at_director", "rejected", "approved"]
VisaState = Literal["none", "waiting", "done"]
Zone = Literal["goods", "services", "payment_terms"]
LineZone = Literal["goods", "services"]
LineKind = Literal["goods", "goods_to_order", "service"]
Group = Literal["stock", "supply", "engineer"]
Blocker = Literal["not_started", "not_draft", "no_lines", "visas_missing"]

DECIMAL = r"^-?[0-9]+(\.[0-9]+)?$"
DIGITS = r"^[0-9]+$"

# --- ответ BFF ---------------------------------------------------------------------------------


class CalcVisaIndicators(BaseModel):
    stock: VisaState
    supply: VisaState
    engineer: VisaState


class CalcAssignee(BaseModel):
    zone: Zone
    name: str | None


class CalcRequestRow(BaseModel):
    number: str
    title: str
    client: str | None
    step: StepCode
    state: CalcState
    due: dt.date
    letter_number: str
    lines: int
    visas: CalcVisaIndicators
    responsible: str | None
    assignees: list[CalcAssignee]
    path: str


class CalcRequestList(BaseModel):
    items: list[CalcRequestRow]


class CalcTask(BaseModel):
    letter_number: str
    letter_subject: str
    resolution_text: str
    decided_at: dt.datetime
    decided_by: str | None
    due: dt.date
    min_margin_pct: str | None = None
    assignees: list[CalcAssignee]


class CalcRequestText(BaseModel):
    text: str
    lines: int


class CalcQuote(BaseModel):
    number: str | None
    version: int
    state: CalcState
    director_comment: str | None
    vat_rate: str


class CalcStock(BaseModel):
    on_hand: int | None
    cell: str | None
    reserved: int | None


class CalcSupplier(BaseModel):
    name: str
    lead_days: int | None
    min_order_qty: int
    price_valid_until: dt.date | None
    offer_price: str | None = None
    offer_currency: str | None = None


class CalcLineVisa(BaseModel):
    by: str
    at: dt.datetime


class CalcLine(BaseModel):
    id: str
    name: str
    article: str
    product_id: str | None
    product_name: str | None
    kind: LineKind
    zone: LineZone
    group: Group
    quantity: int
    unit: str
    stock: CalcStock
    supplier: CalcSupplier | None
    lead_days: int | None
    purchase_price: str | None = None
    purchase_currency: str | None = None
    crew_rate: str | None
    crew_days: str | None
    cost: str | None = None
    client_price: str
    markup_pct: str | None = None
    visa: CalcLineVisa | None
    can_edit: bool


class CalcTotals(BaseModel):
    client: str
    purchase: str | None = None
    markup_pct: str | None = None
    vat_included: Literal[False] = False


class CalcVisaGroup(BaseModel):
    state: VisaState
    total: int
    signed: int
    by: list[str]


class CalcVisaGroups(BaseModel):
    stock: CalcVisaGroup
    supply: CalcVisaGroup
    engineer: CalcVisaGroup


class CalcReady(BaseModel):
    allowed: bool
    blocker: Blocker | None
    missing: int


class CalcRights(BaseModel):
    goods: bool
    services: bool
    build: bool
    cost: bool


class CalcSheet(BaseModel):
    number: str
    title: str
    client: str | None
    step: StepCode
    path: str
    task: CalcTask
    request: CalcRequestText
    quote: CalcQuote | None
    lines: list[CalcLine]
    totals: CalcTotals
    visas: CalcVisaGroups
    ready: CalcReady
    rights: CalcRights


class CalcProposalLine(BaseModel):
    name: str
    quantity: int
    unit: str
    article: str
    note: str


class CalcParseJob(BaseModel):
    job_id: str


class CalcParseResult(BaseModel):
    status: Literal["pending", "done", "failed"]
    lines: list[CalcProposalLine]
    recognized: int | None = None
    truncated: bool | None = None
    reason: str | None = None


class CalcCatalogItem(BaseModel):
    id: str
    name: str
    article: str
    kind: Literal["goods", "service"]
    on_hand: int
    supplier_name: str | None
    lead_days: int | None


class CalcCatalogPage(BaseModel):
    items: list[CalcCatalogItem]


# --- запросы -----------------------------------------------------------------------------------

_STRICT = ConfigDict(extra="forbid")


class CalcLineIn(BaseModel):
    model_config = _STRICT

    name: str | None = Field(default=None, max_length=500)
    quantity: int | None = Field(default=None, ge=1, le=1_000_000)
    unit: str | None = Field(default=None, max_length=32)
    kind: Literal["goods", "service"] | None = None
    product_id: str | None = Field(default=None, pattern=DIGITS, max_length=12)
    article: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=1000)


class CalcLinesIn(BaseModel):
    model_config = _STRICT

    lines: list[CalcLineIn] = Field(min_length=1, max_length=50)


class CalcLinePatch(BaseModel):
    model_config = _STRICT

    name: str | None = Field(default=None, min_length=1, max_length=500)
    quantity: int | None = Field(default=None, ge=1, le=1_000_000)
    unit: str | None = Field(default=None, max_length=32)
    lead_days: int | None = Field(default=None, ge=0, le=3650)
    purchase_price: str | None = Field(default=None, pattern=DECIMAL, max_length=20)
    purchase_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    crew_rate: str | None = Field(default=None, pattern=DECIMAL, max_length=20)
    crew_days: str | None = Field(default=None, pattern=DECIMAL, max_length=10)
    client_price: str | None = Field(default=None, pattern=DECIMAL, max_length=20)
    product_id: str | None = Field(default=None, pattern=DIGITS, max_length=12)
    kind: Literal["goods", "service"] | None = None


class CalcParseIn(BaseModel):
    model_config = _STRICT

    text: str | None = Field(default=None, max_length=20000)


# --- перевод ответов ERP -----------------------------------------------------------------------


def calc_path(number: str) -> str:
    return f"/erp/calc/{segment(number)}"


def _id(value: Any) -> str | None:
    return None if value is None else str(value)


def _assignees(raw: list[dict[str, Any]]) -> list[CalcAssignee]:
    return [CalcAssignee(zone=a["zone"], name=a.get("name")) for a in raw]


def to_row(raw: dict[str, Any]) -> CalcRequestRow:
    deal = raw["deal"]
    number = deal_number(deal)
    return CalcRequestRow(
        number=number,
        title=deal_title(deal),
        client=deal.get("client_name"),
        step=deal_step(deal),
        state=raw["state"],
        due=raw["due"],
        letter_number=raw["letter_number"],
        lines=raw["lines"],
        visas=CalcVisaIndicators(**raw["visas"]),
        responsible=deal.get("manager_name"),
        assignees=_assignees(raw["assignees"]),
        path=calc_path(number),
    )


def _line(raw: dict[str, Any], *, cost: bool, supplier_prices: bool) -> CalcLine:
    supplier = raw.get("supplier")
    supplier_model = None
    if isinstance(supplier, dict):
        supplier_model = CalcSupplier(
            name=supplier["name"],
            lead_days=supplier.get("lead_days"),
            min_order_qty=supplier["min_order_qty"],
            price_valid_until=supplier.get("price_valid_until"),
        )
        if supplier_prices:
            supplier_model.offer_price = supplier.get("offer_price")
            supplier_model.offer_currency = supplier.get("offer_currency")
    visa = raw.get("visa")
    line = CalcLine(
        id=str(raw["id"]),
        name=raw["name"],
        article=raw.get("article") or "",
        product_id=_id(raw.get("product_id")),
        product_name=raw.get("product_name"),
        kind=raw["kind"],
        zone=raw["zone"],
        group=raw["group"],
        quantity=raw["quantity"],
        unit=raw.get("unit") or "",
        stock=CalcStock(**raw["stock"]),
        supplier=supplier_model,
        lead_days=raw.get("lead_days"),
        crew_rate=raw.get("crew_rate"),
        crew_days=raw.get("crew_days"),
        client_price=raw["client_price"],
        visa=CalcLineVisa(**visa) if isinstance(visa, dict) else None,
        can_edit=bool(raw.get("can_edit")),
    )
    if cost:
        line.purchase_price = raw.get("purchase_price")
        line.purchase_currency = raw.get("purchase_currency")
        line.cost = raw.get("cost")
        line.markup_pct = raw.get("markup_pct")
    return line


def to_sheet(raw: dict[str, Any], fields: Collection[str]) -> CalcSheet:
    """Расчёт ERP -> ответ Платформы; поля с ограничением — только группам, которые их видят."""
    cost = "cost_margin" in fields
    totals_visible = cost or "totals_only" in fields
    supplier_prices = "supplier_prices" in fields
    deal = raw["deal"]
    number = deal_number(deal)
    task = raw["task"]
    task_model = CalcTask(
        letter_number=task["letter_number"],
        letter_subject=task.get("letter_subject") or "",
        resolution_text=task.get("resolution_text") or "",
        decided_at=task["decided_at"],
        decided_by=task.get("decided_by_name"),
        due=task["due"],
        assignees=_assignees(task.get("assignees") or []),
    )
    if cost:
        task_model.min_margin_pct = task.get("min_margin_pct")
    quote = raw.get("quote")
    totals = raw["totals"]
    totals_model = CalcTotals(client=totals["client"], vat_included=False)
    if totals_visible:
        totals_model.purchase = totals.get("purchase")
        totals_model.markup_pct = totals.get("markup_pct")
    return CalcSheet(
        number=number,
        title=deal_title(deal),
        client=deal.get("client_name"),
        step=deal_step(deal),
        path=calc_path(number),
        task=task_model,
        request=CalcRequestText(**raw["request"]),
        quote=None
        if not isinstance(quote, dict)
        else CalcQuote(
            number=quote.get("number"),
            version=quote["version"],
            state=quote["state"],
            director_comment=quote.get("director_comment"),
            vat_rate=quote["vat_rate"],
        ),
        lines=[_line(item, cost=cost, supplier_prices=supplier_prices) for item in raw["lines"]],
        totals=totals_model,
        visas=CalcVisaGroups(**raw["visas"]),
        ready=CalcReady(**raw["ready"]),
        rights=CalcRights(**{**raw["rights"], "cost": bool(raw["rights"]["cost"]) and cost}),
    )
