"""Buyer RFQ (заявка) service — the FREE request path.

ADR-0006 module split: the buyer's request lifecycle (build draft line items → route to seller(s)
→ submit DRAFT→RFQ_OPEN) is a SEPARATE, always-free module from the paid КП/quoting engine in
`quotes.py`. It's a leaf: no dependency on the pricing/economics/approval engine, so the paid КП
feature can be gated/toggled as an entitlement without touching the free заявка path.
"""

from django.db import models, transaction

from accounts.models import CustomUser

from ..constants import DealStageCode, QuoteStatusCode
from ..models import ActivityLog, Deal, Quote, QuoteItem, QuoteStatus
from .availability import resolve_seller_offer, split_line_by_availability
from .deals import transition_deal_stage

# The buyer may edit the request only while the deal is a DRAFT — before they submit the RFQ.
# Once the seller starts pricing (stage leaves the pre-work set) the request freezes.
# Submitting moves DRAFT → RFQ_OPEN (see submit_request), which locks the request.
REQUEST_EDITABLE_STAGES = frozenset({DealStageCode.DRAFT})


def buyer_can_edit_request(deal: Deal, user: CustomUser) -> bool:
    """True if `user` may add/edit/remove the request line items on `deal`."""
    from accounts.services.permissions import is_member_of, is_platform_admin_viewer

    if is_platform_admin_viewer(user):
        return False
    if not is_member_of(user, deal.company_id, capability="buy"):
        return False
    stage_code = deal.stage.code if deal.stage_id else None
    return stage_code in REQUEST_EDITABLE_STAGES


def _request_draft_quote(deal: Deal) -> Quote:
    """The single DRAFT quote holding the buyer's requested items (get-or-create)."""
    quote = deal.quotes.filter(status__code=QuoteStatusCode.DRAFT).order_by("version").first()
    if quote:
        return quote
    draft_status = QuoteStatus.objects.get(code=QuoteStatusCode.DRAFT)
    next_version = (deal.quotes.aggregate(m=models.Max("version"))["m"] or 0) + 1
    return Quote.objects.create(deal=deal, version=next_version, status=draft_status)


def _assert_request_editable(deal: Deal, user: CustomUser) -> None:
    from rest_framework.exceptions import PermissionDenied

    if not buyer_can_edit_request(deal, user):
        raise PermissionDenied("REQUEST_NOT_EDITABLE")


def _line_dedup_key(item: QuoteItem):
    """Identity of a request line for dedup: prefer code (mpn / ГОСТ-чертёж), else name+unit."""
    mpn = (item.mpn or "").strip().lower()
    if mpn:
        return ("mpn", mpn)
    gost = (item.gost_drawing or "").strip().lower()
    if gost:
        return ("gost", gost)
    name = (item.imported_raw_name or (item.product.name if item.product_id and item.product else "")).strip().lower()
    return ("name", name, (item.unit or "").strip().lower())


def merge_request_lines(quote: Quote, new_items: list) -> tuple:
    """Add unsaved QuoteItem rows to `quote`, deduping by mpn / ГОСТ / (name+unit)
    against existing lines AND within the batch — same item ⇒ quantities sum.
    Idempotent for re-imports. Returns (created_list, merged_count)."""
    existing = {}
    for line in quote.items.all():
        existing[_line_dedup_key(line)] = line
    created, touched, merged = [], [], 0
    for incoming in new_items:
        key = _line_dedup_key(incoming)
        if key in existing:
            existing[key].quantity += incoming.quantity
            if existing[key].pk:
                touched.append(existing[key])
            merged += 1
        else:
            existing[key] = incoming
            created.append(incoming)
    if created:
        QuoteItem.objects.bulk_create(created)
    for line in touched:
        line.save(update_fields=["quantity"])
    return created, merged


