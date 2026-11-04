"""Очередь проверки карточек партнёров (PART-3, ADR-0022 п. 4): кто ждёт решения, срок и возврат партнёру.

В очереди — карточки со статусом «на проверке» (партнёр отправил черновик или возвращённую карточку) и карточки с открытыми
предложениями полей от партнёров (правка опубликованной карточки из кабинета). Старые сверху. Срок ответа — 1 рабочий день:
своего календаря компании в ERP нет, поэтому 24 часа, часы субботы и воскресенья не считаются.

«Опубликовать» — существующая `catalog.publishing.publish_product` (порог полноты, документ категории, право
`catalog.publish`): она же закрывает проверку решением «опубликована». «Вернуть партнёру» — здесь: статус → «возвращена»,
проверка закрывается решением «возвращена» с общим комментарием и замечаниями по полям, партнёру уходит письмо.

Эталоны: Ozon Seller и Wildberries (модерация: причина у поля, срок), SAP Ariba и Coupa (одобрение каталога поставщика
покупателем), Akeneo (workflow approval: предложения по полям).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Min, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Product, ProductFieldProposal, ProductReview, ProductStatus
from .models.reviews import ISSUE_FIELDS, clean_issues
from .review_flow import close_pending_review

#: Срок ответа партнёру: сутки рабочего времени (выходные не считаются).
REVIEW_SLA = timedelta(hours=24)
CODE_REVIEW = "REVIEW"
CODE_RETURNED = "RETURNED"
MAX_REASON = 2000
#: Общий комментарий, когда сотрудник указал только замечания по полям (причина возврата обязательна — ограничение базы).
ISSUES_ONLY_REASON = "Исправьте поля, отмеченные в карточке."


class ReviewError(Exception):
    """Отказ решения: `code` — машинный код ответа `{"detail": КОД}`."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def due_at(submitted_at: datetime) -> datetime:
    """Когда истекает срок ответа: 24 часа, часы субботы и воскресенья (по времени компании) не считаются."""
    tz = timezone.get_current_timezone()
    moment = timezone.localtime(submitted_at, tz)
    remaining = REVIEW_SLA
    while True:
        if moment.weekday() >= 5:
            monday = moment + timedelta(days=7 - moment.weekday())
            moment = monday.replace(hour=0, minute=0, second=0, microsecond=0)
            continue
        midnight = (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        free = midnight - moment
        if remaining <= free:
            return moment + remaining
        remaining -= free
        moment = midnight


def is_overdue(submitted_at: datetime, now: datetime | None = None) -> bool:
    return (now or timezone.now()) > due_at(submitted_at)


_PARTNER_PROPOSAL = Q(
    field_proposals__status=ProductFieldProposal.Status.PENDING, field_proposals__contact__isnull=False
)


def waiting_queryset(queryset):
    """Карточки очереди с `waiting_since` — временем отправки (старые сверху): открытая проверка, иначе первое предложение партнёра."""
    since = Min("reviews__submitted_at", filter=Q(reviews__decision=ProductReview.Decision.PENDING))
    proposal_since = Min("field_proposals__created_at", filter=_PARTNER_PROPOSAL)
    return (
        queryset.annotate(_review_since=since, _proposal_since=proposal_since)
        .filter(Q(status__code=CODE_REVIEW) | Q(_proposal_since__isnull=False))
        .annotate(waiting_since=Coalesce("_review_since", "_proposal_since", "updated_at"))
        .order_by("waiting_since", "id")
    )


def queue_info(products) -> dict[int, dict]:
    """`{id карточки: {kind, partner, submitted_at, due_at, overdue}}` для страницы очереди: два запроса на страницу.

    `kind` — `card` (карточка на проверке) или `changes` (предложения партнёра к опубликованной). Партнёр карточки —
    источник данных; у предложений — компания, приславшая самое раннее.
    """
    products = list(products)
    ids = [product.pk for product in products]
    proposals = (
        ProductFieldProposal.objects.filter(
            product_id__in=ids, status=ProductFieldProposal.Status.PENDING, contact__isnull=False
        )
        .select_related("supplier")
        .order_by("created_at", "id")
    )
    first_proposal: dict[int, ProductFieldProposal] = {}
    for proposal in proposals:
        first_proposal.setdefault(proposal.product_id, proposal)
    now = timezone.now()
    out: dict[int, dict] = {}
    for product in products:
        on_review = getattr(product.status, "code", None) == CODE_REVIEW
        since = getattr(product, "waiting_since", None) or product.updated_at
        proposal = first_proposal.get(product.pk)
        partner = product.source_supplier if on_review else (proposal.supplier if proposal else None)
        out[product.pk] = {
            "kind": "card" if on_review else "changes",
            "partner": {"id": partner.pk, "name": partner.name} if partner else None,
            "submitted_at": since,
            "due_at": due_at(since),
            "overdue": is_overdue(since, now),
        }
    return out


def clean_return(reason, issues) -> tuple[str, list[dict]]:
    """Тело возврата → `(общий комментарий, замечания по полям)`; нужна хотя бы одна причина, поля — из перечня карточки."""
    text = str(reason or "").strip()
    if len(text) > MAX_REASON:
        raise ReviewError("REVIEW_REASON_TOO_LONG")
    try:
        cleaned = clean_issues(issues)
    except ValueError:
        raise ReviewError("REVIEW_ISSUES_INVALID") from None
    if not text and not cleaned:
        raise ReviewError("REVIEW_REASON_REQUIRED")
    return text or ISSUES_ONLY_REASON, cleaned


@transaction.atomic
def return_to_partner(product_id: int, actor, reason, issues) -> Product:
    """Вернуть карточку партнёру: «на проверке» → «возвращена», проверка закрывается решением «возвращена».

    Карточка блокируется на время решения: два сотрудника не вернут её дважды, а решение по уже опубликованной,
    возвращённой или не отправленной карточке — 409 `PRODUCT_NOT_ON_REVIEW`. Право — то же, что у публикации.
    """
    from .publishing import can_manage

    text, cleaned = clean_return(reason, issues)
    product = (
        Product.objects.select_for_update(of=("self",))
        .select_related("status", "source_supplier")
        .filter(pk=product_id)
        .first()
    )
    if product is None:
        raise ReviewError("NOT_FOUND")
    if not can_manage(actor, product, permission="catalog.publish"):
        raise ReviewError("PRODUCT_NOT_YOURS")
    if getattr(product.status, "code", None) != CODE_REVIEW:
        raise ReviewError("PRODUCT_NOT_ON_REVIEW")
    returned = ProductStatus.objects.filter(code=CODE_RETURNED).first()
    if returned is None:
        raise ReviewError("PRODUCT_STATUS_MISSING")
    product.status = returned
    product.save(update_fields=["status", "updated_at"])
    closed = close_pending_review(product, ProductReview.Decision.RETURNED, actor, reason=text, field_issues=cleaned)
    if not closed:
        # Карточку перевели в «на проверке» мимо кабинета (нет открытой проверки): решение всё равно остаётся в истории
        ProductReview.objects.create(
            product=product,
            decision=ProductReview.Decision.RETURNED,
            reason=text,
            field_issues=cleaned,
            decided_by=actor if getattr(actor, "pk", None) else None,
            decided_at=timezone.now(),
        )
    return product


__all__ = [
    "ISSUE_FIELDS",
    "ReviewError",
    "clean_return",
    "due_at",
    "is_overdue",
    "queue_info",
    "return_to_partner",
    "waiting_queryset",
]
