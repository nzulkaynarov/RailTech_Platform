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

import re
from collections.abc import Mapping
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.feeds.numbers import deal_number
from app.schemas_company import Body, Patch, dec, ident, opt_ident, text
from app.schemas_dictionaries import LocalizedName

ItemKind = Literal["stock", "on_order", "service_fixed", "service_milestones", "service_time"]
BrigadeKindName = Literal["brigade", "person", "subcontractor"]
# Код вида документа из справочника видов ERP (`DocumentKind.code`): виды — данные, не
# перечисление в коде.
KIND_CODE = r"^[a-z0-9_-]{1,32}$"
TechDocKindName = Annotated[str, Field(pattern=KIND_CODE)]
_KIND_CODE = re.compile(KIND_CODE)
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
Validity = Literal["ok", "expiring", "expired"]
RateUnit = Literal["day", "hour"]
OfferSource = Literal["price_list", "rfq_reply", "manual"]
ProposalField = Literal[
    "name", "description", "category", "hs_code", "uom", "domain_type", "gost_drawing"
]
ImportMode = Literal["xlsx", "ai"]
# PART-3: очередь проверки партнёров; поля замечаний — перечень ERP (`catalog.models.reviews`)
ReviewKind = Literal["card", "changes"]
IssueField = Literal[
    "name",
    "description",
    "brand",
    "manufacturer_part_number",
    "gost_drawing",
    "category",
    "uom",
    "hs_code",
    "price",
    "valid_until",
    "other",
]
PriceVisibility = Literal["cabinet", "on_request"]
PriceSource = Literal["item", "partner", "company"]
_SOURCES = {"price_list", "rfq_reply", "manual"}
_PROPOSAL_FIELDS = {
    "name",
    "description",
    "category",
    "hs_code",
    "uom",
    "domain_type",
    "gost_drawing",
}
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
    delivery_basis: str | None
    lead_time: str
    source: OfferSource
    updated_at: str
    valid_from: str | None
    valid_until: str | None
    is_active: bool
    validity: Validity


def _source(value: Any) -> OfferSource:
    return value if value in _SOURCES else "manual"


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
        delivery_basis=raw.get("delivery_basis") or None,
        lead_time=text(raw.get("lead_time")),
        source=_source(raw.get("source")),
        updated_at=text(raw.get("updated_at")),
        valid_from=raw.get("valid_from"),
        valid_until=raw.get("valid_until"),
        is_active=bool(raw.get("is_active", True)),
        validity=validity if validity in ("ok", "expiring", "expired") else "ok",
    )


class ReviewInfo(Out):
    """Карточка ждёт решения (PART-3): кто прислал, когда и до какого срока ответить."""

    kind: ReviewKind
    partner: NamedRef | None
    submitted_at: str
    due_at: str
    overdue: bool


class CatalogPrice(Out):
    """Что покажет каталог клиенту: видимость цены, откуда она взята и цена-витрина."""

    visibility: PriceVisibility
    source: PriceSource
    price: Money | None


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
    proposals_count: int
    review: ReviewInfo | None = None
    completeness: int | None = None


class TechDocFields(Out):
    """Паспорт документа товара: вид, номер, орган, сроки, видимость клиенту (CAT-CARD-1)."""

    id: str
    title: str
    kind: TechDocKindName
    kind_name: str
    number: str
    issued_by: str
    issued_at: str | None
    valid_until: str | None
    is_expired: bool
    client_visible: bool
    review_state: Literal["approved", "pending", "rejected"]
    partner: str | None
    original_name: str
    size_bytes: int
    previewable: bool


class TechDocRef(TechDocFields):
    pass


class ItemImage(Out):
    id: str
    is_main: bool
    sort_order: int
    alt: str


class ItemOrigin(Out):
    own: NamedRef | None
    effective: NamedRef | None
    brand: NamedRef | None
    source: Literal["item", "brand", "none"]


class ItemWarranty(Out):
    months: int | None
    terms: str
    effective_months: int | None
    company_months: int | None
    source: Literal["item", "company", "none"]


