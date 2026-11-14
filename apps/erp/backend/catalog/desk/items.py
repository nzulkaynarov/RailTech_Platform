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


def expiring_days() -> int:
    """За сколько дней до окончания цена партнёра «скоро истекает» — настройка своей компании (задача «Н3c»)."""
    from catalog.policy import policy_for
    from core.tenant import own_company_id

    return policy_for(own_company_id()).offer_expiring_days


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
            proposals_count=Count("field_proposals", filter=Q(field_proposals__status="pending"), distinct=True),
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
    if params.get("proposals") == "pending":
        # CAT-1: позиции с изменениями от поставщиков, ждущими одобрения.
        queryset = queryset.filter(proposals_count__gt=0)
    if params.get("review") == "waiting":
        # PART-3: очередь проверки партнёров — старые отправки сверху (`catalog.review_queue`).
        from catalog.review_queue import waiting_queryset

        return waiting_queryset(queryset.select_related("source_supplier"))
    return queryset.order_by("name", "id")


def queue_rows(products) -> dict[int, dict]:
    """Поля строки очереди проверки на странице: срок, партнёр и полнота (контекст полноты — один на страницу)."""
    from catalog.completeness import CompletenessContext, completeness
    from catalog.review_queue import queue_info

    products = list(products)
    info = queue_info(products)
    ctx = CompletenessContext(products)
    return {
        product.pk: {"review": info[product.pk], "completeness": completeness(product, ctx)["percent"]}
        for product in products
    }


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


def company_warranty_default():
    """Гарантия компании по умолчанию, мес. (`CompanySettings.default_warranty_months`), или None."""
    from parties.models import CompanySettings

    from core.tenant import own_company_id

    company_id = own_company_id()
    if not company_id:
        return None
    return (
        CompanySettings.objects.filter(company_id=company_id).values_list("default_warranty_months", flat=True).first()
    )


def effective_origin(product) -> dict:
    """Страна происхождения: своя у карточки, иначе страна бренда (источник — `item` / `brand` / `none`)."""
    own = product.country_of_origin if product.country_of_origin_id else None
    brand_country = product.brand.country if product.brand_id and product.brand.country_id else None
    effective, source = (own, "item") if own else (brand_country, "brand") if brand_country else (None, "none")

    def ref(country):
        return {"id": country.pk, "name": country.name} if country else None

    return {"own": ref(own), "effective": ref(effective), "brand": ref(brand_country), "source": source}


def effective_warranty(product, company_default) -> dict:
    """Гарантия: своя у карточки, иначе срок компании (источник — `item` / `company` / `none`)."""
    if product.warranty_months is not None:
        months, source = product.warranty_months, "item"
    elif company_default is not None:
        months, source = company_default, "company"
    else:
        months, source = None, "none"
    return {
        "months": product.warranty_months,
        "terms": product.warranty_terms,
        "effective_months": months,
        "company_months": company_default,
        "source": source,
    }


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
        "proposals_count": getattr(product, "proposals_count", 0),
    }


def offer_row(offer, *, show_price: bool, today=None, expiring: int | None = None) -> dict:
    """Предложение поставщика. Цена и валюта — только тому, кто видит `supplier_prices`; иначе `price = null`."""
    today = today or timezone.localdate()
    price = None
    if show_price:
        price = {"amount": f"{offer.base_price:.2f}", "currency": offer.currency.code if offer.currency_id else None}
    expired = bool(offer.valid_until and offer.valid_until < today)
    days = expiring if expiring is not None else expiring_days()  # в цикле вызывающий передаёт значение один раз
    soon = bool(offer.valid_until and today <= offer.valid_until <= today + timedelta(days=days))
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
        "delivery_basis": offer.delivery_basis.code if offer.delivery_basis_id else None,
        "lead_time": offer.delivery_lead_time or "",
        "source": offer.source,
        "updated_at": offer.updated_at,
        "valid_from": offer.valid_from,
        "valid_until": offer.valid_until,
        "is_active": offer.is_active,
        "validity": "expired" if expired else ("expiring" if soon else "ok"),
    }


