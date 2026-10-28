"""Модели «Расчёт · Номенклатура и поставщики», справочников и Техдокументации (контракт BFF 0.26.0,
тег `erp-catalog`; D2-3).

Схемы `Catalog*`, `Supplier*`, `Brigade*`, `HsCode*`, `Manufacturer*`, `ExchangeRate*`, `TechDoc*`
из packages/contracts/openapi/platform-bff.yaml и перевод ответов ERP
(`catalog/items|suppliers|brigades|tech-docs`, `master-data/hs-codes`, `exchange-rates`,
`catalog/manufacturers`).

Поля с ограничением (правило 6 CONVENTIONS): цена закупки в предложении — группа
`supplier_prices`; ставка бригады — `cost_margin` или раздел `erp.calc.services`. ERP отдаёт их по
своим правам, BFF вырезает ещё раз по каталогу ролей (администратор в ERP видит всё, а роль
«Администратор» этих полей не видит)."""

from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from app.feeds.numbers import deal_number
from app.schemas_company import Body, Patch, dec, ident, opt_ident, text

ItemKind = Literal["stock", "on_order", "service_fixed", "service_milestones", "service_time"]
BrigadeKindName = Literal["brigade", "person", "subcontractor"]
TechDocKindName = Literal["tz", "drawing", "certificate", "pnr", "other"]
Validity = Literal["ok", "expiring", "expired"]
RateUnit = Literal["day", "hour"]
_KINDS = {"stock", "on_order", "service_fixed", "service_milestones", "service_time"}


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- общее --------------------------------------------------------------------------------------


class NamedRef(Out):
    id: str
    name: str


class Unit(Out):
    id: str
    code: str
    name: str


class Money(Out):
    amount: str
    currency: str | None


class MoneyIn(Body):
    amount: str
    currency: str


class PageOut(Out):
    total: int
    page: int
    page_size: int


def page_meta(data: Any, page: int, page_size: int) -> dict[str, int]:
    total = data.get("count") if isinstance(data, Mapping) else None
    rows = _rows(data)
    return {
        "total": total if isinstance(total, int) else len(rows),
        "page": page,
        "page_size": page_size,
    }


def _rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, Mapping):
        data = data.get("results", [])
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def rows_of(data: Any) -> list[dict[str, Any]]:
    return _rows(data)


def _named(raw: Any) -> NamedRef | None:
    if not isinstance(raw, Mapping) or raw.get("id") is None:
        return None
    return NamedRef(id=ident(raw["id"]), name=text(raw.get("name")))


def _money(raw: Any) -> Money | None:
    if not isinstance(raw, Mapping) or raw.get("amount") is None:
        return None
    return Money(amount=str(raw["amount"]), currency=raw.get("currency"))


# --- позиции ------------------------------------------------------------------------------------


class ProductRef(Out):
    id: str
    name: str
    sku: str


class Offer(Out):
    id: str
    supplier: NamedRef
    product: ProductRef
    supplier_sku: str
    price: Money | None
    quota_qty: int
    min_order_qty: int
    in_stock_lead_days: int
    order_lead_days: int
    stock_status: str | None
    valid_from: str | None
    valid_until: str | None
    is_active: bool
    validity: Validity


def to_offer(raw: Mapping[str, Any], *, show_prices: bool) -> Offer:
    supplier = _named(raw.get("supplier")) or NamedRef(id="0", name="")
    product = raw.get("product") or {}
    validity = raw.get("validity")
    return Offer(
        id=ident(raw.get("id")),
        supplier=supplier,
        product=ProductRef(
            id=ident(product.get("id")),
            name=text(product.get("name")),
            sku=text(product.get("sku")),
        ),
        supplier_sku=text(raw.get("supplier_sku")),
        price=_money(raw.get("price")) if show_prices else None,
        quota_qty=int(raw.get("quota_qty") or 0),
        min_order_qty=int(raw.get("min_order_qty") or 1),
        in_stock_lead_days=int(raw.get("in_stock_lead_days") or 0),
        order_lead_days=int(raw.get("order_lead_days") or 0),
        stock_status=raw.get("stock_status"),
        valid_from=raw.get("valid_from"),
        valid_until=raw.get("valid_until"),
        is_active=bool(raw.get("is_active", True)),
        validity=validity if validity in ("ok", "expiring", "expired") else "ok",
    )


class Item(Out):
    id: str
    sku: str
    name: str
    kind: ItemKind
    unit: Unit | None
    vat_rate: str | None
    vat_effective: str | None
    category: NamedRef | None
    status: str | None
    offers_count: int
    nearest_valid_until: str | None
    docs_count: int