class Proposal(Out):
    id: str
    field: ProposalField
    current: str
    proposed: str
    supplier: NamedRef | None
    created_at: str


class PublishState(Out):
    publishable: bool
    missing: list[str]


class Mxik(Out):
    """План 1.8: МХИК (ИКПУ) товара — код и что о нём сказал классификатор."""

    code: str
    name: str
    unit: str
    package: str


class MxikHit(Mxik):
    group: str


class MxikPage(Out):
    items: list[MxikHit]


class ItemDetail(Item):
    description: str
    gost_drawing: str
    hs_code: str
    mxik: Mxik | None = None
    manufacturer_part_number: str
    brand: str | None
    brand_id: str | None
    source_supplier: NamedRef | None
    offers: list[Offer]
    prices_visible: bool
    tech_docs: list[TechDocRef]
    images: list[ItemImage]
    origin: ItemOrigin
    warranty: ItemWarranty
    proposals: list[Proposal]
    publish: PublishState
    catalog_price: CatalogPrice


def to_proposal(raw: Mapping[str, Any]) -> Proposal | None:
    field = raw.get("field")
    if field not in _PROPOSAL_FIELDS or raw.get("id") is None:
        return None
    return Proposal(
        id=ident(raw["id"]),
        field=field,
        current=text(raw.get("current")),
        proposed=text(raw.get("proposed")),
        supplier=_named(raw.get("supplier")),
        created_at=text(raw.get("created_at")),
    )


class ItemPage(PageOut):
    items: list[Item]


def _kind(value: Any) -> ItemKind:
    return value if value in _KINDS else "on_order"


def _unit(raw: Any) -> Unit | None:
    if not isinstance(raw, Mapping) or raw.get("id") is None:
        return None
    return Unit(id=ident(raw["id"]), code=text(raw.get("code")), name=text(raw.get("name")))


def _review(raw: Any) -> ReviewInfo | None:
    if not isinstance(raw, Mapping) or raw.get("kind") not in ("card", "changes"):
        return None
    return ReviewInfo(
        kind=raw["kind"],
        partner=_named(raw.get("partner")),
        submitted_at=text(raw.get("submitted_at")),
        due_at=text(raw.get("due_at")),
        overdue=bool(raw.get("overdue")),
    )


def _completeness(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _catalog_price(raw: Any) -> CatalogPrice:
    raw = _mapping(raw)
    visibility = raw.get("visibility")
    source = raw.get("source")
    return CatalogPrice(
        visibility="cabinet" if visibility == "cabinet" else "on_request",
        source=source if source in ("item", "partner") else "company",
        price=_money(raw.get("price")),
    )


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
        "proposals_count": int(raw.get("proposals_count") or 0),
        "review": _review(raw.get("review")),
        "completeness": _completeness(raw.get("completeness")),
    }


