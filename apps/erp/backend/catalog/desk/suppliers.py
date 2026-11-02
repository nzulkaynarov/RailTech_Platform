"""Поставщики и их предложения для экрана «Номенклатура и поставщики» (D2-3).

Поставщик — внешняя компания, у которой есть предложения или тип SUPPLIER/MANUFACTURER; своя компания в список не входит.
Квота — сколько единиц поставщик готов отгрузить по цене (`SupplierOffer.stock_quantity`), срок действия цены —
окно `valid_from…valid_until` (R7). Цену поставщика видит только тот, кому открыт `supplier_prices`
(`catalog.desk.access.can_view_supplier_prices`): в ответе ERP остальным она `null`, а правка цены — 403.
"""

import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import pghistory
from django.conf import settings
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
        .select_related("country", "default_currency")
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
        queryset = queryset.filter(
            Q(name__icontains=text) | Q(inn__icontains=text) | Q(registration_number__icontains=text)
        )
    return queryset.order_by("name", "id")


def supplier_row(company) -> dict:
    return {
        "id": company.pk,
        "name": company.name,
        "tin": company.inn or "",
        "registration_number": company.registration_number or "",
        "country": company.country.name if company.country_id else None,
        "country_id": company.country_id,
        "currency": company.default_currency.code if company.default_currency_id else None,
        "is_manufacturer": company.types.filter(code="MANUFACTURER").exists(),
        "offers_count": getattr(company, "offers_count", 0),
        "expired_count": getattr(company, "expired_count", 0),
        "expiring_count": getattr(company, "expiring_count", 0),
        "nearest_valid_until": getattr(company, "nearest_valid_until", None),
    }


def supplier_detail(company, user) -> dict:
    today = timezone.localdate()
    show_price = can_view_supplier_prices(user)
    from catalog.models import Manufacturer

    offers = list(
        SupplierOffer.objects.filter(supplier=company)
        .select_related("supplier", "product__brand", "currency", "stock_status", "delivery_basis")
        .order_by("product__name", "id")
    )
    # CAT-1: «чьи бренды поставляет» — выводится из его цен (у каких изготовителей есть его предложения), а не отдельным
    # списком: такая связь не расходится с ценами и не требует второго ввода (Odoo: товары поставщика — из supplierinfo).
    supplied = {o.product.brand_id: o.product.brand.name for o in offers if o.product.brand_id and o.is_active}
    made = Manufacturer.objects.filter(company=company).order_by("name").values_list("id", "name")
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
            "brands": [{"id": pk, "name": name} for pk, name in sorted(supplied.items(), key=lambda x: x[1].lower())],
            "manufactured_brands": [{"id": pk, "name": name} for pk, name in made],
        }
    )
    return row


# --- поставщик: создание и правка (CAT-1) -------------------------------------------------------------------------

SUPPLIER_TEXT_FIELDS = ("contact_person", "phone", "email", "website", "legal_address")


def _country(country_id):
    from core.models import Country

    if country_id is None:
        return None
    country = Country.objects.filter(pk=country_id).first()
    if country is None:
        raise ItemError("COUNTRY_NOT_FOUND", "country_id")
    return country


def _currency(code, field="currency"):
    from core.models import Currency

    if not code:
        return None
    currency = Currency.objects.filter(code=str(code).upper(), is_active=True).first()
    if currency is None:
        raise ItemError("CURRENCY_NOT_FOUND", field)
    return currency


def _check_identity(company: Company) -> None:
    """ИНН (резидент) или рег. номер страны (нерезидент) — хотя бы одно; дубль — 409 `SUPPLIER_EXISTS`."""
    if not company.inn and not company.registration_number:
        raise ItemError("SUPPLIER_ID_REQUIRED", "tin")
    if company.inn and not re.match(settings.INN_VALIDATION_REGEX, company.inn):
        raise ItemError("TIN_INVALID", "tin")
    others = Company.objects.exclude(pk=company.pk) if company.pk else Company.objects.all()
    if company.inn and others.filter(inn=company.inn).exists():
        raise ItemError("SUPPLIER_EXISTS", "tin")
    if (
        company.registration_number
        and others.filter(
            registration_number__iexact=company.registration_number, country_id=company.country_id
        ).exists()
    ):
        raise ItemError("SUPPLIER_EXISTS", "registration_number")


