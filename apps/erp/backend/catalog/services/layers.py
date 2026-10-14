"""Два слоя каталога (M1-ERP-07; ORCHESTRATOR §3.5 «клиент видит только опубликованный слой»).

Эталон — Odoo `product.template` (опубликованное: `website_published`, `list_price`, описание для
витрины; внутреннее: `standard_price`, `seller_ids` поставщиков) и ERPNext Item (show in website,
наличие на витрине — статусом). Карточка одна, слоёв два:

* **опубликованный** — что видит клиент: имя, описание, характеристики, единица, вид, политика
  исполнения услуги, цена-витрина или «по запросу», наличие статусом, срок для клиента, публичные
  фото и документы;
* **внутренний** — всё остальное: поставщики и их цены, артикулы поставщиков, остатки и сроки
  поставщиков, ТН ВЭД, внутренние заметки, провенанс и спрос, полнота, статус.

`published_projection` — ЕДИНСТВЕННАЯ функция, через которую карточка уходит наружу: каталог для
не-сотрудника во внутреннем API, будущий портал (`/api/portal/v1/catalog`, M2-ERP-01), поиск по
каталогу интеграции и `erp-mcp` (режим `lead`, M3). Позиция КП в документах клиенту (публичная
страница, PDF) ссылается на карточку через `client_line_reference` — тот же опубликованный слой,
урезанный до имени. Набор полей проекции = схема `CatalogItem` портального контракта
(`packages/contracts/openapi/erp-portal.yaml`); негативные тесты — `catalog/tests/test_layers.py`.
"""

from __future__ import annotations

from django.utils import timezone

#: Поля проекции в режиме `client` — ровно свойства `CatalogItem` портального контракта.
PUBLISHED_FIELDS = (
    "id",
    "kind",
    "name",
    "description",
    "unit",
    "category",
    "fulfillment_policy",
    "price",
    "availability",
    "lead_time_days",
    "images",
    "documents",
    "attributes",
)
#: Коммерческие поля опубликованного слоя: только клиенту в кабинете и только при видимости `cabinet`.
COMMERCIAL_FIELDS = ("price", "availability", "lead_time_days")
#: Режим `lead` (бот лиду, поиск интеграции `mode=lead`) — без цен, наличия и сроков (DECISIONS 2026-10-13).
LEAD_FIELDS = tuple(field for field in PUBLISHED_FIELDS if field not in COMMERCIAL_FIELDS)

#: Внутренний слой — поля и связи, которые НИКОГДА не уходят клиенту (по ним держат негативные тесты).
INTERNAL_FIELDS = frozenset(
    {
        "offers",
        "supplier",
        "supplier_data",
        "supplier_sku",
        "base_price",
        "base_price_currency",
        "stock_quantity",
        "stock_status",
        "in_stock_lead_time_days",
        "order_lead_time_days",
        "delivery_lead_time",
        "min_order_qty",
        "internal_notes",
        "owner_company",
        "owner_company_data",
        "source_deal",
        "demand_count",
        "last_requested_at",
        "hs_code",
        "completeness",
        "status",
        "status_code",
    }
)

#: Статус наличия поставщика → наличие, как его видит клиент (BUSINESS §10.1: статус, без количеств).
_AVAILABILITY_BY_STOCK_STATUS = {
    "IN_STOCK": "in_stock",
    "EXPECTED": "expected",
    "ON_ORDER": "on_order",
    "OUT_OF_STOCK": "on_order",
}
_AVAILABILITY_RANK = {"in_stock": 0, "expected": 1, "on_order": 2}


def client_visible_products():
    """Карточки, которые вообще можно показать клиенту: опубликованные и с выбранным видом.

    Связи — под проекцию: без N+1 на странице каталога.
    """
    from ..models import Product

    return (
        Product.objects.filter(status__code="PUBLISHED", domain_type__isnull=False)
        .select_related("domain_type", "category", "uom", "list_price_currency")
        .prefetch_related("images", "documents", "offers__stock_status")
    )


def _absolute(url: str | None, request) -> str | None:
    if not url:
        return None
    if request is not None and not url.startswith("http"):
        return request.build_absolute_uri(url)
    return url


def _public_images(product, request) -> list[str]:
    urls = []
    for image in product.images.all():
        if not image.is_public:
            continue
        url = _absolute(image.image.url if image.image else image.image_url, request)
        if url:
            urls.append(url)
    return urls


def _public_documents(product, request) -> list[dict]:
    rows = []
    for document in product.documents.all():
        if not document.is_public:
            continue
        url = _absolute(document.file.url if document.file else document.file_url, request)
        if url:
            rows.append({"name": document.name, "url": url})
    return rows


def _attributes(product) -> list[dict]:
    specs = product.specifications if isinstance(product.specifications, dict) else {}
    return [
        {"name": str(name), "value": str(value)}
        for name, value in specs.items()
        if value is not None and str(value).strip() and str(name).strip()
    ]


def _availability(product) -> str | None:
    """Лучший статус среди действующих предложений поставщиков — только как статус, без количеств
    и сроков поставщика. У услуги наличия нет. Нет предложений — «под заказ»."""
    from ..models import ProductKind

    if product.kind != ProductKind.SERVICE:
        today = timezone.localdate()
        statuses = [
            _AVAILABILITY_BY_STOCK_STATUS.get(getattr(offer.stock_status, "code", None), "on_order")
            for offer in product.offers.all()
            if offer.is_active and not (offer.valid_until and offer.valid_until < today)
        ]
        return min(statuses, key=_AVAILABILITY_RANK.__getitem__) if statuses else "on_order"
    return None


def _price(product) -> dict | None:
    if product.list_price is None or product.list_price_currency_id is None:
        return None
    return {"amount": f"{product.list_price:.2f}", "currency": product.list_price_currency.code}


def published_projection(product, *, mode: str = "client", request=None) -> dict:
    """Карточка глазами клиента — опубликованный слой и НИЧЕГО больше.

    `mode="client"` — клиент в кабинете: при видимости `cabinet` с ценой, наличием и сроком, при
    `on_request` эти три поля `null` («по запросу»). `mode="lead"` — лид и бот вне кабинета: без
    цен, наличия и сроков вовсе. Публикацию карточки проверяет вызывающий (`client_visible_products`);
    функция только проецирует.
    """
    from ..models import CatalogVisibility

    if mode not in ("client", "lead"):
        raise ValueError(f"unknown projection mode: {mode!r}")
    data = {
        "id": product.pk,
        "kind": str(product.kind) if product.kind else None,
        "name": product.name,
        "description": product.description or "",
        "unit": product.uom.name if product.uom_id else "",
        "category": product.category.name if product.category_id else None,
        "fulfillment_policy": product.fulfillment_policy or None,
        "images": _public_images(product, request),
        "documents": _public_documents(product, request),
        "attributes": _attributes(product),
    }
    if mode == "lead":
        return data
    on_cabinet = product.visibility == CatalogVisibility.CABINET
    data["price"] = _price(product) if on_cabinet else None
    data["availability"] = _availability(product) if on_cabinet else None
    data["lead_time_days"] = product.client_lead_time_days if on_cabinet else None
    return {field: data[field] for field in PUBLISHED_FIELDS}


def client_line_reference(product) -> dict | None:
    """Ссылка позиции КП/документа клиенту на карточку — опубликованный слой, урезанный до имени.
    Модель целиком в контекст шаблона клиента не уходит: шаблон не дотянется до поставщиков."""
    if product is None:
        return None
    return {"id": product.pk, "name": product.name}