def item_detail(product, user) -> dict:
    today = timezone.localdate()
    show_price = can_view_supplier_prices(user)
    soon_days = expiring_days()
    from catalog.completeness import completeness
    from catalog.desk.proposals import proposal_row

    offers = list(
        product.offers.select_related("supplier", "product", "currency", "stock_status", "delivery_basis").order_by(
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
    from catalog.desk import images as image_service
    from catalog.desk.tech_docs import doc_fields, kind_names

    names = kind_names()
    docs = list(product.tech_documents.order_by("-created_at", "-id")[:20])
    row.update(
        {
            "description": product.description,
            "gost_drawing": product.gost_drawing,
            "hs_code": product.hs_code,
            "manufacturer_part_number": product.manufacturer_part_number,
            "brand": product.brand.name if product.brand_id else None,
            "brand_id": product.brand_id,
            "source_supplier": (
                {"id": product.source_supplier_id, "name": product.source_supplier.name}
                if product.source_supplier_id
                else None
            ),
            "offers": [offer_row(o, show_price=show_price, today=today, expiring=soon_days) for o in offers],
            "prices_visible": show_price,
            "tech_docs": [doc_fields(d, names, today) for d in docs],
            "images": [image_service.image_row(i) for i in image_service.ordered(product)],
            "origin": effective_origin(product),
            "warranty": effective_warranty(product, company_warranty_default()),
        }
    )
    row["docs_count"] = product.tech_documents.count()  # полное число, как в списке (в карточке показаны последние 20)
    # CAT-1: изменения от поставщиков на одобрении и что мешает публикации (тем же движком, что кнопка «Опубликовать»).
    pending = list(
        product.field_proposals.filter(status="pending").select_related("supplier").order_by("created_at", "id")
    )
    row["proposals"] = [proposal_row(p) for p in pending]
    row["proposals_count"] = len(pending)
    report = completeness(product)
    row["publish"] = {
        "publishable": bool(report["is_publishable"]),
        "missing": [item["code"] for item in report["missing"]],
    }
    row["completeness"] = report["percent"]
    row["catalog_price"] = catalog_price(product)
    from catalog.review_queue import CODE_REVIEW, queue_info

    waiting = getattr(product.status, "code", None) == CODE_REVIEW or bool(
        pending and any(p.contact_id for p in pending)
    )
    if waiting:
        product.waiting_since = _waiting_since(product, pending)
        row["review"] = queue_info([product])[product.pk]
    else:
        row["review"] = None
    return row


def _waiting_since(product, pending):
    """С какого момента карточка ждёт решения: открытая проверка, иначе первое предложение партнёра."""
    review = (
        product.reviews.filter(decision="pending")
        .order_by("submitted_at")
        .values_list("submitted_at", flat=True)
        .first()
    )
    if review is not None:
        return review
    return next((p.created_at for p in pending if p.contact_id), None) or product.updated_at


def catalog_price(product) -> dict:
    """Что покажет каталог клиенту: цена-витрина или «по запросу», и откуда взята видимость (карточка, партнёр, компания)."""
    from catalog.constants import PriceVisibility
    from catalog.policy import price_visibility_source

    visibility, source = price_visibility_source(product)
    shown = None
    if visibility == PriceVisibility.CABINET and product.list_price is not None and product.list_price_currency_id:
        shown = {"amount": f"{product.list_price:.2f}", "currency": product.list_price_currency.code}
    return {"visibility": visibility, "source": source, "price": shown}


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
        country_of_origin=_country(data.get("country_of_origin_id")),
        warranty_months=_warranty_months(data.get("warranty_months")),
        warranty_terms=(data.get("warranty_terms") or "").strip(),
    )
    _apply_kind(product, kind)
    product.save()
    return product


def _brand(brand_id):
    from catalog.models import Manufacturer

    if brand_id is None:
        return None
    brand = Manufacturer.objects.filter(pk=brand_id).first()
    if brand is None:
        raise ItemError("BRAND_NOT_FOUND", "brand_id")
    return brand


def _country(country_id):
    from core.models import Country

    if country_id is None:
        return None
    country = Country.objects.filter(pk=country_id, is_active=True).first()
    if country is None:
        raise ItemError("COUNTRY_NOT_FOUND", "country_of_origin_id")
    return country


#: Потолок гарантии, мес.: 50 лет — защита от опечатки, а не бизнес-правило.
WARRANTY_MONTHS_MAX = 600


def _warranty_months(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not str(value).strip().isdigit() or int(value) > WARRANTY_MONTHS_MAX:
        raise ItemError("WARRANTY_MONTHS_INVALID", "warranty_months")
    return int(value)


def _hs_code(value) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if str(value or "").strip() and (digits != str(value).strip() or len(digits) not in (2, 4, 6, 8, 10)):
        raise ItemError("ITEM_HS_CODE_INVALID", "hs_code")
    return digits


def update_item(product: Product, data: dict, actor=None) -> Product:
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
    # CAT-1: изготовитель (бренд), артикул изготовителя и код ТН ВЭД — правятся в Платформе.
    if "brand_id" in data:
        product.brand = _brand(data["brand_id"])
    if "manufacturer_part_number" in data:
        product.manufacturer_part_number = (data["manufacturer_part_number"] or "").strip()
    # CAT-CARD-1: страна происхождения и гарантия (пусто — страна бренда / срок компании).
    if "country_of_origin_id" in data:
        product.country_of_origin = _country(data["country_of_origin_id"])
    if "warranty_months" in data:
        product.warranty_months = _warranty_months(data["warranty_months"])
    if "warranty_terms" in data:
        product.warranty_terms = (data["warranty_terms"] or "").strip()
    old_hs = product.hs_code or ""
    if "hs_code" in data:
        product.hs_code = _hs_code(data["hs_code"])
    product.save()
    if "hs_code" in data:
        from catalog.services import log_hs_code_change

        log_hs_code_change(product, old_hs, actor, origin="manual")
    return product


def set_published(product: Product, publish: bool, actor) -> Product:
    """«Опубликовать» / «Снять с публикации» (`catalog/publishing.py`: порог полноты, право `catalog.publish`).

    Карточку без владельца (старая, ничья) публикует сотрудник своей компании — владельцем становится своя компания:
    иначе `can_manage` не пустил бы никого, кроме администратора.

    Публикация карточки партнёра «на проверке» — решение очереди проверки (PART-3): строка карточки блокируется
    (`select_for_update`), статус читается под блокировкой; если пока сотрудник смотрел карточку её вернули или опубликовали
    параллельно — 409 `PRODUCT_NOT_ON_REVIEW`, чужое решение не перезаписывается. Журнал и письмо партнёру — только если
    публикация действительно закрыла открытую проверку (и после фиксации транзакции).
    """
    from django.db import transaction

    from catalog.models import ProductReview
    from catalog.publishing import publish_product, unpublish_product
    from catalog.review_queue import CODE_REVIEW
    from core.tenant import own_company_id

    seen_review = getattr(product.status, "code", None) == CODE_REVIEW
    with transaction.atomic():
        locked = (
            Product.objects.select_for_update(of=("self",))
            .select_related("status", "source_supplier")
            .filter(pk=product.pk)
            .first()
        )
        if locked is None:
            raise ItemError("ITEM_NOT_FOUND")
        if publish and seen_review and getattr(locked.status, "code", None) != CODE_REVIEW:
            raise ItemError("PRODUCT_NOT_ON_REVIEW")
        if locked.owner_company_id is None and own_company_id():
            locked.owner_company_id = own_company_id()
            locked.save(update_fields=["owner_company", "updated_at"])
        had_open_review = (
            publish
            and getattr(locked.status, "code", None) == CODE_REVIEW
            and ProductReview.objects.filter(product=locked, decision=ProductReview.Decision.PENDING).exists()
        )
        _, error = (publish_product if publish else unpublish_product)(locked, actor)
        if error:
            raise ItemError(error.split(":", 1)[0])
        if had_open_review:
            _decided(locked, actor, "published")
    return locked


def _decided(product: Product, actor, decision: str, *, reason: str = "", issues=()) -> None:
    """Решение очереди проверки: запись журнала и письмо партнёру (после фиксации транзакции)."""
    from django.db import transaction

    from catalog.desk.audit import record

    record(
        actor,
        entity="product_review",
        instance=product,
        event=decision,
        action="Карточка партнёра " + ("опубликована" if decision == "published" else "возвращена партнёру"),
        before={"status": "REVIEW"},
        after={
            "status": "PUBLISHED" if decision == "published" else "RETURNED",
            **({"reason": reason, "issues": len(issues)} if decision == "returned" else {}),
        },
        detail=product.name,
    )
    if product.source_supplier_id:
        from portal.services.partner_decision_mail import notify_decision

        transaction.on_commit(
            lambda: notify_decision(product, decision, reason=reason, issues=list(issues), actor=actor)
        )


def return_item(product_id, data: dict, actor) -> Product:
    """«Вернуть партнёру»: общий комментарий и замечания по полям; отказы — `ItemError` (409, 400, 403)."""
    from catalog.review_queue import ReviewError, return_to_partner

    try:
        product = return_to_partner(product_id, actor, data.get("reason"), data.get("issues"))
    except ReviewError as error:
        raise ItemError(error.code) from None
    decided = product.reviews.order_by("-decided_at", "-id").first()
    _decided(
        product,
        actor,
        "returned",
        reason=decided.reason if decided else "",
        issues=decided.field_issues if decided else (),
    )
    return product
