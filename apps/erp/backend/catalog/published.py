"""Опубликованный слой каталога — ЕДИНСТВЕННЫЙ путь карточки наружу (M1-ERP-07).

Паттерн «один каталог, два слоя» (BUSINESS §8.3, §10.1): клиент в кабинете, бот и CRM видят
только опубликованный слой — название, описание, характеристики, единицу, фото, цену-витрину
или «по запросу», наличие как статус и срок. Внутренний слой — поставщики, закупочные цены,
артикулы поставщиков, остатки количеством, себестоимость, спрос, ТН ВЭД — не покидает бэк-офис.

Как это гарантируется: проекция собирается БЕЛЫМ СПИСКОМ полей (`project()`), а не
вычёркиванием лишнего из сериализатора бэк-офиса — новое поле карточки наружу само не утечёт.
Портальный (`/api/portal/v1/catalog`, M2-ERP-01), интеграционный (`/catalog/search`, M3-ERP-01)
и MCP-эндпоинты (`search_catalog`, M3-ERP-03) отдают каталог только через этот модуль.

Форма ответа — `CatalogItem` из `packages/contracts/openapi/erp-portal.yaml`; в режиме `lead`
(контракт MCP `prospect`) без `price`, `availability` и `lead_time_days`.
"""

from __future__ import annotations

from urllib.parse import urljoin

from django.conf import settings
from django.db.models import Prefetch
from django.utils import timezone

from .constants import MODE_CLIENT, MODE_LEAD, PROJECTION_MODES, PriceVisibility
from .policy import CatalogPolicy, effective_price_visibility, load_policies, policy_for

#: Наличие как статус (контракт портала `Availability`).
IN_STOCK = "in_stock"
ON_ORDER = "on_order"
EXPECTED = "expected"

#: Ключи `CatalogItem` (контракт портала). Проекция не отдаёт ничего вне этого набора —
#: сторож-тест сверяет его с контрактом.
CATALOG_ITEM_KEYS = frozenset(
    {
        "id",
        "kind",
        "name",
        "description",
        "unit",
        "category",
        "category_id",
        "price",
        "availability",
        "lead_time_days",
        "images",
        "attributes",
    }
)
CLIENT_ONLY_KEYS = frozenset({"price", "availability", "lead_time_days"})


def published_products():
    """Опубликованные карточки со всем, что читает проекция, — без запросов на строку."""
    from .models import Product, SupplierOffer

    return (
        Product.objects.filter(status__code="PUBLISHED")
        .select_related("domain_type", "category", "uom", "list_price_currency")
        .prefetch_related(
            "images",
            Prefetch(
                "offers",
                queryset=SupplierOffer.objects.filter(is_active=True).select_related("stock_status"),
                to_attr="active_offers",
            ),
        )
    )


def _current_offers(product) -> list:
    """Действующие предложения поставщиков: активные и в окне действия цены."""
    offers = getattr(product, "active_offers", None)
    if offers is None:
        offers = [offer for offer in product.offers.all() if offer.is_active]
    today = timezone.localdate()
    return [
        offer
        for offer in offers
        if not (offer.valid_from and offer.valid_from > today) and not (offer.valid_until and offer.valid_until < today)
    ]


def _min_positive(values) -> int | None:
    positive = [value for value in values if value]
    return min(positive) if positive else None