def to_item_detail(raw: Mapping[str, Any], *, show_prices: bool) -> ItemDetail:
    docs = [
        TechDocRef(**tech_doc_fields(d))
        for d in raw.get("tech_docs") or []
        if isinstance(d, Mapping)
    ]
    origin = _mapping(raw.get("origin"))
    warranty = _mapping(raw.get("warranty"))
    return ItemDetail(
        **to_item(raw),
        description=text(raw.get("description")),
        gost_drawing=text(raw.get("gost_drawing")),
        hs_code=text(raw.get("hs_code")),
        **_mxik(raw.get("mxik")),
        manufacturer_part_number=text(raw.get("manufacturer_part_number")),
        brand=raw.get("brand"),
        brand_id=opt_ident(raw.get("brand_id")),
        source_supplier=_named(raw.get("source_supplier")),
        offers=[
            to_offer(o, show_prices=show_prices)
            for o in raw.get("offers") or []
            if isinstance(o, Mapping)
        ],
        prices_visible=show_prices and bool(raw.get("prices_visible")),
        tech_docs=docs,
        images=[
            to_image(i) for i in raw.get("images") or [] if isinstance(i, Mapping) and i.get("id")
        ],
        origin=ItemOrigin(
            own=_named(origin.get("own")),
            effective=_named(origin.get("effective")),
            brand=_named(origin.get("brand")),
            source=origin.get("source") if origin.get("source") in ("item", "brand") else "none",
        ),
        warranty=ItemWarranty(
            months=_months(warranty.get("months")),
            terms=text(warranty.get("terms")),
            effective_months=_months(warranty.get("effective_months")),
            company_months=_months(warranty.get("company_months")),
            source=warranty.get("source")
            if warranty.get("source") in ("item", "company")
            else "none",
        ),
        proposals=[
            p
            for p in (to_proposal(r) for r in raw.get("proposals") or [] if isinstance(r, Mapping))
            if p is not None
        ],
        publish=PublishState(
            publishable=bool((raw.get("publish") or {}).get("publishable")),
            missing=[str(m) for m in (raw.get("publish") or {}).get("missing") or []],
        ),
        catalog_price=_catalog_price(raw.get("catalog_price")),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def to_image(raw: Mapping[str, Any]) -> ItemImage:
    return ItemImage(
        id=ident(raw.get("id")),
        is_main=bool(raw.get("is_main")),
        sort_order=int(raw.get("sort_order") or 0),
        alt=text(raw.get("alt")),
    )


def _months(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


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
    country_of_origin_id: str | None = Field(default=None, pattern=r"^[0-9]+$")
    warranty_months: int | None = Field(default=None, ge=0, le=600)
    warranty_terms: str | None = Field(default=None, max_length=5000)


class ItemUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset(
        {
            "unit_id",
            "category_id",
            "vat_rate",
            "brand_id",
            "country_of_origin_id",
            "warranty_months",
        }
    )
    name: str | None = None
    kind: ItemKind | None = None
    description: str | None = None
    unit_id: str | None = None
    category_id: str | None = None
    vat_rate: str | None = None
    brand_id: str | None = Field(default=None, pattern=r"^[0-9]+$")
    manufacturer_part_number: str | None = Field(default=None, max_length=120)
    hs_code: str | None = Field(
        default=None, pattern=r"^([0-9]{2}|[0-9]{4}|[0-9]{6}|[0-9]{8}|[0-9]{10})?$"
    )
    country_of_origin_id: str | None = Field(default=None, pattern=r"^[0-9]+$")
    warranty_months: int | None = Field(default=None, ge=0, le=600)
    warranty_terms: str | None = Field(default=None, max_length=5000)
    # План 1.8: МХИК из классификатора (код, название, единица, упаковка) или вручную (только код)
    mxik_code: str | None = Field(default=None, pattern=r"^([0-9]{17})?$")
    mxik_name: str | None = Field(default=None, max_length=500)
    mxik_unit: str | None = Field(default=None, max_length=100)
    mxik_package: str | None = Field(default=None, max_length=200)


class ReturnIssue(Body):
    field: IssueField
    comment: str = Field(min_length=1, max_length=500)


class ItemReturn(Body):
    """Возврат карточки партнёру: нужна причина — общий комментарий или замечание по полю."""

    reason: str | None = Field(default=None, max_length=2000)
    issues: list[ReturnIssue] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def _has_reason(self) -> Self:
        if not (self.reason or "").strip() and not self.issues:
            raise ValueError("укажите причину возврата")
        return self


class ItemImageUpdate(Patch):
    is_main: Literal[True] | None = None
    sort_order: int | None = Field(default=None, ge=0)
    alt_text: str | None = Field(default=None, max_length=255)


def _mxik(raw: Any) -> dict[str, Any]:
    """`mxik` карточки ERP → поле контракта; нет кода — `null` (значение по умолчанию)."""
    if not isinstance(raw, dict) or not raw.get("code"):
        return {}
    return {
        "mxik": Mxik(
            code=str(raw["code"]),
            name=text(raw.get("name")),
            unit=text(raw.get("unit")),
            package=text(raw.get("package")),
        )
    }


def to_mxik_page(raw: Any) -> MxikPage:
    rows = raw.get("results") if isinstance(raw, dict) else None
    return MxikPage(
        items=[
            MxikHit(
                code=str(row.get("code") or ""),
                name=text(row.get("name")),
                group=text(row.get("group")),
                unit=text(row.get("unit")),
                package=text(row.get("package")),
            )
            for row in rows or []
            if isinstance(row, dict) and row.get("code")
        ]
    )


def item_to_erp(sent: dict[str, Any]) -> dict[str, Any]:
    out = dict(sent)
    for key in ("unit_id", "category_id", "brand_id", "country_of_origin_id"):
        if key in out and out[key] is not None:
            out[key] = int(out[key])
    return out


# --- поставщики ---------------------------------------------------------------------------------


class SupplierRow(Out):
    id: str
    name: str
    tin: str
    registration_number: str
    country: str | None
    country_id: str | None
    currency: str | None
    is_manufacturer: bool
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
    brands: list[NamedRef]
    manufactured_brands: list[NamedRef]


class SupplierPage(PageOut):
    items: list[SupplierRow]


def to_supplier(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": ident(raw.get("id")),
        "name": text(raw.get("name")),
        "tin": text(raw.get("tin")),
        "registration_number": text(raw.get("registration_number")),
        "country": raw.get("country"),
        "country_id": opt_ident(raw.get("country_id")),
        "currency": raw.get("currency") or None,
        "is_manufacturer": bool(raw.get("is_manufacturer")),
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
        brands=_named_list(raw.get("brands")),
        manufactured_brands=_named_list(raw.get("manufactured_brands")),
    )


def _named_list(raw: Any) -> list[NamedRef]:
    return [n for n in (_named(r) for r in raw or []) if n is not None]


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
    delivery_basis: str | None = Field(default=None, max_length=10)
    lead_time: str | None = Field(default=None, max_length=100)
    supplier_sku: str | None = Field(default=None, max_length=100)
    source: OfferSource | None = None


class OfferCreate(Body):
    product_id: str = Field(pattern=r"^[0-9]+$")
    price: MoneyIn
    delivery_basis: str | None = Field(default=None, max_length=10)
    min_order_qty: int | None = Field(default=None, ge=1)
    quota_qty: int | None = Field(default=None, ge=0)
    in_stock_lead_days: int | None = Field(default=None, ge=0)
    order_lead_days: int | None = Field(default=None, ge=0)
    lead_time: str | None = Field(default=None, max_length=100)
    supplier_sku: str | None = Field(default=None, max_length=100)
    valid_from: str | None = None
    valid_until: str | None = None
    source: OfferSource | None = None


def offer_create_to_erp(sent: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in sent.items() if v is not None}
    out["product_id"] = int(out["product_id"])
    return out


class OfferHistoryRow(Out):
    at: str
    price: Money | None
    valid_from: str | None
    valid_until: str | None
    delivery_basis: str | None
    source: OfferSource
    by: str | None


class OfferHistory(Out):
    items: list[OfferHistoryRow]


def to_offer_history(data: Any, *, show_prices: bool) -> OfferHistory:
    rows = data if isinstance(data, list) else []
    return OfferHistory(
        items=[
            OfferHistoryRow(
                at=text(r.get("at")),
                price=_money(r.get("price")) if show_prices else None,
                valid_from=r.get("valid_from"),
                valid_until=r.get("valid_until"),
                delivery_basis=r.get("delivery_basis") or None,
                source=_source(r.get("source")),
                by=r.get("by") or None,
            )
            for r in rows
            if isinstance(r, Mapping)
        ]
    )


class SupplierCreate(Body):
    name: str = Field(min_length=1, max_length=255)
    country_id: str | None = Field(default=None, pattern=r"^[0-9]+$")
    tin: str | None = Field(default=None, pattern=r"^([0-9]{9})?$")
    registration_number: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, max_length=3)
    contact_person: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=254)
    website: str | None = Field(default=None, max_length=255)
    is_manufacturer: bool | None = None


class SupplierUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"country_id", "currency"})
    name: str | None = Field(default=None, min_length=1, max_length=255)
    country_id: str | None = Field(default=None, pattern=r"^[0-9]+$")
    tin: str | None = Field(default=None, pattern=r"^([0-9]{9})?$")
    registration_number: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, max_length=3)
    contact_person: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=254)
    website: str | None = Field(default=None, max_length=255)
    is_manufacturer: bool | None = None


def supplier_to_erp(sent: dict[str, Any]) -> dict[str, Any]:
    out = dict(sent)
    if out.get("country_id") is not None:
        out["country_id"] = int(out["country_id"])
    return out


# --- загрузка прайса (CAT-1) --------------------------------------------------------------------


class PriceImportJob(Out):
    job_id: str
    mode: ImportMode


class PriceImportApplyIn(Body):
    supplier_id: str = Field(pattern=r"^[0-9]+$")
    rows_token: str = Field(pattern=r"^[0-9a-f]{32}$")
    valid_from: str | None = None
    valid_until: str | None = None


class RowNote(Out):
    row: int
    code: str
    value: str


class ImportProposal(Out):
    row: int
    product_id: str
    product_name: str
    field: ProposalField
    current: str
    proposed: str


class PriceImportReport(Out):
    checked: bool
    items_created: int
    items_matched: int
    offers_created: int
    offers_updated: int
    proposal_count: int
    proposals: list[ImportProposal]
    error_count: int
    errors: list[RowNote]
    warning_count: int
    warnings: list[RowNote]
    rows_truncated: int
    unpublishable: int
    rows_token: str | None
    ai_used: bool | None