def save_supplier(company: Company, data: dict, user) -> Company:
    """Создание и правка поставщика — простая карточка компании, без анкет и статусов допуска (L0-2).

    Эталон — Odoo «Contact» с вкладкой «Purchase» (валюта поставщика) и SAP Business Partner с ролью «поставщик»:
    одна запись контрагента, тип «поставщик» (и «изготовитель», если он сам выпускает товар).
    """
    from parties.models import CompanyType

    created = company.pk is None
    before = None if created else snapshot(company, SUPPLIER_SNAPSHOT)
    if "name" in data or created:
        name = (data.get("name") or "").strip()
        if not name:
            raise ItemError("SUPPLIER_NAME_REQUIRED", "name")
        company.name = name
    if "country_id" in data:
        company.country = _country(data["country_id"])
    if "tin" in data:
        company.inn = (data["tin"] or "").strip() or None
    if "registration_number" in data:
        company.registration_number = (data["registration_number"] or "").strip()
    if "currency" in data:
        company.default_currency = _currency(data["currency"])
    for field in SUPPLIER_TEXT_FIELDS:
        if field in data:
            setattr(company, field, (data[field] or "").strip())
    _check_identity(company)
    if created:
        company.is_registered = False  # заведена сотрудником, входа нет
    company.save()
    wanted = {"SUPPLIER"} | ({"MANUFACTURER"} if data.get("is_manufacturer") else set())
    if created or "is_manufacturer" in data:
        for code in ("SUPPLIER", "MANUFACTURER"):
            kind = CompanyType.objects.filter(code=code).first()
            if kind is None:
                continue
            if code in wanted:
                company.types.add(kind)
            elif code == "MANUFACTURER":
                company.types.remove(kind)
    record(
        user,
        entity="supplier",
        instance=company,
        event="created" if created else "updated",
        action="Поставщик заведён" if created else "Поставщик изменён",
        before=before,
        after=snapshot(company, SUPPLIER_SNAPSHOT),
        detail=company.name,
    )
    return company


SUPPLIER_SNAPSHOT = ("name", "inn", "registration_number", "country", "default_currency", *SUPPLIER_TEXT_FIELDS)


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
    "delivery_basis",
    "delivery_lead_time",
    "supplier_sku",
    "source",
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
    _apply_terms(offer, data)
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
    with pghistory.context(user=getattr(user, "pk", None), source=offer.source):
        offer.save()
    record(
        user,
        entity="supplier_offer",
        instance=offer,
        event="updated",
        action="Предложение поставщика изменено",
        before=before,
        after=snapshot(offer, OFFER_FIELDS),
        masked=("base_price",),  # цену видит только supplier_prices, журнал читает администратор
        detail=f"{offer.product.name} | {offer.supplier.name}",
    )
    return offer


def _apply_terms(offer: SupplierOffer, data: dict) -> None:
    """Базис поставки (Incoterms), срок поставки словами, артикул поставщика, источник цены (CAT-1)."""
    from core.models import DeliveryBasis

    if "delivery_basis" in data:
        code = data["delivery_basis"]
        basis = DeliveryBasis.objects.filter(code=code).first() if code else None
        if code and basis is None:
            raise ItemError("DELIVERY_BASIS_NOT_FOUND", "delivery_basis")
        offer.delivery_basis = basis
    if "lead_time" in data:
        offer.delivery_lead_time = (data["lead_time"] or "").strip()[:100]
    if "supplier_sku" in data:
        offer.supplier_sku = (data["supplier_sku"] or "").strip()[:100]
    if "source" in data:
        if data["source"] not in SupplierOffer.Source.values:
            raise ItemError("OFFER_SOURCE_INVALID", "source")
        offer.source = data["source"]