def availability(product) -> tuple[str, int | None]:
    """Наличие как статус и срок в днях — из внутреннего слоя, без количества и поставщика.

    Уровень 1 из BUSINESS §10.2: остаток — число на предложении поставщика. Склад с движениями
    (M4-ERP-01) заменит источник, не форму ответа.

    - есть остаток или статус «в наличии» хотя бы у одного действующего предложения → `in_stock`,
      срок — самый короткий срок отгрузки со склада (0 — «сегодня»);
    - статус «ожидается» → `expected`, срок — самый короткий срок под заказ;
    - иначе (и для услуг, и без предложений) → `on_order`, срок — самый короткий срок под заказ
      или `null` («срок уточним»).
    """
    offers = _current_offers(product)
    stocked = [
        offer for offer in offers if offer.stock_quantity > 0 or getattr(offer.stock_status, "code", None) == "IN_STOCK"
    ]
    if stocked:
        return IN_STOCK, min(offer.in_stock_lead_time_days for offer in stocked)
    order_lead = _min_positive(offer.order_lead_time_days for offer in offers)
    if any(getattr(offer.stock_status, "code", None) == "EXPECTED" for offer in offers):
        return EXPECTED, order_lead
    return ON_ORDER, order_lead


def _absolute(url: str, request) -> str:
    """Относительную ссылку на фото делает абсолютной.

    База — `CABINET_URL` (как в письмах и событиях): клиент видит фото на домене Cabinet, а заголовок `Host`
    запроса (в туннеле на телефон — подменённый) на адрес не влияет (FIX-64, N-4). Без настройки — прежнее
    поведение: от адреса запроса; без запроса — ссылка как есть."""
    if request is None or not url or url.startswith("http"):
        return url
    base = (getattr(settings, "CABINET_URL", "") or "").strip()
    if base:
        return urljoin(base.rstrip("/") + "/", url.lstrip("/"))
    return request.build_absolute_uri(url)


def _image_urls(product, request) -> list[str]:
    urls = []
    for image in product.images.all():  # порядок модели: главное фото первым
        url = image.image.url if image.image else image.image_url
        if url:
            urls.append(_absolute(url, request))
    return urls


def _attributes(product) -> list[dict]:
    specifications = product.specifications if isinstance(product.specifications, dict) else {}
    return [
        {"name": str(name), "value": str(value)}
        for name, value in specifications.items()
        if str(name).strip() and value not in (None, "")
    ]


def _price(product, policy: CatalogPolicy) -> dict | None:
    """Цена-витрина клиенту или `None` — «по запросу» (контракт: `price: Money | null`)."""
    if effective_price_visibility(product, policy) != PriceVisibility.CABINET:
        return None
    if product.list_price is None or product.list_price_currency_id is None:
        return None
    return {"amount": f"{product.list_price:.2f}", "currency": product.list_price_currency.code}


def project(product, *, mode: str, policy: CatalogPolicy | None = None, request=None) -> dict:
    """Карточка в опубликованном слое — `CatalogItem` контракта портала.

    `mode="client"` — клиент в кабинете и бот в сервисном режиме: + цена (только при политике
    `cabinet`, иначе `null` — «по запросу»), наличие как статус, срок. `mode="lead"` — лид и бот
    вне кабинета: перечень без цены, наличия и срока (решение владельца 2026-10-13).
    """
    if mode not in PROJECTION_MODES:
        raise ValueError(f"unknown projection mode: {mode!r}")
    item = {
        "id": product.pk,
        "kind": "service" if product.is_service else "goods",
        "name": product.name,
        "description": product.description or "",
        "unit": product.uom.name if product.uom_id else "",
        "category": product.category.name if product.category_id else None,
        "category_id": product.category_id,
        "images": _image_urls(product, request),
        "attributes": _attributes(product),
    }
    if mode == MODE_CLIENT:
        policy = policy if policy is not None else policy_for(product.owner_company_id)
        status, lead_time_days = availability(product)
        item["price"] = _price(product, policy)
        item["availability"] = status
        item["lead_time_days"] = lead_time_days
    return item


def project_many(products, *, mode: str, request=None) -> list[dict]:
    """Проекция пачки: политики компаний — одним запросом (для списков портала и поиска)."""
    products = list(products)
    policies = load_policies(product.owner_company_id for product in products) if mode != MODE_LEAD else {}
    return [
        project(product, mode=mode, policy=policies.get(product.owner_company_id, CatalogPolicy()), request=request)
        for product in products
    ]