class PriceImportStatus(Out):
    state: Literal["running", "done", "failed"]
    report: PriceImportReport | None
    error: str | None


def _notes(raw: Any) -> list[RowNote]:
    out = []
    for r in raw or []:
        if not isinstance(r, Mapping):
            continue
        code, _, value = text(r.get("message")).partition(":")
        out.append(RowNote(row=int(r.get("row") or 0), code=code or "ROW_FAILED", value=value))
    return out


def _count(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    return value if isinstance(value, int) and value > 0 else 0


def to_import_report(raw: Mapping[str, Any]) -> PriceImportReport:
    proposals = [
        ImportProposal(
            row=int(p.get("row") or 0),
            product_id=ident(p.get("product_id")),
            product_name=text(p.get("product_name")),
            field=p["field"],
            current=text(p.get("current")),
            proposed=text(p.get("proposed")),
        )
        for p in raw.get("proposals") or []
        if isinstance(p, Mapping) and p.get("field") in _PROPOSAL_FIELDS
    ]
    ai_used = raw.get("ai_used")
    token = raw.get("rows_token")
    return PriceImportReport(
        checked=bool(raw.get("dry_run")),
        items_created=_count(raw, "created"),
        items_matched=_count(raw, "updated"),
        offers_created=_count(raw, "offers_created"),
        offers_updated=_count(raw, "offers_updated"),
        proposal_count=_count(raw, "proposal_count"),
        proposals=proposals,
        error_count=_count(raw, "error_count"),
        errors=_notes(raw.get("errors")),
        warning_count=_count(raw, "warning_count"),
        warnings=_notes(raw.get("warnings")),
        rows_truncated=_count(raw, "rows_truncated"),
        unpublishable=_count(raw, "unpublishable"),
        rows_token=token if isinstance(token, str) else None,
        ai_used=ai_used if isinstance(ai_used, bool) else None,
    )


def to_import_status(data: Any) -> PriceImportStatus:
    """Ответ ERP `import-status` / `ai-status` → состояние загрузки.

    Сбой воркера или файла — `failed` с кодом."""
    if not isinstance(data, Mapping):
        return PriceImportStatus(state="failed", report=None, error="IMPORT_FAILED")
    result = data.get("result")
    if not isinstance(result, Mapping):
        state = text(data.get("status")).upper()
        if state in ("FAILURE", "REVOKED"):
            return PriceImportStatus(state="failed", report=None, error="IMPORT_FAILED")
        return PriceImportStatus(state="running", report=None, error=None)
    status = result.get("status")
    if status in ("error", "failed"):
        message = text(result.get("message"))
        code = (
            message if message.replace("_", "").isalnum() and message.isupper() else "IMPORT_FAILED"
        )
        return PriceImportStatus(state="failed", report=None, error=code)
    return PriceImportStatus(state="done", report=to_import_report(result), error=None)


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
    company_id: str | None


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
        company_id=opt_ident(raw.get("company")),
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
    company_id: str | None = Field(default=None, pattern=r"^[0-9]+$")


class ManufacturerUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"country_id", "company_id"})
    name: str | None = None
    country_id: str | None = None
    website: str | None = None
    is_active: bool | None = None
    company_id: str | None = Field(default=None, pattern=r"^[0-9]+$")