@transaction.atomic
def buyer_add_request_item(
    user: CustomUser, deal: Deal, *, name: str, quantity, unit="", unit_code="", note="", mpn=""
) -> QuoteItem:
    from rest_framework.exceptions import ValidationError

    clean_name = (name or "").strip()
    if not clean_name:
        raise ValidationError({"name": "ITEM_NAME_REQUIRED"})
    _assert_request_editable(deal, user)
    quote = _request_draft_quote(deal)
    # Lock the draft quote so concurrent adds of the same line serialize — the
    # dedup read-modify-write on `quantity` below would otherwise lose an update.
    quote = Quote.objects.select_for_update().get(pk=quote.pk)
    candidate = QuoteItem(
        quote=quote,
        imported_raw_name=clean_name,
        quantity=max(1, int(quantity or 1)),
        unit=(unit or "")[:32],
        unit_code=(unit_code or "")[:8],
        note=note or "",
        # Article (MPN) parity with the edit path — without it a new line drops the
        # article. Set before _line_dedup_key, which prefers mpn for dedup.
        mpn=(mpn or "")[:120],
    )
    # Same dedup as cart/import: re-adding an identical line sums the quantity.
    key = _line_dedup_key(candidate)
    existing = next((line for line in quote.items.all() if _line_dedup_key(line) == key), None)
    if existing:
        existing.quantity += candidate.quantity
        existing.save(update_fields=["quantity"])
        item = existing
    else:
        candidate.save()
        item = candidate
    quote.recalculate_totals()
    ActivityLog.objects.create(
        action="Добавлена позиция заявки",
        detail=f"Deal #{deal.id}: «{clean_name}» × {item.quantity}",
        user=user,
        level="INFO",
        entity_type="deal",
        entity_id=str(deal.id),
    )
    return item


@transaction.atomic
def buyer_add_request_items(user: CustomUser, deal: Deal, rows: list) -> list:
    """Bulk-add request lines — used by the catalog cart checkout. Each row is
    {product_id?, name?, quantity, unit?}. Catalog items link to the real Product
    (so the seller gets a pre-matched line), free rows fall back to imported_raw_name.
    """
    from django.utils import timezone

    from catalog.models import Product

    _assert_request_editable(deal, user)
    quote = _request_draft_quote(deal)
    # Lock the draft quote so a concurrent cart checkout / single-add doesn't
    # race the merge_request_lines read-modify-write (lost quantity update).
    quote = Quote.objects.select_for_update().get(pk=quote.pk)
    to_create = []
    for row in rows or []:
        product = None
        product_id = row.get("product_id")
        if product_id:
            product = Product.objects.select_related("uom").filter(pk=product_id).first()
        name = (row.get("name") or (product.name if product else "")).strip()
        if not (name or product):
            continue
        # A catalog line INHERITS the product's attributes (uom / MPN / ГОСТ / ТНВЭД) — the
        # Product is the single source of truth. Previously only name+qty survived the
        # cart→заявка hop, so the seller received a line with no unit/spec (owner-reported).
        # An explicit row value (free-text path) still wins where provided.
        prod_uom = product.uom if (product and product.uom_id) else None
        quantity = max(1, int(row.get("quantity") or 1))
        # Lead-time inheritance (Track B): a catalog line carries the срок from the owning
        # seller's offer so the buyer already sees a realistic delivery time; the seller may
        # later override it. Resolved via product.owner_company (the offer supplier).
        lead_time_days = 0
        if product:
            offer = resolve_seller_offer(product, product.owner_company_id)
            if offer is not None:
                tranches = split_line_by_availability(product, quantity, offer)
                lead_time_days = max((tranche.lead_time_days for tranche in tranches), default=0)
        to_create.append(
            QuoteItem(
                quote=quote,
                product=product,
                imported_raw_name="" if product else name,
                quantity=quantity,
                unit=(row.get("unit") or (prod_uom.name if prod_uom else ""))[:32],
                unit_code=(row.get("unit_code") or (prod_uom.code if prod_uom else ""))[:8],
                mpn=(product.manufacturer_part_number if product else "") or "",
                gost_drawing=(product.gost_drawing if product else "") or "",
                hs_code=(product.hs_code if product else "") or "",
                lead_time_days=lead_time_days,
                note=row.get("note") or "",
                assigned_at=timezone.now() if product else None,
            )
        )
    if to_create:
        merge_request_lines(quote, to_create)
        quote.recalculate_totals()
        ActivityLog.objects.create(
            action="Добавлены позиции заявки (корзина)",
            detail=f"Deal #{deal.id}: {len(to_create)} позиций",
            user=user,
            level="INFO",
            entity_type="deal",
            entity_id=str(deal.id),
        )
    return to_create


