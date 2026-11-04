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

Карточка товара (CAT-CARD-2): изготовитель, артикул изготовителя, страна происхождения и гарантия идут в каждой проекции;
документы (`documents`) — только по запросу `with_documents=True` (детальная карточка портала): «видно клиенту» и действующие,
без файла, имени загруженного файла и размера. Файл отдаёт отдельное представление портала.
"""

from __future__ import annotations

from urllib.parse import urljoin

from django.conf import settings
from django.db.models import Prefetch
from django.utils import timezone

from .constants import MODE_CLIENT, MODE_LEAD, PROJECTION_MODES, PriceVisibility
from .policy import CatalogPolicy, effective_price_visibility, load_partner_price_visibility, load_policies, policy_for

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
        "manufacturer",
        "manufacturer_part_number",
        "country_of_origin",
        "warranty",
        "documents",
    }
)
#: Ключи, которых нет в проекции без `with_documents=True` (список каталога, интеграция, MCP, превью сотрудника).
DETAIL_ONLY_KEYS = frozenset({"documents"})
CLIENT_ONLY_KEYS = frozenset({"price", "availability", "lead_time_days"})


def published_products():
    """Опубликованные карточки со всем, что читает проекция, — без запросов на строку."""
    from .models import Product, SupplierOffer

    return (
        Product.objects.filter(status__code="PUBLISHED")
        .select_related("domain_type", "category", "uom", "list_price_currency", "brand__country", "country_of_origin")
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


def _manufacturer(product) -> dict | None:
    brand = product.brand if product.brand_id else None
    if brand is None:
        return None
    return {"name": brand.name, "country": brand.country.name if brand.country_id else None}


def _country_of_origin(product) -> str | None:
    """Страна происхождения: своя у карточки, иначе страна изготовителя (как в карточке бэк-офиса)."""
    if product.country_of_origin_id:
        return product.country_of_origin.name
    brand = product.brand if product.brand_id else None
    return brand.country.name if brand is not None and brand.country_id else None


def company_warranty_months() -> int | None:
    """Гарантия компании по умолчанию, мес. (та же, что в карточке бэк-офиса)."""
    from catalog.desk.items import company_warranty_default

    return company_warranty_default()


def _warranty(product, company_default: int | None) -> dict | None:
    """Гарантия клиенту: своя у карточки, иначе срок компании; `None` — нигде не задана или 0 («без гарантии»)."""
    months = product.warranty_months if product.warranty_months is not None else company_default
    if not months:
        return None
    return {"months": months, "terms": product.warranty_terms or ""}


def client_visible_documents():
    """Документы, которые видит клиент: «видно клиенту» и действующие (пусто в «действует до» — бессрочно).

    Единственное правило видимости: им пользуются и список `documents` карточки (`client_documents`), и выдача файла
    (`portal.services.catalog_documents`). «Сегодня» — по `TIME_ZONE` (Asia/Tashkent): документ со сроком «до 4 ноября»
    действует весь день 4 ноября по Ташкенту, а не по UTC.
    """
    from django.db.models import Q

    from .models import TechDocument

    return TechDocument.objects.filter(client_visible=True).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate())
    )


def client_documents(product) -> list[dict]:
    """Документы карточки для клиента (`client_visible_documents` этой карточки): без файла, имени загруженного файла и размера.

    Как в 1С:УТ «Сертификаты номенклатуры»: на печать идут действующие. Порядок — как в справочнике видов, затем по id.
    Имя при скачивании строится из названия документа.
    """
    from .models import DocumentKind

    documents = list(client_visible_documents().filter(product_id=product.pk).order_by("id"))
    kinds = {kind.code: kind for kind in DocumentKind.objects.filter(code__in={doc.kind for doc in documents})}
    documents.sort(key=lambda doc: (kinds[doc.kind].sort_order if doc.kind in kinds else 10**6, doc.pk))
    return [
        {
            "id": doc.pk,
            "kind_name": kinds[doc.kind].name if doc.kind in kinds else doc.kind,
            "title": doc.title,
            "number": doc.number,
            "issued_by": doc.issued_by,
            "issued_at": doc.issued_at.isoformat() if doc.issued_at else None,
            "valid_until": doc.valid_until.isoformat() if doc.valid_until else None,
        }
        for doc in documents
    ]


def _price(product, policy: CatalogPolicy, partners: dict[int, str] | None = None) -> dict | None:
    """Цена-витрина клиенту или `None` — «по запросу» (контракт: `price: Money | null`)."""
    if effective_price_visibility(product, policy, partners) != PriceVisibility.CABINET:
        return None
    if product.list_price is None or product.list_price_currency_id is None:
        return None
    return {"amount": f"{product.list_price:.2f}", "currency": product.list_price_currency.code}


_UNSET = object()


def project(
    product,
    *,
    mode: str,
    policy: CatalogPolicy | None = None,
    request=None,
    with_documents: bool = False,
    warranty_default=_UNSET,
    partners: dict[int, str] | None = None,
) -> dict:
    """Карточка в опубликованном слое — `CatalogItem` контракта портала.

    `mode="client"` — клиент в кабинете и бот в сервисном режиме: + цена (только при политике
    `cabinet`, иначе `null` — «по запросу»), наличие как статус, срок. `mode="lead"` — лид и бот
    вне кабинета: перечень без цены, наличия и срока (решение владельца 2026-10-13).

    `with_documents=True` добавляет `documents` — только детальная карточка портала. `warranty_default` — срок компании,
    уже прочитанный вызывающим (пачка читает его один раз); не задан — читается здесь.
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
        "manufacturer": _manufacturer(product),
        "manufacturer_part_number": product.manufacturer_part_number or None,
        "country_of_origin": _country_of_origin(product),
        "warranty": _warranty(product, company_warranty_months() if warranty_default is _UNSET else warranty_default),
    }
    if with_documents:
        item["documents"] = client_documents(product)
    if mode == MODE_CLIENT:
        policy = policy if policy is not None else policy_for(product.owner_company_id)
        status, lead_time_days = availability(product)
        item["price"] = _price(product, policy, partners)
        item["availability"] = status
        item["lead_time_days"] = lead_time_days
    return item


def project_many(products, *, mode: str, request=None) -> list[dict]:
    """Проекция пачки: политики компаний — одним запросом (для списков портала и поиска)."""
    products = list(products)
    policies = load_policies(product.owner_company_id for product in products) if mode != MODE_LEAD else {}
    partners = (
        load_partner_price_visibility(product.source_supplier_id for product in products) if mode != MODE_LEAD else {}
    )
    warranty_default = company_warranty_months()
    return [
        project(
            product,
            mode=mode,
            policy=policies.get(product.owner_company_id, CatalogPolicy()),
            request=request,
            warranty_default=warranty_default,
            partners=partners,
        )
        for product in products
    ]