class TechDocRef(Out):
    id: str
    title: str
    kind: TechDocKindName


class ItemDetail(Item):
    description: str
    gost_drawing: str
    hs_code: str
    manufacturer_part_number: str
    brand: str | None
    offers: list[Offer]
    prices_visible: bool
    tech_docs: list[TechDocRef]


class ItemPage(PageOut):
    items: list[Item]


def _kind(value: Any) -> ItemKind:
    return value if value in _KINDS else "on_order"


def _unit(raw: Any) -> Unit | None:
    if not isinstance(raw, Mapping) or raw.get("id") is None:
        return None
    return Unit(id=ident(raw["id"]), code=text(raw.get("code")), name=text(raw.get("name")))


def to_item(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": ident(raw.get("id")),
        "sku": text(raw.get("sku")),
        "name": text(raw.get("name")),
        "kind": _kind(raw.get("kind")),
        "unit": _unit(raw.get("unit")),
        "vat_rate": dec(raw.get("vat_rate")),
        "vat_effective": dec(raw.get("vat_effective")),
        "category": _named(raw.get("category")),
        "status": raw.get("status"),
        "offers_count": int(raw.get("offers_count") or 0),
        "nearest_valid_until": raw.get("nearest_valid_until"),
        "docs_count": int(raw.get("docs_count") or 0),
    }


def to_item_detail(raw: Mapping[str, Any], *, show_prices: bool) -> ItemDetail:
    docs = [
        TechDocRef(
            id=ident(d.get("id")), title=text(d.get("title")), kind=_tech_kind(d.get("kind"))
        )
        for d in raw.get("tech_docs") or []
        if isinstance(d, Mapping)
    ]
    return ItemDetail(
        **to_item(raw),
        description=text(raw.get("description")),
        gost_drawing=text(raw.get("gost_drawing")),
        hs_code=text(raw.get("hs_code")),
        manufacturer_part_number=text(raw.get("manufacturer_part_number")),
        brand=raw.get("brand"),
        offers=[
            to_offer(o, show_prices=show_prices)
            for o in raw.get("offers") or []
            if isinstance(o, Mapping)
        ],
        prices_visible=show_prices and bool(raw.get("prices_visible")),
        tech_docs=docs,
    )


def to_item_page(data: Any, page: int, page_size: int) -> ItemPage:
    return ItemPage(
        items=[Item(**to_item(r)) for r in _rows(data)], **page_meta(data, page, page_size)
    )


class ItemCreate(Body):
    name: str
    kind: ItemKind
    description: str | None = None
    unit_id: str | None = None
    category_id: str | None = None
    vat_rate: str | None = None


class ItemUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"unit_id", "category_id", "vat_rate"})
    name: str | None = None
    kind: ItemKind | None = None
    description: str | None = None
    unit_id: str | None = None
    category_id: str | None = None
    vat_rate: str | None = None


def item_to_erp(sent: dict[str, Any]) -> dict[str, Any]:
    out = dict(sent)
    for key in ("unit_id", "category_id"):
        if key in out and out[key] is not None:
            out[key] = int(out[key])
    return out


# --- поставщики ---------------------------------------------------------------------------------


class SupplierRow(Out):
    id: str
    name: str
    tin: str
    country: str | None
    offers_count: int
    expired_count: int
    expiring_count: int
    nearest_valid_until: str | None


class SupplierDetail(SupplierRow):
    contact_person: str
    phone: str
    email: str
    website: str
    legal_address: str
    offers: list[Offer]
    prices_visible: bool


class SupplierPage(PageOut):
    items: list[SupplierRow]


def to_supplier(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": ident(raw.get("id")),
        "name": text(raw.get("name")),
        "tin": text(raw.get("tin")),
        "country": raw.get("country"),
        "offers_count": int(raw.get("offers_count") or 0),
        "expired_count": int(raw.get("expired_count") or 0),
        "expiring_count": int(raw.get("expiring_count") or 0),
        "nearest_valid_until": raw.get("nearest_valid_until"),
    }


def to_supplier_detail(raw: Mapping[str, Any], *, show_prices: bool) -> SupplierDetail:
    return SupplierDetail(
        **to_supplier(raw),
        contact_person=text(raw.get("contact_person")),
        phone=text(raw.get("phone")),
        email=text(raw.get("email")),
        website=text(raw.get("website")),
        legal_address=text(raw.get("legal_address")),
        offers=[
            to_offer(o, show_prices=show_prices)
            for o in raw.get("offers") or []
            if isinstance(o, Mapping)
        ],
        prices_visible=show_prices and bool(raw.get("prices_visible")),
    )


