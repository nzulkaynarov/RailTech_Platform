"""«Мои товары» партнёра: свои карточки и свои цены, отправка на проверку, подтверждение актуальности (PART-2, ADR-0022 п. 4).

Партнёр видит только своё: карточки, где он источник данных (`Product.source_supplier`) или у него есть цена, и только
собственную цену по ним. Чужие цены, другие поставщики, наши цены продажи и закупки сюда не попадают — модуль строит ответ
из запросов, которые фильтруют по компании сессии, а не из общих проекций каталога.

Карточкой владеем мы: партнёр может отправить свой черновик или возвращённую карточку на проверку (`REVIEW`); публикует и
возвращает сотрудник (очередь проверки — PART-3). Из портала публикации нет.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pghistory
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Case, Count, Exists, F, OuterRef, Q, Subquery, When
from django.db.models.functions import Greatest
from django.http import Http404
from django.utils import timezone
from portal.exceptions import PortalValidationError
from portal.models import PortalUpload

from catalog.completeness import CompletenessContext, requirements_for
from catalog.constants import DEFAULT_OFFER_CONFIRM_DAYS
from catalog.desk.items import ItemError
from catalog.desk.tech_docs import _check_range, _date, validate_upload
from catalog.models import (
    DocumentKind,
    Product,
    ProductFieldProposal,
    ProductReview,
    ProductStatus,
    SupplierOffer,
    TechDocument,
)
from catalog.offer_freshness import EXPIRING_DAYS, freshness
from catalog.policy import policy_for
from catalog.published import client_visible_documents
from catalog.review_flow import close_pending_review
from catalog.review_queue import reason_text
from core.tenant import own_company_id

DRAFT = "draft"
REVIEW = "review"
RETURNED = "returned"
PUBLISHED = "published"
#: Цена партнёра привязалась к чужой неопубликованной карточке: ему видно только то, что он прислал сам.
MATCHED = "matched"
CARD_STATUSES = (DRAFT, REVIEW, RETURNED, PUBLISHED, MATCHED)

#: Коды статуса карточки в справочнике ERP.
CODE_DRAFT = "DRAFT"
CODE_REVIEW = "REVIEW"
CODE_RETURNED = "RETURNED"
CODE_PUBLISHED = "PUBLISHED"
CODE_ARCHIVED = "ARCHIVED"

#: Поля, которые партнёр заполняет прайсом: только по ним считается его «полнота» и список «не хватает». Остальное
#: (цена-витрина, документ соответствия, фото) заполняет сотрудник — требовать это от партнёра нечестно.
PARTNER_FIELD_CODES = ("name", "uom", "category", "hs_code", "identity")

MAX_BATCH = 500
NOTIFY_EVENT = "portal.partner_products_submitted"


def _own_q(company) -> Q:
    return Q(source_supplier_id=company.pk)


def _visible_q(company) -> Q:
    """Карточка, поля которой партнёру можно показывать: своя (он источник данных) или опубликованная (слой публичен)."""
    return _own_q(company) | Q(status__code=CODE_PUBLISHED)


def status_filter(company, status: str) -> Q:
    """Фильтр вкладки. Чужая неопубликованная карточка — «сопоставлена»: её ход и поля партнёру не видны."""
    own = _own_q(company)
    published = Q(status__code=CODE_PUBLISHED)
    if status == PUBLISHED:
        return published
    if status == MATCHED:
        return ~_visible_q(company)
    if status == RETURNED:
        return own & Q(status__code=CODE_RETURNED)
    if status == REVIEW:
        return own & Q(status__code=CODE_REVIEW)
    if status == DRAFT:
        return own & (Q(status__isnull=True) | ~Q(status__code__in=(CODE_PUBLISHED, CODE_REVIEW, CODE_RETURNED)))
    raise ValueError(status)


def partner_cards(company):
    """Карточки партнёра: он источник данных или у него есть цена. Архивные не показываются."""
    mine = SupplierOffer.objects.filter(product=OuterRef("pk"), supplier=company)
    return (
        Product.objects.annotate(_has_my_offer=Exists(mine))
        .filter(Q(source_supplier_id=company.pk) | Q(_has_my_offer=True))
        .exclude(status__code=CODE_ARCHIVED)
        .select_related("status", "brand", "category", "domain_type", "uom")
    )


def card_status(product, company_id: int) -> str:
    code = product.status.code if product.status_id else None
    if code == CODE_PUBLISHED:
        return PUBLISHED
    if product.source_supplier_id != company_id:
        return MATCHED
    if code == CODE_REVIEW:
        return REVIEW
    if code == CODE_RETURNED:
        return RETURNED
    return DRAFT


def status_counts(company, queryset) -> dict:
    aggregates = {status: Count("pk", filter=status_filter(company, status)) for status in CARD_STATUSES}
    counts = queryset.aggregate(all=Count("pk"), **aggregates)
    return {key: counts[key] for key in ("all", *CARD_STATUSES)}


def search(queryset, company, text: str):
    """Поиск по названию, бренду и артикулу. Поля карточки ищутся только у своих и опубликованных; у чужой неопубликованной —
    только то, что партнёр прислал сам (иначе поиск выдавал бы, что чужая карточка с таким названием есть)."""
    text = (text or "").strip()
    if not text:
        return queryset
    mine = SupplierOffer.objects.filter(product=OuterRef("pk"), supplier=company).filter(
        Q(supplier_item_name__icontains=text) | Q(supplier_brand__icontains=text) | Q(supplier_mpn__icontains=text)
    )
    card_fields = Q(name__icontains=text) | Q(manufacturer_part_number__icontains=text) | Q(brand__name__icontains=text)
    return queryset.annotate(_my_text_match=Exists(mine)).filter(
        (_visible_q(company) & card_fields) | Q(_my_text_match=True)
    )


def ordered(queryset, company):
    """Порядок списка: новые сверху; у чужой неопубликованной карточки — по дате СВОЕЙ цены, не по её изменениям."""
    my_updated = SupplierOffer.objects.filter(product=OuterRef("pk"), supplier=company).values("updated_at")[:1]
    sort = Case(When(_visible_q(company), then=F("updated_at")), default=Subquery(my_updated))
    return queryset.annotate(_sort_at=sort).order_by("-_sort_at", "-id")


def offers_attention(company) -> dict:
    """Сколько цен компании требуют внимания: срок истёк, не подтверждены дольше N дней, срок скоро кончится.

    Те же правила, что `catalog/offer_freshness.py`, но одним запросом по всем ценам компании — для плашки «подтвердите
    актуальность» над списком (карточки страницы всех цен не покрывают).
    """
    today, now = timezone.localdate(), timezone.now()
    confirm_days = policy_for(own_company_id()).offer_confirm_days or DEFAULT_OFFER_CONFIRM_DAYS
    moment = Greatest("confirmed_at", "updated_at")
    expired = Q(valid_until__lt=today)
    stale = ~expired & Q(_moment__lt=now - timedelta(days=confirm_days))
    expiring = ~expired & ~stale & Q(valid_until__lte=today + timedelta(days=EXPIRING_DAYS))
    totals = (
        SupplierOffer.objects.filter(supplier=company, is_active=True)
        .annotate(_moment=moment)
        .aggregate(
            expired=Count("pk", filter=expired),
            stale=Count("pk", filter=stale),
            expiring=Count("pk", filter=expiring),
        )
    )
    return totals


# ── Проекция карточки ────────────────────────────────────────────────────────────────────────────────


def partner_completeness(product, ctx: CompletenessContext) -> dict:
    """Полнота по полям, которые партнёр заполняет прайсом: `{percent, missing: [{code, label}]}`."""
    requirements = [item for item in requirements_for(product, ctx) if item[0] in PARTNER_FIELD_CODES]
    missing = [{"code": code, "label": str(label)} for code, label, check in requirements if not check(product, ctx)]
    percent = round((len(requirements) - len(missing)) * 100 / len(requirements)) if requirements else 100
    return {"percent": percent, "missing": missing}


def _offer_view(offer, *, today, now, confirm_days: int) -> dict:
    currency = offer.currency.code if offer.currency_id else None
    return {
        "price": {"amount": f"{offer.base_price:.2f}", "currency": currency} if currency else None,
        "valid_from": offer.valid_from,
        "valid_until": offer.valid_until,
        "delivery_basis": offer.delivery_basis.code if offer.delivery_basis_id else None,
        "min_order_qty": offer.min_order_qty,
        "confirmed_at": offer.confirmed_at,
        "freshness": freshness(offer, today=today, now=now, confirm_days=confirm_days),
    }


def _issues(review) -> list[dict]:
    """Замечания последнего возврата: `[{field, comment}]` — поле подсвечивается в карточке кабинета."""
    return list(review.field_issues or []) if review is not None else []


def project_cards(company, products: list, language: str | None = None) -> list[dict]:
    """Карточки страницы → элементы `PartnerProduct`. Запросы — на страницу, не на строку."""
    if not products:
        return []
    ids = [product.pk for product in products]
    today, now = timezone.localdate(), timezone.now()
    confirm_days = policy_for(own_company_id()).offer_confirm_days or DEFAULT_OFFER_CONFIRM_DAYS
    my_offers = {
        offer.product_id: offer
        for offer in SupplierOffer.objects.filter(supplier=company, product_id__in=ids).select_related(
            "currency", "delivery_basis"
        )
    }
    pending = set(
        ProductFieldProposal.objects.filter(
            supplier=company, status=ProductFieldProposal.Status.PENDING, product_id__in=ids
        ).values_list("product_id", flat=True)
    )
    returns: dict[int, ProductReview] = {}
    for review in ProductReview.objects.filter(
        product_id__in=ids, decision=ProductReview.Decision.RETURNED, product__source_supplier=company
    ).order_by("-decided_at", "-id"):
        returns.setdefault(review.product_id, review)
    ctx = CompletenessContext(products)
    items = []
    for product in products:
        own = product.source_supplier_id == company.pk
        status = card_status(product, company.pk)
        my_offer = my_offers.get(product.pk)
        offer = my_offer if my_offer is not None and my_offer.is_active else None
        offer_view = _offer_view(offer, today=today, now=now, confirm_days=confirm_days) if offer else None
        if status == MATCHED:
            # Цена привязалась к чужой неопубликованной карточке: только то, что партнёр прислал сам. Ни названия, ни категории,
            # ни полноты, ни статуса и даты правок чужой карточки (эталон — Amazon «matched to existing listing»).
            items.append(
                {
                    "id": product.pk,
                    # Старые предложения без названия строки: бренд и артикул, но не название чужой карточки
                    "name": my_offer.supplier_item_name
                    or " ".join(filter(None, (my_offer.supplier_brand, my_offer.supplier_mpn)))
                    or my_offer.supplier_sku
                    or "—",
                    "brand": my_offer.supplier_brand or None,
                    "manufacturer_part_number": my_offer.supplier_mpn,
                    "category": None,
                    "status": MATCHED,
                    "return_reason": None,
                    "return_issues": [],
                    "completeness": 0,
                    "offer": offer_view,
                    "has_pending_change": False,
                    "is_own": False,
                    "can_submit": False,
                    "updated_at": my_offer.updated_at,
                }
            )
            continue
        items.append(
            {
                "id": product.pk,
                "name": product.name,
                "brand": product.brand.name if product.brand_id else None,
                "manufacturer_part_number": product.manufacturer_part_number or "",
                "category": product.category.name if product.category_id else None,
                "status": status,
                "return_reason": (
                    (reason_text(returns[product.pk].reason, language) or None)
                    if own and status == RETURNED and product.pk in returns
                    else None
                ),
                "return_issues": _issues(returns.get(product.pk)) if own and status == RETURNED else [],
                "completeness": partner_completeness(product, ctx)["percent"],
                "offer": offer_view,
                "has_pending_change": product.pk in pending,
                "is_own": own,
                "can_submit": own and status in (DRAFT, RETURNED),
                "updated_at": product.updated_at,
            }
        )
    return items


def project_detail(company, product, language: str | None = None) -> dict:
    """Одна карточка с описанием, недостающими полями и историей проверок (только своя).

    Сопоставленная чужая неопубликованная карточка — только присланное партнёром: описания, ТН ВЭД, единицы, недостающих
    полей и истории нет.
    """
    [item] = project_cards(company, [product], language)
    if item["status"] == MATCHED:
        return {**item, "description": "", "hs_code": "", "uom": None, "missing": [], "history": [], "documents": []}
    ctx = CompletenessContext([product])
    own = product.source_supplier_id == company.pk
    history = []
    if own:
        history = [
            {
                "submitted_at": review.submitted_at,
                "decision": review.decision,
                "reason": reason_text(review.reason, language),
                "issues": list(review.field_issues or []),
                "decided_at": review.decided_at,
            }
            for review in product.reviews.all()
        ]
    return {
        **item,
        "description": product.description or "",
        "hs_code": product.hs_code or "",
        "uom": product.uom.code if product.uom_id else None,
        "missing": partner_completeness(product, ctx)["missing"],
        "history": history,
        "documents": list_partner_documents(company, product.pk),
    }


def serialize_partner_document(doc: TechDocument, company, kind_names: dict[str, str] | None = None) -> dict:
    if kind_names is None:
        kind_names = {k.code: k.name for k in DocumentKind.objects.all()}
    return {
        "id": doc.pk,
        "kind": doc.kind,
        "kind_name": kind_names.get(doc.kind, doc.kind),
        "title": doc.title,
        "number": doc.number or "",
        "issued_by": doc.issued_by or "",
        "issued_at": doc.issued_at,
        "valid_until": doc.valid_until,
        "original_name": doc.original_name or "",
        "size_bytes": doc.size_bytes or 0,
        "status": doc.review_state,
        "can_delete": doc.source_supplier_id == company.pk,
        "created_at": doc.created_at,
    }


def _documents_for(company, product_id: int):
    """Документы карточки, которые партнёру можно видеть и скачивать; `None` — карточка ему не видна.

    Партнёр без владения карточкой (есть только цена) — как клиент: `client_visible`, одобренные, действующие и только у
    опубликованной карточки. Владелец (источник данных) дополнительно видит присланное им самим, в том числе «на проверке» и
    отклонённое. Внутренние документы сотрудников (`client_visible=False`) не отдаются никому из партнёров.
    """
    product = Product.objects.filter(pk=product_id).select_related("status").exclude(status__code=CODE_ARCHIVED).first()
    if product is None:
        return None
    owns = product.source_supplier_id == company.pk
    if not owns and not SupplierOffer.objects.filter(supplier=company, product=product).exists():
        return None
    if owns:
        shown = Q(source_supplier_id=company.pk) | Q(client_visible=True, review_state="approved")
        return TechDocument.objects.filter(product_id=product_id).filter(shown)
    if product.status_id is None or product.status.code != CODE_PUBLISHED:
        return TechDocument.objects.none()
    return client_visible_documents().filter(product_id=product_id)


def list_partner_documents(company, product_id: int) -> list[dict]:
    queryset = _documents_for(company, product_id)
    if queryset is None:
        return []
    docs = list(queryset.order_by("-created_at", "-id"))
    kinds = {k.code: k.name for k in DocumentKind.objects.filter(code__in={d.kind for d in docs})}
    return [serialize_partner_document(doc, company, kinds) for doc in docs]


def get_partner_document(company, product_id: int, doc_id: int) -> TechDocument | None:
    queryset = _documents_for(company, product_id)
    return queryset.filter(pk=doc_id).first() if queryset is not None else None


def _read_upload(company, upload_id):
    """Файл `PortalUpload` компании как отдельный `ContentFile` (копия содержимого, а не ссылка на путь загрузки)."""
    try:
        key = uuid.UUID(str(upload_id))
    except ValueError:
        raise PortalValidationError("UPLOAD_NOT_FOUND")
    upload = PortalUpload.objects.filter(upload_id=key, company=company).first()
    if upload is None or not upload.file:
        raise PortalValidationError("UPLOAD_NOT_FOUND")
    try:
        with upload.file.open("rb") as stream:
            content = stream.read()
    except OSError:
        raise PortalValidationError("UPLOAD_NOT_FOUND")
    return ContentFile(content, name=upload.name or os.path.basename(upload.file.name))


@transaction.atomic
def create_partner_document(company, product_id: int, data: dict, file_obj=None, contact=None) -> dict:
    """Документ своей карточки от партнёра: уходит сотруднику на проверку и до одобрения клиенту не виден.

    `client_visible` из тела запроса игнорируется — решает сотрудник при одобрении.
    """
    product = (
        Product.objects.filter(pk=product_id, source_supplier_id=company.pk).exclude(status__code=CODE_ARCHIVED).first()
    )
    if product is None:
        raise Http404

    if file_obj is None:
        upload_id = data.get("upload_id")
        if not upload_id:
            raise PortalValidationError("FILE_REQUIRED")
        file_obj = _read_upload(company, upload_id)

    try:
        content_type = validate_upload(file_obj)
    except ItemError as err:
        raise PortalValidationError(err.code)

    kind_code = (data.get("kind") or "certificate").strip()
    kind = DocumentKind.objects.filter(code=kind_code, is_active=True).first()
    if kind is None:
        raise PortalValidationError("TECH_DOC_KIND_INVALID")

    try:
        issued_at = _date(data.get("issued_at"), "issued_at")
        valid_until = _date(data.get("valid_until"), "valid_until")
        _check_range(issued_at, valid_until)
    except ItemError as err:
        raise PortalValidationError(err.code)

    title = (data.get("title") or "").strip() or os.path.splitext(getattr(file_obj, "name", "document"))[0]
    number = (data.get("number") or "").strip()
    issued_by = (data.get("issued_by") or "").strip()

    doc = TechDocument.objects.create(
        kind=kind.code,
        title=title[:255],
        file=file_obj,
        original_name=os.path.basename(getattr(file_obj, "name", "document"))[:255],
        content_type=content_type,
        size_bytes=getattr(file_obj, "size", 0),
        number=number[:100],
        issued_by=issued_by[:255],
        issued_at=issued_at,
        valid_until=valid_until,
        client_visible=False,
        review_state="pending",
        source_supplier=company,
        uploaded_by_contact=contact,
        product=product,
    )
    return serialize_partner_document(doc, company, {kind.code: kind.name})


@transaction.atomic
def delete_partner_document(company, product_id: int, doc_id: int, contact=None, ip: str = "") -> bool:
    """Удалить можно только документ, присланный этой компанией; запись в журнал — в той же транзакции.

    Документы сотрудников на своей карточке партнёр удалить не может: для него они «не найдены».
    """
    product = (
        Product.objects.filter(pk=product_id, source_supplier_id=company.pk).exclude(status__code=CODE_ARCHIVED).first()
    )
    if product is None:
        return False
    doc = (
        TechDocument.objects.select_for_update()
        .filter(pk=doc_id, product_id=product_id, source_supplier=company)
        .first()
    )
    if doc is None:
        return False
    from crm.models import ActivityLog

    ActivityLog.objects.create(
        action="Партнёр удалил документ товара",
        event_code="catalog.partner_document_deleted",
        event_params={
            "document_id": doc.pk,
            "kind": doc.kind,
            "number": doc.number,
            "title": doc.title,
            "product_id": product_id,
            "review_state": doc.review_state,
            "contact_id": contact.pk if contact else None,
            "ip": ip,
        },
        detail=f"{doc.title}: {contact.name if contact else company.name}",
        entity_type="tech_document",
        entity_id=doc.pk,
        company_id=company.pk,
        contact_id=contact.pk if contact else None,
    )
    name, storage = (doc.file.name, doc.file.storage) if doc.file else (None, None)
    doc.delete()
    if name:
        transaction.on_commit(lambda: storage.delete(name))
    return True


# ── Отправка на проверку ─────────────────────────────────────────────────────────────────────────────


def _unique(ids) -> list[int]:
    return list(dict.fromkeys(ids))


@transaction.atomic
def submit_for_review(*, company, contact, ids) -> tuple[list[int], list[dict]]:
    """Свои черновики и возвращённые карточки → «на проверке». Итог построчный: `(отправлено, ошибки по id)`.

    Чужая и несуществующая карточка неотличимы — `NOT_FOUND`; своя, но уже на проверке или опубликованная —
    `PRODUCT_NOT_SUBMITTABLE`. Строки блокируются на время проверки: две одновременные отправки не создают две проверки
    (ограничение `catalog_one_pending_review` — вторая страховка).
    """
    ids = _unique(ids)
    locked = {
        product.pk: product
        for product in Product.objects.select_for_update(of=("self",))
        .select_related("status")
        .filter(pk__in=ids, source_supplier_id=company.pk)
        .exclude(status__code=CODE_ARCHIVED)
    }
    review_status = ProductStatus.objects.filter(code=CODE_REVIEW).first()
    submitted, errors = [], []
    for product_id in ids:
        product = locked.get(product_id)
        if product is None:
            errors.append({"id": product_id, "code": "NOT_FOUND"})
            continue
        code = product.status.code if product.status_id else CODE_DRAFT
        if code not in (CODE_DRAFT, CODE_RETURNED) or review_status is None:
            errors.append({"id": product_id, "code": "PRODUCT_NOT_SUBMITTABLE"})
            continue
        # Висящая открытая проверка (статус меняли мимо проверки) закрывается, а не ломает отправку ограничением базы
        close_pending_review(product, ProductReview.Decision.CANCELLED)
        product.status = review_status
        product.save(update_fields=["status", "updated_at"])
        ProductReview.objects.create(product=product, submitted_by_contact=contact)
        submitted.append(product_id)
    return submitted, errors


def catalog_reviewers():
    """Кому сообщить об отправке: ответственный сотрудник отношения — иначе тем, у кого право публикации каталога."""
    from accounts.models import CustomUser

    own_id = own_company_id()
    return CustomUser.objects.filter(
        is_active=True,
        memberships__company_id=own_id,
        memberships__is_active=True,
        memberships__company_roles__permissions__contains=["catalog.publish"],
    ).distinct()


def notify_submitted(company, count: int) -> None:
    """Уведомление сотрудникам: тот же механизм, что у остальных событий портала (`notifications.services`).

    Ответственный сотрудник отношения получает его, если он есть; иначе — все с правом `catalog.publish`; никого —
    администраторы платформы. Один раз на отправку, а не на карточку.
    """
    from parties.models import CompanyRelationship, RelationshipRole

    from notifications.services import notify_platform_admins, notify_user

    if count <= 0:
        return
    title = f"Партнёр «{company.name}» отправил карточки на проверку"
    message = f"Карточек на проверке: {count}. Проверьте и опубликуйте или верните партнёру с причиной."
    params = {"company": company.name, "count": count}
    relationship = (
        CompanyRelationship.objects.filter(company=company, role=RelationshipRole.PARTNER)
        .select_related("responsible")
        .first()
    )
    recipients = (
        [relationship.responsible] if relationship and relationship.responsible_id else list(catalog_reviewers())
    )
    if not recipients:
        notify_platform_admins(
            title=title, message=message, type_code="INFO", event_code=NOTIFY_EVENT, event_params=params
        )
        return
    for user in recipients:
        notify_user(
            user=user, title=title, message=message, type_code="INFO", event_code=NOTIFY_EVENT, event_params=params
        )


# ── Подтверждение актуальности ───────────────────────────────────────────────────────────────────────


@transaction.atomic
def confirm_offers(*, company, contact, ids=None) -> dict:
    """«Подтвердить актуальность» цен компании: без модерации. `ids=None` — все цены компании.

    Цена с истёкшим сроком не подтверждается (`OFFER_EXPIRED` — нужен новый прайс); по `ids` без цены компании —
    `NOT_FOUND` (чужая карточка неотличима от несуществующей). В `expired` — сколько цен пропущено из-за срока.
    """
    today, now = timezone.localdate(), timezone.now()
    offers = SupplierOffer.objects.select_for_update(of=("self",)).filter(supplier=company, is_active=True)
    if ids is not None:
        ids = _unique(ids)
        offers = offers.filter(product_id__in=ids)
    by_product = {offer.product_id: offer for offer in offers}
    errors, confirm_pks, expired = [], [], 0
    for offer in by_product.values():
        if offer.valid_until is not None and offer.valid_until < today:
            expired += 1
            continue
        confirm_pks.append(offer.pk)
    if ids is not None:
        for product_id in ids:
            offer = by_product.get(product_id)
            if offer is None:
                errors.append({"id": product_id, "code": "NOT_FOUND"})
            elif offer.valid_until is not None and offer.valid_until < today:
                errors.append({"id": product_id, "code": "OFFER_EXPIRED"})
    if confirm_pks:
        with pghistory.context(contact=contact.pk, source="confirm"):
            SupplierOffer.objects.filter(pk__in=confirm_pks).update(confirmed_at=now, confirmed_by_contact=contact)
    return {"confirmed": len(confirm_pks), "expired": expired, "errors": errors}