def buyer_update_request_item(
    user: CustomUser,
    item: QuoteItem,
    *,
    name=None,
    quantity=None,
    unit=None,
    unit_code=None,
    note=None,
    mpn=None,
    name_canonical=None,
) -> QuoteItem:
    from rest_framework.exceptions import ValidationError

    deal = item.quote.deal
    _assert_request_editable(deal, user)
    fields = []
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise ValidationError({"name": "ITEM_NAME_REQUIRED"})
        item.imported_raw_name = clean_name
        fields.append("imported_raw_name")
    # Buyer may correct the AI-import's canonical RU search key (used to re-match
    # against the cyrillic catalog) — never touches the original imported name.
    if name_canonical is not None:
        item.name_canonical = (name_canonical or "")[:500]
        fields.append("name_canonical")
    if quantity is not None:
        item.quantity = max(1, int(quantity))
        fields.append("quantity")
    if unit is not None:
        item.unit = (unit or "")[:32]
        fields.append("unit")
    if unit_code is not None:
        item.unit_code = (unit_code or "")[:8]
        fields.append("unit_code")
    if note is not None:
        item.note = note or ""
        fields.append("note")
    if mpn is not None:
        item.mpn = (mpn or "")[:120]
        fields.append("mpn")
    if fields:
        item.save(update_fields=fields)
        item.quote.recalculate_totals()
    return item


def buyer_remove_request_item(user: CustomUser, item: QuoteItem) -> None:
    deal = item.quote.deal
    _assert_request_editable(deal, user)
    quote = item.quote
    item.delete()
    quote.recalculate_totals()
    ActivityLog.objects.create(
        action="Удалена позиция заявки",
        detail=f"Deal #{deal.id}: QuoteItem #{item.id}",
        user=user,
        level="INFO",
        entity_type="deal",
        entity_id=str(deal.id),
    )


def _is_request_item_incomplete(item: QuoteItem) -> bool:
    # UBL: a line must be identified by a name OR a code (mpn / ГОСТ-чертёж) OR a product.
    return not (
        (item.imported_raw_name or "").strip()
        or (item.mpn or "").strip()
        or (item.gost_drawing or "").strip()
        or item.product_id
    )


def buyer_update_request_meta(user: CustomUser, deal: Deal, *, title=None, notes=None) -> Deal:
    """Buyer edits the request header — title + note-to-seller — while still DRAFT."""
    from rest_framework.exceptions import PermissionDenied, ValidationError

    if not buyer_can_edit_request(deal, user):
        raise PermissionDenied("REQUEST_NOT_EDITABLE")
    fields = []
    if title is not None:
        clean = title.strip()
        if not clean:
            raise ValidationError({"title": "TITLE_REQUIRED"})
        deal.title = clean[:255]
        fields.append("title")
    if notes is not None:
        deal.notes = notes
        fields.append("notes")
    if fields:
        deal.save(update_fields=fields)
    return deal


def route_deal_from_catalog(deal: Deal) -> set:
    """Upsert DealSellerRouting rows from the deal's quote-item products — the
    target seller(s) are the distinct `Product.owner_company` of the chosen catalog
    items. Idempotent. Returns the set of seller company ids routed to. Product-less
    (free-text) lines contribute nothing — those deals are routed by the buyer.
    """
    from crm.models import DealSellerRouting, QuoteItem

    seller_ids = set(
        QuoteItem.objects.filter(quote__deal=deal, product__owner_company__isnull=False)
        .values_list("product__owner_company_id", flat=True)
        .distinct()
    )
    for seller_id in seller_ids:
        DealSellerRouting.objects.get_or_create(deal=deal, seller_company_id=seller_id)
    return seller_ids


def route_request_to_sellers(user: CustomUser, deal: Deal, seller_company_ids: list) -> Deal:
    """Buyer routes a (typically free-text) заявка to chosen seller companies.

    Multi-seller routing: a free-text RFQ has no Product.owner_company to imply the
    supplier, so the buyer picks the target seller(s) explicitly. Idempotent upsert of
    DealSellerRouting rows (the through model behind Deal.target_sellers). Allowed only
    while the deal is still DRAFT — once submitted the routing is frozen.

    Guards: not a platform-admin viewer, buyer (can_buy) of the deal's own company,
    deal stage is DRAFT, and every id is an active SUPPLIER-type Company.
    """
    from rest_framework.exceptions import PermissionDenied, ValidationError

    from accounts.constants import SELLER_COMPANY_TYPES
    from accounts.models import Company
    from accounts.services.permissions import is_member_of, is_platform_admin_viewer
    from crm.models import DealSellerRouting

    if is_platform_admin_viewer(user):
        raise PermissionDenied("ADMIN_VIEWER_CANNOT_ACT")
    if not is_member_of(user, deal.company_id, capability="buy"):
        raise PermissionDenied("ONLY_BUYER_CAN_ROUTE")
    if (deal.stage.code if deal.stage_id else None) != DealStageCode.DRAFT:
        raise ValidationError({"detail": "REQUEST_ALREADY_SUBMITTED"})

    requested_ids = {int(seller_id) for seller_id in seller_company_ids}
    if not requested_ids:
        raise ValidationError({"detail": "NO_SELLERS_SELECTED"})

    # NB: Company has no is_active flag (only CompanyMember does). A company is
    # "active as a seller" iff it carries a SUPPLIER CompanyType — same gate the
    # rest of the codebase uses (core.permissions, catalog offers, contracts).
    valid_ids = set(
        Company.objects.filter(
            id__in=requested_ids,
            types__code__in=SELLER_COMPANY_TYPES,
        )
        .distinct()
        .values_list("id", flat=True)
    )
    if valid_ids != requested_ids:
        raise ValidationError({"detail": "NOT_A_SELLER_COMPANY"})

    for seller_id in valid_ids:
        DealSellerRouting.objects.get_or_create(deal=deal, seller_company_id=seller_id)

    ActivityLog.objects.create(
        action="Заявка адресована продавцам (RFQ routing)",
        detail=f"Deal #{deal.id}: {len(valid_ids)} продавцов",
        user=user,
        level="INFO",
        entity_type="deal",
        entity_id=str(deal.id),
    )
    return deal


