"""Поставщики и их предложения для экрана «Номенклатура и поставщики» (D2-3).

Поставщик — внешняя компания, у которой есть предложения или тип SUPPLIER/MANUFACTURER; своя компания в список не входит.
Квота — сколько единиц поставщик готов отгрузить по цене (`SupplierOffer.stock_quantity`), срок действия цены —
окно `valid_from…valid_until` (R7). Цену поставщика видит только тот, кому открыт `supplier_prices`
(`catalog.desk.access.can_view_supplier_prices`): в ответе ERP остальным она `null`, а правка цены — 403.
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Min, Q
from django.utils import timezone
from parties.models import Company

from catalog.desk.access import can_view_supplier_prices
from catalog.desk.audit import record, snapshot
from catalog.desk.items import EXPIRING_SOON_DAYS, ItemError, current_offer_q, offer_row
from catalog.models import StockStatus, SupplierOffer
from catalog.services import offer_validity_error

SUPPLIER_TYPES = ("SUPPLIER", "MANUFACTURER")


def supplier_queryset(params):
    from core.tenant import own_company_id

    today = timezone.localdate()
    queryset = Company.objects.active().filter(Q(supplier_offers__isnull=False) | Q(types__code__in=SUPPLIER_TYPES))
    own_id = own_company_id()
    if own_id:
        queryset = queryset.exclude(pk=own_id)
    ids = list(queryset.values_list("pk", flat=True).distinct())
    queryset = (
        Company.objects.filter(pk__in=ids)
        .select_related("country")
        .annotate(
            offers_count=Count("supplier_offers", filter=Q(supplier_offers__is_active=True), distinct=True),
            expired_count=Count(
                "supplier_offers",
                filter=Q(supplier_offers__is_active=True, supplier_offers__valid_until__lt=today),
                distinct=True,
            ),
            expiring_count=Count(
                "supplier_offers",
                filter=Q(
                    supplier_offers__is_active=True,
                    supplier_offers__valid_until__gte=today,
                    supplier_offers__valid_until__lte=today + timedelta(days=EXPIRING_SOON_DAYS),
                ),
                distinct=True,
            ),
            nearest_valid_until=Min("supplier_offers__valid_until", filter=current_offer_q("supplier_offers__", today)),
        )
    )
    text = (params.get("q") or "").strip()
    if text:
        queryset = queryset.filter(Q(name__icontains=text) | Q(inn__icontains=text))
    return queryset.order_by("name", "id")


def supplier_row(company) -> dict:
    return {
        "id": company.pk,
        "name": company.name,
        "tin": company.inn or "",
        "country": company.country.name if company.country_id else None,
        "offers_count": getattr(company, "offers_count", 0),
        "expired_count": getattr(company, "expired_count", 0),
        "expiring_count": getattr(company, "expiring_count", 0),
        "nearest_valid_until": getattr(company, "nearest_valid_until", None),
    }


def supplier_detail(company, user) -> dict:
    today = timezone.localdate()
    show_price = can_view_supplier_prices(user)
    offers = (
        SupplierOffer.objects.filter(supplier=company)
        .select_related("supplier", "product", "currency", "stock_status")
        .order_by("product__name", "id")
    )
    row = supplier_row(company)
    row.update(
        {
            "contact_person": company.contact_person or "",
            "phone": company.phone or "",
            "email": company.email or "",
            "website": company.website or "",
            "legal_address": company.legal_address or "",
            "offers": [offer_row(o, show_price=show_price, today=today) for o in offers],
            "prices_visible": show_price,
        }
    )
    return row


OFFER_FIELDS = (
    "base_price",
    "currency",
    "stock_quantity",
    "min_order_qty",
    "in_stock_lead_time_days",
    "order_lead_time_days",
    "stock_status",
    "valid_from",
    "valid_until",
    "is_active",
)


def update_offer(offer: SupplierOffer, data: dict, user) -> SupplierOffer:
    """Условия предложения: квота, минимальный заказ, сроки, окно действия цены, признак «действует»; цена — отдельное право.
    Правка пишется в журнал (кто, что было и что стало)."""
    before = snapshot(offer, OFFER_FIELDS)
    if "price" in data:
        if not can_view_supplier_prices(user):
            raise ItemError("SUPPLIER_PRICES_REQUIRED", "price")
        _apply_price(offer, data["price"])
    for source, target in (
        ("quota_qty", "stock_quantity"),
        ("min_order_qty", "min_order_qty"),
        ("in_stock_lead_days", "in_stock_lead_time_days"),
        ("order_lead_days", "order_lead_time_days"),
    ):
        if source in data:
            value = data[source]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or (target == "min_order_qty" and value < 1)
            ):
                raise ItemError("OFFER_NUMBER_INVALID", source)
            setattr(offer, target, value)
    for field in ("valid_from", "valid_until"):
        if field in data:
            setattr(offer, field, data[field])
    if "is_active" in data:
        offer.is_active = bool(data["is_active"])
    if "stock_status" in data:
        status = StockStatus.objects.filter(code=data["stock_status"]).first() if data["stock_status"] else None
        if data["stock_status"] and status is None:
            raise ItemError("STOCK_STATUS_NOT_FOUND", "stock_status")
        offer.stock_status = status
    error = offer_validity_error(offer.valid_from, offer.valid_until)
    if error:
        raise ItemError(error, "valid_until")
    offer.save()
    record(
        user,
        entity="supplier_offer",
        instance=offer,
        event="updated",
        action="Предложение поставщика изменено",
        before=before,
        after=snapshot(offer, OFFER_FIELDS),
    )
    return offer


def _apply_price(offer: SupplierOffer, price) -> None:
    from core.models import Currency

    if not isinstance(price, dict):
        raise ItemError("OFFER_PRICE_INVALID", "price")
    try:
        amount = Decimal(str(price.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ItemError("OFFER_PRICE_INVALID", "price") from None
    if amount < 0 or amount >= Decimal("1e12"):
        raise ItemError("OFFER_PRICE_INVALID", "price")
    currency = Currency.objects.filter(code=price.get("currency"), is_active=True).first()
    if currency is None:
        raise ItemError("OFFER_CURRENCY_INVALID", "price")
    offer.base_price = amount
    offer.currency = currency