def manufacturer_to_erp(sent: dict[str, Any]) -> dict[str, Any]:
    out = dict(sent)
    for ours, erp in (("country_id", "country"), ("company_id", "company")):
        if ours in out:
            value = out.pop(ours)
            out[erp] = int(value) if value is not None else None
    return out


class LookupCategory(Out):
    id: str
    name: str
    parent_id: str | None


class LookupCurrency(Out):
    code: str
    symbol: str


class DeliveryBasisRef(Out):
    code: str
    name: str


class DocumentKindRef(Out):
    code: TechDocKindName
    name: str
    has_validity: bool
    client_visible_default: bool


class CountryRef(NamedRef):
    #: Название на языке интерфейса выбирает экран
    names: LocalizedName


class Lookups(Out):
    units: list[Unit]
    categories: list[LookupCategory]
    currencies: list[LookupCurrency]
    countries: list[CountryRef]
    delivery_bases: list[DeliveryBasisRef]
    document_kinds: list[DocumentKindRef]


# --- техдокументация ---------------------------------------------------------------------------


class TechDocDeal(Out):
    id: str
    number: str
    title: str
    client: str


class TechDoc(TechDocFields):
    content_type: str
    product: ProductRef | None
    deal: TechDocDeal | None
    uploaded_by: str | None
    created_at: str


class TechDocUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"issued_at", "valid_until"})
    kind: TechDocKindName | None = None
    title: str | None = Field(default=None, max_length=255)
    number: str | None = Field(default=None, max_length=100)
    issued_by: str | None = Field(default=None, max_length=255)
    issued_at: str | None = Field(default=None, pattern=DATE_PATTERN)
    valid_until: str | None = Field(default=None, pattern=DATE_PATTERN)
    client_visible: bool | None = None


class TechDocReview(Patch):
    """Решение по документу партнёра (FX-2): `approve` или `reject`."""

    decision: Literal["approve", "reject"]
    client_visible: bool | None = None


class TechDocPage(PageOut):
    items: list[TechDoc]


def _tech_kind(value: Any) -> str:
    return value if isinstance(value, str) and _KIND_CODE.match(value) else "other"


def tech_doc_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    kind = _tech_kind(raw.get("kind"))
    state = raw.get("review_state")
    return {
        "id": ident(raw.get("id")),
        "title": text(raw.get("title")),
        "kind": kind,
        "kind_name": text(raw.get("kind_name")) or kind,
        "number": text(raw.get("number")),
        "issued_by": text(raw.get("issued_by")),
        "issued_at": raw.get("issued_at"),
        "valid_until": raw.get("valid_until"),
        "is_expired": bool(raw.get("is_expired")),
        "client_visible": bool(raw.get("client_visible")),
        "review_state": state if state in ("approved", "pending", "rejected") else "approved",
        "partner": text(raw.get("partner")) or None,
        "original_name": text(raw.get("original_name")),
        "size_bytes": int(raw.get("size_bytes") or 0),
        "previewable": bool(raw.get("previewable")),
    }


def to_tech_doc(raw: Mapping[str, Any]) -> TechDoc:
    product = raw.get("product")
    deal = raw.get("deal")
    return TechDoc(
        **tech_doc_fields(raw),
        content_type=text(raw.get("content_type")),
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