def submit_request(user: CustomUser, deal: Deal) -> Deal:
    """Buyer issues the RFQ to the seller — the explicit «Отправить заявку» step.

    World-standard RFQ lifecycle: Draft → SUBMIT → seller quotes → accept/reject.
    Guards: buyer with can_buy, deal still DRAFT, ≥1 line, and NO incomplete lines
    (the data-quality gate). On success the deal moves DRAFT → RFQ_OPEN via the FSM
    and the buyer's request locks for editing.
    """
    from rest_framework.exceptions import PermissionDenied, ValidationError

    from accounts.services.kyc import company_kyc_verified
    from accounts.services.permissions import is_member_of, is_platform_admin_viewer

    if is_platform_admin_viewer(user):
        raise PermissionDenied("ADMIN_VIEWER_CANNOT_ACT")
    if not is_member_of(user, deal.company_id, capability="buy"):
        raise PermissionDenied("ONLY_BUYER_CAN_SUBMIT_REQUEST")
    # ADR-0006 Phase E — KYC floor: «после KYC = минимум». Browsing + building a DRAFT заявка is
    # free, but SUBMITTING it to sellers requires a KYC-verified (L2+) company. This is the first
    # real backend gate on verification (it was FE-cosmetic only — the Layer-0 gap).
    if not company_kyc_verified(deal.company_id):
        raise PermissionDenied("KYC_REQUIRED_TO_SUBMIT")
    if (deal.stage.code if deal.stage_id else None) != DealStageCode.DRAFT:
        raise ValidationError({"detail": "REQUEST_ALREADY_SUBMITTED"})

    quote = deal.quotes.filter(status__code=QuoteStatusCode.DRAFT).order_by("version").first()
    items = list(quote.items.all()) if quote else []
    if not items:
        raise ValidationError({"detail": "REQUEST_EMPTY"})
    if any(_is_request_item_incomplete(item) for item in items):
        raise ValidationError({"detail": "REQUEST_HAS_INCOMPLETE_ITEMS"})

    # Route the RFQ to the seller(s) whose catalog products the buyer chose — the
    # supplier is implied by Product.owner_company (world-standard marketplace RFQ).
    # Free-text-only заявки stay unrouted here; the buyer routes them explicitly.
    route_deal_from_catalog(deal)

    # An RFQ MUST reach at least one seller. A free-text/manually-typed заявка produces
    # no Product.owner_company routing, so without an explicit buyer routing this would
    # advance to RFQ_OPEN visible to NO seller, while the buyer is told «Менеджер готовит
    # КП» — a silent dead-end (audit F2). Mirror the NO_SELLERS_SELECTED guard the /route
    # endpoint already enforces so both paths uphold the same ≥1-recipient invariant.
    if not deal.seller_routings.exists():
        raise ValidationError({"detail": "NO_RECIPIENTS"})

    deal, error = transition_deal_stage(deal, DealStageCode.RFQ_OPEN, actor=user)
    if error:
        raise ValidationError({"detail": error})
    ActivityLog.objects.create(
        action="Заявка отправлена поставщику (RFQ)",
        detail=f"Deal #{deal.id}: {len(items)} позиций",
        user=user,
        level="INFO",
        entity_type="deal",
        entity_id=str(deal.id),
    )
    return deal