def to_supplier_page(data: Any, page: int, page_size: int) -> SupplierPage:
    return SupplierPage(
        items=[SupplierRow(**to_supplier(r)) for r in _rows(data)],
        **page_meta(data, page, page_size),
    )


class OfferUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"stock_status", "valid_from", "valid_until"})
    price: MoneyIn | None = None
    quota_qty: int | None = None
    min_order_qty: int | None = None
    in_stock_lead_days: int | None = None
    order_lead_days: int | None = None
    stock_status: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    is_active: bool | None = None


# --- бригады ------------------------------------------------------------------------------------


class CrewRate(Out):
    amount: str
    currency: str | None
    unit: RateUnit


class Brigade(Out):
    id: str
    name: str
    kind: BrigadeKindName
    specialization: str
    headcount: int
    rate: CrewRate | None
    rate_visible: bool
    note: str
    is_active: bool


class BrigadePage(PageOut):
    items: list[Brigade]


def to_brigade(raw: Mapping[str, Any], *, show_rates: bool) -> Brigade:
    rate = raw.get("rate")
    kind = raw.get("kind")
    return Brigade(
        id=ident(raw.get("id")),
        name=text(raw.get("name")),
        kind=kind if kind in ("brigade", "person", "subcontractor") else "brigade",
        specialization=text(raw.get("specialization")),
        headcount=int(raw.get("headcount") or 1),
        rate=(
            CrewRate(
                amount=str(rate["amount"]),
                currency=rate.get("currency"),
                unit="hour" if rate.get("unit") == "hour" else "day",
            )
            if show_rates and isinstance(rate, Mapping) and rate.get("amount") is not None
            else None
        ),
        rate_visible=show_rates and bool(raw.get("rate_visible")),
        note=text(raw.get("note")),
        is_active=bool(raw.get("is_active", True)),
    )


def to_brigade_page(data: Any, page: int, page_size: int, *, show_rates: bool) -> BrigadePage:
    return BrigadePage(
        items=[to_brigade(r, show_rates=show_rates) for r in _rows(data)],
        **page_meta(data, page, page_size),
    )


class BrigadeCreate(Body):
    name: str
    kind: BrigadeKindName | None = None
    specialization: str | None = None
    headcount: int | None = None
    rate: MoneyIn | None = None
    rate_unit: RateUnit | None = None
    note: str | None = None
    is_active: bool | None = None


class BrigadeUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"rate"})
    name: str | None = None
    kind: BrigadeKindName | None = None
    specialization: str | None = None
    headcount: int | None = None
    rate: MoneyIn | None = None
    rate_unit: RateUnit | None = None
    note: str | None = None
    is_active: bool | None = None


# --- запросы на категории ----------------------------------------------------------------------


class CategoryProposalIn(Body):
    name: str
    parent_id: str | None = None
    justification: str | None = None


def proposal_to_erp(body: CategoryProposalIn) -> dict[str, Any]:
    sent = body.sent()
    out: dict[str, Any] = {"proposed_name": sent["name"].strip()}
    if sent.get("parent_id"):
        out["parent"] = int(sent["parent_id"])
    if sent.get("justification"):
        out["justification"] = sent["justification"].strip()
    return out


# --- справочники --------------------------------------------------------------------------------


class ExchangeRateRow(Out):
    id: str
    currency: str
    rate_to_uzs: str
    rate_date: str
    source: Literal["CBU", "MANUAL"]


class ExchangeRatePage(PageOut):
    items: list[ExchangeRateRow]


def to_rate_page(data: Any, page: int, page_size: int) -> ExchangeRatePage:
    return ExchangeRatePage(
        items=[
            ExchangeRateRow(
                id=ident(r.get("id")),
                currency=text(r.get("currency")),
                rate_to_uzs=text(r.get("rate_to_uzs")),
                rate_date=text(r.get("rate_date")),
                source="MANUAL" if r.get("source") == "MANUAL" else "CBU",
            )
            for r in _rows(data)
        ],
        **page_meta(data, page, page_size),
    )


class HsCode(Out):
    id: str
    code: str
    name: str
    unit_name: str
    extra_unit_name: str
    level: Literal[2, 4, 6, 8, 10]
    valid_from: str | None
    valid_until: str | None
    is_active: bool
    source: str


class HsCodePage(PageOut):
    items: list[HsCode]


