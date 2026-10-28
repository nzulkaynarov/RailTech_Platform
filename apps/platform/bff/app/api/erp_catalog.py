"""Расчёт · Номенклатура и поставщики, бригады, запросы на категории и справочники (контракт: тег
`erp-catalog`, 0.25.0; D2-3).

BFF проксирует к ERP с токеном сотрудника (`catalog/items|suppliers|brigades`, `catalog/category-
requests`, `master-data/hs-codes`, `catalog/manufacturers`, `exchange-rates`) и проверяет раздел
каталога `erp.stock` (чтение — `read`, изменения — `full`). Права на операцию решает ERP
(`catalog.manage`, `supply.manage`). Закрытые поля режут оба: цену закупки в предложениях — без
поля `supplier_prices`, ставку бригады — без `cost_margin` и без раздела `erp.calc.services`; ERP
отдаёт `null`, BFF вырезает ещё раз (администратор ERP видит всё, а роль «Администратор» — нет)."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status

from app.clients.erp_company import ErpCompany
from app.deps import Authed, require
from app.rbac import allows
from app.schemas_company import (
    CategoryRequest,
    CategoryRequestList,
    RequestStatus,
    ident,
    opt_ident,
    text,
    to_category_request,
)
from app.schemas_erp_catalog import (
    Brigade,
    BrigadeCreate,
    BrigadePage,
    BrigadeUpdate,
    CategoryProposalIn,
    ExchangeRatePage,
    HsCode,
    HsCodeCreate,
    HsCodePage,
    HsCodeUpdate,
    ItemCreate,
    ItemDetail,
    ItemPage,
    ItemUpdate,
    LookupCategory,
    LookupCurrency,
    Lookups,
    Manufacturer,
    ManufacturerCreate,
    ManufacturerPage,
    ManufacturerUpdate,
    NamedRef,
    Offer,
    OfferUpdate,
    SupplierDetail,
    SupplierPage,
    Unit,
    item_to_erp,
    manufacturer_to_erp,
    proposal_to_erp,
    rows_of,
    to_brigade,
    to_brigade_page,
    to_hs,
    to_hs_page,
    to_item_detail,
    to_item_page,
    to_manufacturer,
    to_manufacturer_page,
    to_offer,
    to_rate_page,
    to_supplier_detail,
    to_supplier_page,
)

router = APIRouter(tags=["erp-catalog"])

Reader = Annotated[Authed, Depends(require("erp.stock", "read"))]
Writer = Annotated[Authed, Depends(require("erp.stock", "full"))]
ItemId = Annotated[str, Path(pattern=r"^[0-9]+$")]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]
Search = Annotated[str | None, Query(max_length=200)]
ItemKindQuery = Annotated[
    str | None,
    Query(pattern=r"^(stock|on_order|service_fixed|service_milestones|service_time)$"),
]


def _erp(authed: Authed) -> ErpCompany:
    return ErpCompany(authed.call)


def show_prices(authed: Authed) -> bool:
    """Цена закупки: поле `supplier_prices` хотя бы у одной роли сотрудника."""
    return "supplier_prices" in authed.fields


def show_rates(authed: Authed) -> bool:
    """Ставка бригады: `cost_margin` или зона услуг расчёта (гл. инженер)."""
    return "cost_margin" in authed.fields or allows(authed.access, "erp.calc.services", "read")


def _params(**values: Any) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v not in (None, "")}


# --- справочники для форм ---------------------------------------------------------------------


@router.get("/erp/catalog/lookups", response_model=Lookups, operation_id="getCatalogLookups")
async def get_lookups(authed: Reader) -> Lookups:
    erp = _erp(authed)
    units, categories, currencies, countries = await asyncio.gather(
        erp.pages("master-data/units/"),
        erp.pages("catalog/categories/"),
        erp.pages("master-data/currencies/"),
        erp.pages("master-data/countries/"),
    )
    return Lookups(
        units=[
            Unit(id=ident(u.get("id")), code=text(u.get("code")), name=text(u.get("name")))
            for u in units
        ],
        categories=[
            LookupCategory(
                id=ident(c.get("id")),
                name=text(c.get("name")),
                parent_id=opt_ident(c.get("parent")),
            )
            for c in categories
        ],
        currencies=[
            LookupCurrency(code=text(c.get("code")), symbol=text(c.get("symbol")))
            for c in currencies
        ],
        countries=[NamedRef(id=ident(c.get("id")), name=text(c.get("name"))) for c in countries],
    )


# --- позиции -----------------------------------------------------------------------------------


@router.get("/erp/catalog/items", response_model=ItemPage, operation_id="listCatalogItems")
async def list_items(
    authed: Reader,
    q: Search = None,
    kind: ItemKindQuery = None,
    category_id: Annotated[str | None, Query(pattern=r"^[0-9]+$")] = None,
    page: Page = 1,
    page_size: PageSize = 25,
) -> ItemPage:
    data = await _erp(authed).data(
        "GET",
        "catalog/items/",
        params=_params(q=q, kind=kind, category=category_id, page=page, page_size=page_size),
    )
    return to_item_page(data, page, page_size)


@router.post(
    "/erp/catalog/items",
    response_model=ItemDetail,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCatalogItem",
)
async def create_item(body: ItemCreate, authed: Writer) -> ItemDetail:
    raw = await _erp(authed).data("POST", "catalog/items/", json=item_to_erp(body.sent()))
    return to_item_detail(raw, show_prices=show_prices(authed))


@router.get("/erp/catalog/items/{id}", response_model=ItemDetail, operation_id="getCatalogItem")
async def get_item(id: ItemId, authed: Reader) -> ItemDetail:
    raw = await _erp(authed).data("GET", f"catalog/items/{id}/")
    return to_item_detail(raw, show_prices=show_prices(authed))


@router.patch(
    "/erp/catalog/items/{id}", response_model=ItemDetail, operation_id="updateCatalogItem"
)
async def update_item(id: ItemId, body: ItemUpdate, authed: Writer) -> ItemDetail:
    raw = await _erp(authed).data("PATCH", f"catalog/items/{id}/", json=item_to_erp(body.sent()))
    return to_item_detail(raw, show_prices=show_prices(authed))


# --- поставщики --------------------------------------------------------------------------------


@router.get(
    "/erp/catalog/suppliers", response_model=SupplierPage, operation_id="listCatalogSuppliers"
)
async def list_suppliers(
    authed: Reader, q: Search = None, page: Page = 1, page_size: PageSize = 25
) -> SupplierPage:
    data = await _erp(authed).data(
        "GET", "catalog/suppliers/", params=_params(q=q, page=page, page_size=page_size)
    )
    return to_supplier_page(data, page, page_size)


@router.get(
    "/erp/catalog/suppliers/{id}", response_model=SupplierDetail, operation_id="getCatalogSupplier"
)
async def get_supplier(id: ItemId, authed: Reader) -> SupplierDetail:
    raw = await _erp(authed).data("GET", f"catalog/suppliers/{id}/")
    return to_supplier_detail(raw, show_prices=show_prices(authed))


@router.patch(
    "/erp/catalog/suppliers/{id}/offers/{offer_id}",
    response_model=Offer,
    operation_id="updateSupplierOffer",
)
async def update_offer(id: ItemId, offer_id: ItemId, body: OfferUpdate, authed: Writer) -> Offer:
    raw = await _erp(authed).data(
        "PATCH", f"catalog/suppliers/{id}/offers/{offer_id}/", json=body.sent()
    )
    return to_offer(raw, show_prices=show_prices(authed))


# --- бригады -----------------------------------------------------------------------------------


@router.get("/erp/catalog/brigades", response_model=BrigadePage, operation_id="listBrigades")
async def list_brigades(
    authed: Reader,
    q: Search = None,
    kind: Annotated[str | None, Query(pattern=r"^(brigade|person|subcontractor)$")] = None,
    include_inactive: bool = False,
    page: Page = 1,
    page_size: PageSize = 25,
) -> BrigadePage:
    data = await _erp(authed).data(
        "GET",
        "catalog/brigades/",
        params=_params(
            q=q,
            kind=kind,
            include_inactive="1" if include_inactive else None,
            page=page,
            page_size=page_size,
        ),
    )
    return to_brigade_page(data, page, page_size, show_rates=show_rates(authed))


@router.post(
    "/erp/catalog/brigades",
    response_model=Brigade,
    status_code=status.HTTP_201_CREATED,
    operation_id="createBrigade",
)
async def create_brigade(body: BrigadeCreate, authed: Writer) -> Brigade:
    raw = await _erp(authed).data("POST", "catalog/brigades/", json=body.sent())
    return to_brigade(raw, show_rates=show_rates(authed))


@router.patch("/erp/catalog/brigades/{id}", response_model=Brigade, operation_id="updateBrigade")
async def update_brigade(id: ItemId, body: BrigadeUpdate, authed: Writer) -> Brigade:
    raw = await _erp(authed).data("PATCH", f"catalog/brigades/{id}/", json=body.sent())
    return to_brigade(raw, show_rates=show_rates(authed))


# --- запросы на новые категории ----------------------------------------------------------------


@router.get(
    "/erp/catalog/category-requests",
    response_model=CategoryRequestList,
    response_model_exclude_unset=True,
    operation_id="listCatalogCategoryRequests",
)
async def list_category_requests(
    authed: Reader, status_filter: Annotated[RequestStatus | None, Query(alias="status")] = None
) -> CategoryRequestList:
    params = {"status": status_filter.upper()} if status_filter else None
    rows = await _erp(authed).pages("catalog/category-requests/", params)
    return CategoryRequestList(items=[to_category_request(r) for r in rows])


@router.post(
    "/erp/catalog/category-requests",
    response_model=CategoryRequest,
    response_model_exclude_unset=True,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCatalogCategoryRequest",
)
async def create_category_request(body: CategoryProposalIn, authed: Writer) -> CategoryRequest:
    raw = await _erp(authed).data("POST", "catalog/category-requests/", json=proposal_to_erp(body))
    return to_category_request(raw)


# --- справочники: курсы, ТН ВЭД, производители ------------------------------------------------


@router.get(
    "/erp/catalog/exchange-rates",
    response_model=ExchangeRatePage,
    operation_id="listCatalogExchangeRates",
)
async def list_rates(
    authed: Reader,
    currency: Annotated[str | None, Query(pattern=r"^[A-Za-z]{3}$")] = None,
    page: Page = 1,
    page_size: PageSize = 25,
) -> ExchangeRatePage:
    data = await _erp(authed).data(
        "GET", "exchange-rates/", params=_params(currency=currency, page=page, page_size=page_size)
    )
    return to_rate_page(data, page, page_size)


@router.get("/erp/catalog/hs-codes", response_model=HsCodePage, operation_id="listHsCodes")
async def list_hs_codes(
    authed: Reader,
    q: Search = None,
    level: Annotated[int | None, Query()] = None,
    active: bool = False,
    page: Page = 1,
    page_size: PageSize = 25,
) -> HsCodePage:
    data = await _erp(authed).data(
        "GET",
        "master-data/hs-codes/",
        params=_params(
            q=q, level=level, active="1" if active else None, page=page, page_size=page_size
        ),
    )
    return to_hs_page(data, page, page_size)


@router.post(
    "/erp/catalog/hs-codes",
    response_model=HsCode,
    status_code=status.HTTP_201_CREATED,
    operation_id="createHsCode",
)
async def create_hs_code(body: HsCodeCreate, authed: Writer) -> HsCode:
    return to_hs(await _erp(authed).data("POST", "master-data/hs-codes/", json=body.sent()))


@router.patch("/erp/catalog/hs-codes/{id}", response_model=HsCode, operation_id="updateHsCode")
async def update_hs_code(id: ItemId, body: HsCodeUpdate, authed: Writer) -> HsCode:
    return to_hs(await _erp(authed).data("PATCH", f"master-data/hs-codes/{id}/", json=body.sent()))


@router.get(
    "/erp/catalog/manufacturers", response_model=ManufacturerPage, operation_id="listManufacturers"
)
async def list_manufacturers(
    authed: Reader,
    q: Search = None,
    include_inactive: bool = False,
    page: Page = 1,
    page_size: PageSize = 25,
) -> ManufacturerPage:
    data = await _erp(authed).data(
        "GET",
        "catalog/manufacturers/",
        params=_params(
            search=q,
            include_inactive="1" if include_inactive else None,
            page=page,
            page_size=page_size,
        ),
    )
    return to_manufacturer_page(data, page, page_size)


@router.post(
    "/erp/catalog/manufacturers",
    response_model=Manufacturer,
    status_code=status.HTTP_201_CREATED,
    operation_id="createManufacturer",
)
async def create_manufacturer(body: ManufacturerCreate, authed: Writer) -> Manufacturer:
    raw = await _erp(authed).data(
        "POST", "catalog/manufacturers/", json=manufacturer_to_erp(body.sent())
    )
    return to_manufacturer(raw)


@router.patch(
    "/erp/catalog/manufacturers/{id}",
    response_model=Manufacturer,
    operation_id="updateManufacturer",
)
async def update_manufacturer(id: ItemId, body: ManufacturerUpdate, authed: Writer) -> Manufacturer:
    raw = await _erp(authed).data(
        "PATCH", f"catalog/manufacturers/{id}/", json=manufacturer_to_erp(body.sent())
    )
    return to_manufacturer(raw)


__all__ = ["router", "rows_of"]