def create_offer(supplier: Company, data: dict, user) -> SupplierOffer:
    """Цена поставщика вручную (CAT-1): товар, цена, валюта, Incoterms, MOQ, сроки, окно действия, источник.

    Эталон — Odoo `product.supplierinfo` и SAP info record: одна запись цены на пару «поставщик — товар»; вторая на ту же
    пару — 409 `OFFER_EXISTS` (правка существующей). Цена — только с правом на цены поставщиков.
    """
    from catalog.models import Product

    if not can_view_supplier_prices(user):
        raise ItemError("SUPPLIER_PRICES_REQUIRED", "price")
    product = Product.objects.exclude(status__code="ARCHIVED").filter(pk=data.get("product_id")).first()
    if product is None:
        raise ItemError("ITEM_NOT_FOUND", "product_id")
    if SupplierOffer.objects.filter(product=product, supplier=supplier).exists():
        raise ItemError("OFFER_EXISTS", "product_id")
    if "price" not in data:
        raise ItemError("OFFER_PRICE_INVALID", "price")
    offer = SupplierOffer(product=product, supplier=supplier, source=SupplierOffer.Source.MANUAL)
    _apply_price(offer, data["price"])
    for source, target in (
        ("quota_qty", "stock_quantity"),
        ("min_order_qty", "min_order_qty"),
        ("in_stock_lead_days", "in_stock_lead_time_days"),
        ("order_lead_days", "order_lead_time_days"),
    ):
        if source in data:
            setattr(offer, target, data[source])
    offer.valid_from = data.get("valid_from")
    offer.valid_until = data.get("valid_until")
    _apply_terms(offer, data)
    error = offer_validity_error(offer.valid_from, offer.valid_until)
    if error:
        raise ItemError(error, "valid_until")
    with pghistory.context(user=getattr(user, "pk", None), source=offer.source):
        offer.save()
    record(
        user,
        entity="supplier_offer",
        instance=offer,
        event="created",
        action="Цена поставщика добавлена",
        before=None,
        after=snapshot(offer, OFFER_FIELDS),
        masked=("base_price",),
        detail=f"{product.name} | {supplier.name}",
    )
    return offer


def offer_history(offer: SupplierOffer, user) -> list[dict]:
    """История цены (pghistory): снимки, где менялись цена, валюта, окно действия, базис или источник; новые сверху.

    Цену в истории видит тот же, кто видит её в предложении; остальным — даты и источник без суммы.
    """
    from accounts.models import CustomUser

    show_price = can_view_supplier_prices(user)
    events = list(
        offer.events.select_related("currency", "delivery_basis", "pgh_context").order_by("pgh_created_at", "pgh_id")
    )
    rows, last = [], None
    for event in events:
        key = (
            event.base_price,
            event.currency_id,
            event.valid_from,
            event.valid_until,
            event.delivery_basis_id,
            event.source,
        )
        if key == last:
            continue
        last = key
        metadata = event.pgh_context.metadata if event.pgh_context_id else {}
        rows.append(
            {
                "at": event.pgh_created_at,
                "price": (
                    {"amount": f"{event.base_price:.2f}", "currency": event.currency.code if event.currency_id else None}
                    if show_price
                    else None
                ),
                "valid_from": event.valid_from,
                "valid_until": event.valid_until,
                "delivery_basis": event.delivery_basis.code if event.delivery_basis_id else None,
                "source": event.source,
                "user_id": metadata.get("user"),
            }
        )
    people = {u.pk: u for u in CustomUser.objects.filter(pk__in={r["user_id"] for r in rows if r["user_id"]})}
    for row in rows:
        person = people.get(row.pop("user_id"))
        row["by"] = (person.get_full_name() or person.email) if person else None
    return list(reversed(rows))


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
