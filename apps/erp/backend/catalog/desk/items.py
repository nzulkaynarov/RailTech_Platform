"""Позиции номенклатуры для экрана «Номенклатура и поставщики» (D2-3): список, карточка, создание, правка.

Тип позиции (SPEC-v3 §7.4): товар со склада / под заказ / услуга фикс / по этапам / по времени. Он **вычисляется**, а не
хранится: услуга — по домену и политике исполнения карточки, товар «со склада» — если у действующего предложения
поставщика есть остаток (то же правило, что `catalog.published.availability`). Цены поставщиков в списке не отдаются
вовсе; в карточке — только тому, кто видит `supplier_prices` (`catalog.desk.access`).
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Exists, Min, OuterRef, Q
from django.utils import timezone

from catalog.constants import FulfillmentPolicy
from catalog.desk.access import can_view_supplier_prices
from catalog.models import Category, DomainType, Product, SupplierOffer
from core.models import UnitOfMeasure

GOODS_DOMAIN = DomainType.GENERAL_GOODS
SERVICES_DOMAIN = DomainType.SERVICES

KIND_STOCK = "stock"
KIND_ON_ORDER = "on_order"
SERVICE_KINDS = {
    "service_fixed": FulfillmentPolicy.FIXED,
    "service_milestones": FulfillmentPolicy.MILESTONES,
    "service_time": FulfillmentPolicy.TIME,
}
ALL_KINDS = (KIND_STOCK, KIND_ON_ORDER, *SERVICE_KINDS)
#: Предложение «скоро истекает»: срок действия цены в ближайшие дни (подсказка снабженцу).
EXPIRING_SOON_DAYS = 14


def current_offer_q(prefix: str = "", today=None) -> Q:
    """Предложение действует: активно и сегодня в окне действия цены."""
    today = today or timezone.localdate()
    return (
        Q(**{f"{prefix}is_active": True})
        & (Q(**{f"{prefix}valid_from__isnull": True}) | Q(**{f"{prefix}valid_from__lte": today}))
        & (Q(**{f"{prefix}valid_until__isnull": True}) | Q(**{f"{prefix}valid_until__gte": today}))
    )


def _stocked_offer(today):
    return (
        SupplierOffer.objects.filter(product=OuterRef("pk"))
        .filter(current_offer_q(today=today))
        .filter(Q(stock_quantity__gt=0) | Q(stock_status__code="IN_STOCK"))
    )


def list_queryset(params):
    """Позиции с поиском и фильтрами; без запросов на строку (агрегаты одним запросом)."""
    today = timezone.localdate()
    queryset = (
        Product.objects.exclude(status__code="ARCHIVED")
        .select_related("domain_type", "uom", "category", "status")
        .annotate(
            has_stock=Exists(_stocked_offer(today)),
            offers_count=Count("offers", filter=Q(offers__is_active=True), distinct=True),
            nearest_valid_until=Min("offers__valid_until", filter=current_offer_q("offers__", today)),
            docs_count=Count("tech_documents", distinct=True),
        )
    )
    text = (params.get("q") or "").strip()
    if text:
        queryset = queryset.filter(
            Q(name__icontains=text)
            | Q(sku__icontains=text)
            | Q(gost_drawing__icontains=text)
            | Q(manufacturer_part_number__icontains=text)
        )
    kind = params.get("kind")
    if kind in SERVICE_KINDS:
        queryset = queryset.filter(domain_type__code=SERVICES_DOMAIN, fulfillment_policy=SERVICE_KINDS[kind].value)
    elif kind == KIND_STOCK:
        queryset = queryset.exclude(domain_type__code=SERVICES_DOMAIN).filter(has_stock=True)
    elif kind == KIND_ON_ORDER:
        queryset = queryset.exclude(domain_type__code=SERVICES_DOMAIN).filter(has_stock=False)
    category = params.get("category")
    if category and str(category).isdigit():
        queryset = queryset.filter(category_id=int(category))
    return queryset.order_by("name", "id")


def item_kind(product, has_stock: bool) -> str:
    if product.is_service:
        policy = product.fulfillment_policy or FulfillmentPolicy.FIXED
        return f"service_{policy}"
    return KIND_STOCK if has_stock else KIND_ON_ORDER


def company_vat_default():
    """Ставка НДС компании по умолчанию (`CompanySettings.default_vat_rate`) или None — без создания строки настроек."""
    from parties.models import CompanySettings

    from core.tenant import own_company_id

    company_id = own_company_id()
    if not company_id:
        return None
    return CompanySettings.objects.filter(company_id=company_id).values_list("default_vat_rate", flat=True).first()


def _rate(value):
    return None if value is None else f"{Decimal(value):.2f}"


def item_row(product, vat_default) -> dict:
    return {
        "id": product.pk,
        "sku": product.sku,
        "name": product.name,
        "kind": item_kind(product, bool(getattr(product, "has_stock", False))),
        "is_service": product.is_service,
        "unit": {"id": product.uom_id, "code": product.uom.code, "name": product.uom.name} if product.uom_id else None,
        "vat_rate": _rate(product.vat_rate),
        "vat_effective": _rate(product.vat_rate if product.vat_rate is not None else vat_default),
        "category": {"id": product.category_id, "name": product.category.name} if product.category_id else None,
        "status": getattr(product.status, "code", None),
        "offers_count": getattr(product, "offers_count", 0),
        "nearest_valid_until": getattr(product, "nearest_valid_until", None),
        "docs_count": getattr(product, "docs_count", 0),
    }


def offer_row(offer, *, show_price: bool, today=None) -> dict:
    """Предложение поставщика. Цена и валюта — только тому, кто видит `supplier_prices`; иначе `price = null`."""
    today = today or timezone.localdate()
    price = None
    if show_price:
        price = {"amount": f"{offer.base_price:.2f}", "currency": offer.currency.code if offer.currency_id else None}
    expired = bool(offer.valid_until and offer.valid_until < today)
    soon = bool(offer.valid_until and today <= offer.valid_until <= today + timedelta(days=EXPIRING_SOON_DAYS))
    return {
        "id": offer.pk,
        "supplier": {"id": offer.supplier_id, "name": offer.supplier.name},
        "product": {"id": offer.product_id, "name": offer.product.name, "sku": offer.product.sku},
        "supplier_sku": offer.supplier_sku,
        "price": price,
        "quota_qty": offer.stock_quantity,
        "min_order_qty": offer.min_order_qty,
        "in_stock_lead_days": offer.in_stock_lead_time_days,
        "order_lead_days": offer.order_lead_time_days,
        "stock_status": offer.stock_status.code if offer.stock_status_id else None,
        "valid_from": offer.valid_from,
        "valid_until": offer.valid_until,
        "is_active": offer.is_active,
        "validity": "expired" if expired else ("expiring" if soon else "ok"),
    }


def item_detail(product, user) -> dict:
    today = timezone.localdate()
    show_price = can_view_supplier_prices(user)
    offers = list(
        product.offers.select_related("supplier", "product", "currency", "stock_status").order_by(
            "supplier__name", "id"
        )
    )
    stocked = any(
        o.is_active
        and not (o.valid_from and o.valid_from > today)
        and not (o.valid_until and o.valid_until < today)
        and (o.stock_quantity > 0 or getattr(o.stock_status, "code", None) == "IN_STOCK")
        for o in offers
    )
    product.has_stock = stocked
    product.offers_count = sum(1 for o in offers if o.is_active)
    row = item_row(product, company_vat_default())
    row.update(
        {
            "description": product.description,
            "gost_drawing": product.gost_drawing,
            "hs_code": product.hs_code,
            "manufacturer_part_number": product.manufacturer_part_number,
            "brand": product.brand.name if product.brand_id else None,
            "offers": [offer_row(o, show_price=show_price, today=today) for o in offers],
            "prices_visible": show_price,
            "tech_docs": [
                {"id": d.pk, "title": d.title, "kind": d.kind}
                for d in product.tech_documents.order_by("-created_at", "-id")[:20]
            ],
        }
    )
    row["docs_count"] = len(row["tech_docs"])
    return row


# --- запись ------------------------------------------------------------------------------------------------------


class ItemError(Exception):
    """Отказ проверки: `code` — машинный код ответа `{"detail": КОД}`."""

    def __init__(self, code: str, field: str | None = None):
        super().__init__(code)
        self.code = code
        self.field = field


def parse_vat(value):
    """`None`/пусто — «по умолчанию компании»; иначе число 0..100 с двумя знаками."""
    if value in (None, ""):
        return None
    try:
        rate = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ItemError("VAT_RATE_INVALID", "vat_rate") from None
    if rate < 0 or rate > 100:
        raise ItemError("VAT_RATE_INVALID", "vat_rate")
    return rate


def _apply_kind(product, kind) -> None:
    if kind in SERVICE_KINDS:
        product.domain_type = DomainType.objects.get(code=SERVICES_DOMAIN)
        product.fulfillment_policy = SERVICE_KINDS[kind].value
    else:
        product.domain_type = DomainType.objects.get(code=GOODS_DOMAIN)
        product.fulfillment_policy = ""


def _unit(unit_id):
    if unit_id is None:
        return None
    unit = UnitOfMeasure.objects.filter(pk=unit_id, is_active=True).first()
    if unit is None:
        raise ItemError("UNIT_NOT_FOUND", "unit_id")
    return unit


def _category(category_id):
    if category_id is None:
        return None
    category = Category.objects.filter(pk=category_id).first()
    if category is None:
        raise ItemError("CATEGORY_NOT_FOUND", "category_id")
    return category


def create_item(data: dict, actor) -> Product:
    from core.tenant import own_company

    name = (data.get("name") or "").strip()
    if not name:
        raise ItemError("ITEM_NAME_REQUIRED", "name")
    kind = data.get("kind")
    if kind not in (KIND_STOCK, KIND_ON_ORDER, *SERVICE_KINDS):
        raise ItemError("ITEM_KIND_INVALID", "kind")
    product = Product(
        name=name,
        description=data.get("description") or "",
        uom=_unit(data.get("unit_id")),
        category=_category(data.get("category_id")),
        vat_rate=parse_vat(data.get("vat_rate")),
        owner_company=own_company(),
    )
    _apply_kind(product, kind)
    product.save()
    return product


def update_item(product: Product, data: dict) -> Product:
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise ItemError("ITEM_NAME_REQUIRED", "name")
        product.name = name
    if "description" in data:
        product.description = data["description"] or ""
    if "unit_id" in data:
        product.uom = _unit(data["unit_id"])
    if "category_id" in data:
        product.category = _category(data["category_id"])
    if "vat_rate" in data:
        product.vat_rate = parse_vat(data["vat_rate"])
    if "kind" in data:
        if data["kind"] not in (KIND_STOCK, KIND_ON_ORDER, *SERVICE_KINDS):
            raise ItemError("ITEM_KIND_INVALID", "kind")
        _apply_kind(product, data["kind"])
    product.save()
    return product