def to_hs(raw: Mapping[str, Any]) -> HsCode:
    level = raw.get("level")
    return HsCode(
        id=ident(raw.get("id")),
        code=text(raw.get("code")),
        name=text(raw.get("name")),
        unit_name=text(raw.get("unit_name")),
        extra_unit_name=text(raw.get("extra_unit_name")),
        level=level if level in (2, 4, 6, 8, 10) else 10,
        valid_from=raw.get("valid_from"),
        valid_until=raw.get("valid_until"),
        is_active=bool(raw.get("is_active", True)),
        source=text(raw.get("source")),
    )


def to_hs_page(data: Any, page: int, page_size: int) -> HsCodePage:
    return HsCodePage(items=[to_hs(r) for r in _rows(data)], **page_meta(data, page, page_size))


class HsCodeCreate(Body):
    code: str
    name: str
    unit_name: str | None = None
    extra_unit_name: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None


class HsCodeUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"valid_from", "valid_until"})
    name: str | None = None
    unit_name: str | None = None
    extra_unit_name: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None


class Manufacturer(Out):
    id: str
    name: str
    country_id: str | None
    country_name: str | None
    website: str
    is_active: bool


class ManufacturerPage(PageOut):
    items: list[Manufacturer]


def to_manufacturer(raw: Mapping[str, Any]) -> Manufacturer:
    return Manufacturer(
        id=ident(raw.get("id")),
        name=text(raw.get("name")),
        country_id=opt_ident(raw.get("country")),
        country_name=raw.get("country_name") or None,
        website=text(raw.get("website")),
        is_active=bool(raw.get("is_active", True)),
    )


def to_manufacturer_page(data: Any, page: int, page_size: int) -> ManufacturerPage:
    return ManufacturerPage(
        items=[to_manufacturer(r) for r in _rows(data)], **page_meta(data, page, page_size)
    )


class ManufacturerCreate(Body):
    name: str
    country_id: str | None = None
    website: str | None = None
    is_active: bool | None = None


class ManufacturerUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"country_id"})
    name: str | None = None
    country_id: str | None = None
    website: str | None = None
    is_active: bool | None = None


def manufacturer_to_erp(sent: dict[str, Any]) -> dict[str, Any]:
    out = dict(sent)
    if "country_id" in out:
        value = out.pop("country_id")
        out["country"] = int(value) if value is not None else None
    return out


class LookupCategory(Out):
    id: str
    name: str
    parent_id: str | None


class LookupCurrency(Out):
    code: str
    symbol: str


class Lookups(Out):
    units: list[Unit]
    categories: list[LookupCategory]
    currencies: list[LookupCurrency]
    countries: list[NamedRef]


# --- техдокументация ---------------------------------------------------------------------------


class TechDocDeal(Out):
    id: str
    number: str
    title: str
    client: str


class TechDoc(Out):
    id: str
    kind: TechDocKindName
    title: str
    original_name: str
    content_type: str
    size_bytes: int
    previewable: bool
    product: ProductRef | None
    deal: TechDocDeal | None
    uploaded_by: str | None
    created_at: str


class TechDocPage(PageOut):
    items: list[TechDoc]


def _tech_kind(value: Any) -> TechDocKindName:
    return value if value in ("tz", "drawing", "certificate", "pnr", "other") else "other"


def to_tech_doc(raw: Mapping[str, Any]) -> TechDoc:
    product = raw.get("product")
    deal = raw.get("deal")
    return TechDoc(
        id=ident(raw.get("id")),
        kind=_tech_kind(raw.get("kind")),
        title=text(raw.get("title")),
        original_name=text(raw.get("original_name")),
        content_type=text(raw.get("content_type")),
        size_bytes=int(raw.get("size_bytes") or 0),
        previewable=bool(raw.get("previewable")),
        product=(
            ProductRef(
                id=ident(product.get("id")),
                name=text(product.get("name")),
                sku=text(product.get("sku")),
            )
            if isinstance(product, Mapping)
            else None
        ),
        deal=(
            TechDocDeal(
                id=ident(deal.get("id")),
                number=deal_number(
                    {
                        "id": deal["id"],
                        "number": deal.get("number"),
                        "created_at": deal.get("created_at"),
                        "stage_code": deal.get("stage_code"),
                    }
                ),
                title=text(deal.get("title")),
                client=text(deal.get("client")),
            )
            if isinstance(deal, Mapping) and isinstance(deal.get("id"), int)
            else None
        ),
        uploaded_by=raw.get("uploaded_by"),
        created_at=text(raw.get("created_at")),
    )


def to_tech_page(data: Any, page: int, page_size: int) -> TechDocPage:
    return TechDocPage(
        items=[to_tech_doc(r) for r in _rows(data)], **page_meta(data, page, page_size)
    )
