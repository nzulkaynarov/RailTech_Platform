from typing import Optional, Tuple

from django.db import transaction

from accounts.models import CustomUser

from ..models import Deal
from ._params import BidSubmission
from .deals import transition_deal_stage


@transaction.atomic
def submit_supplier_bid(
    deal_id,
    supplier_id: Optional[int] = None,
    submitted_by: Optional[CustomUser] = None,
    items: Optional[list[dict]] = None,
    notes: str = "",
    lead_time_days: Optional[int] = None,
    currency_id: Optional[int] = None,
) -> Tuple[Optional[object], Optional[str]]:
    """Create or update a SupplierBid for the given deal+supplier.

    Callers pass deal_id + supplier_id (+ items, ...). A BidSubmission dataclass
    may also be passed as the first positional argument; its fields are unpacked.
    """
    # Unpack a BidSubmission passed as the first positional argument.
    if isinstance(deal_id, BidSubmission):
        bs = deal_id
        deal_id = bs.deal_id
        supplier_id = bs.supplier_id
        items = bs.items
        notes = bs.notes
        lead_time_days = bs.lead_time_days
        currency_id = bs.currency_id
    if items is None:
        items = []

    from decimal import Decimal as D

    from django.utils import timezone

    from accounts.services import company_has_operational_subscription, is_member_of, is_platform_admin_viewer

    from ..models import SupplierBid, SupplierBidItem

    if is_platform_admin_viewer(submitted_by):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    deal = Deal.objects.get(pk=deal_id)
    if deal.stage and deal.stage.code not in {"RFQ_OPEN"}:
        return None, "BID_ONLY_IN_RFQ_OPEN"
    is_superuser = getattr(submitted_by, "is_superuser", False)
    # Security: user must be active member of the supplier company with can_sell.
    if not (is_superuser or is_member_of(submitted_by, supplier_id, capability="sell")):
        return None, "NOT_A_SUPPLIER_MEMBER"
    # Feature gate: supplier company must have an operational subscription.
    # Superusers bypass for emergency fixes only — flagged in the audit log below.
    subscription_ok = company_has_operational_subscription(supplier_id)
    if not (is_superuser or subscription_ok):
        return None, "SUBSCRIPTION_NOT_OPERATIONAL"
    superuser_bypass = is_superuser and not subscription_ok
    bid, _ = SupplierBid.objects.get_or_create(deal_id=deal_id, supplier_id=supplier_id)
    bid.items.all().delete()
    total = D("0")
    for row in items:
        qty = int(row.get("quantity", 1) or 1)
        price = D(str(row.get("unit_price", 0) or 0))
        if qty <= 0 or price < 0:
            return None, "BID_ITEM_INVALID_AMOUNT"
        SupplierBidItem.objects.create(
            bid=bid,
            quote_item_id=row.get("quote_item_id"),
            product_id=row.get("product_id"),
            description=row.get("description", ""),
            quantity=qty,
            unit_price=price,
            lead_time_days=row.get("lead_time_days"),
        )
        total += price * qty
    bid.submitted_by = submitted_by
    bid.status = "SUBMITTED"
    bid.submitted_at = timezone.now()
    bid.total_amount = total
    bid.lead_time_days = lead_time_days
    if currency_id:
        bid.currency_id = currency_id
    bid.notes = notes
    bid.save()

    # Audit -- log to BOTH the bid itself and the parent deal so admin timeline
    # on a deal surfaces supplier actions.
    from core.audit import log_admin_action

    bypass_marker = "[SUPERUSER_BYPASS] " if superuser_bypass else ""
    snapshot = {
        "status": bid.status,
        "total_amount": str(bid.total_amount),
        "lead_time_days": bid.lead_time_days,
        "items_count": bid.items.count(),
        "superuser_subscription_bypass": superuser_bypass,
    }
    log_admin_action(
        entity_type="supplier_bid",
        entity_id=bid.id,
        action=f"{bypass_marker}SupplierBid submitted",
        detail=f"Deal #{deal_id} · supplier #{supplier_id} · {bid.total_amount}",
        actor=submitted_by,
        after=snapshot,
        level="WARNING" if superuser_bypass else "INFO",
    )
    log_admin_action(
        entity_type="deal",
        entity_id=deal_id,
        action=f"SupplierBid #{bid.id} submitted",
        detail=f"supplier #{supplier_id} · {bid.total_amount}",
        actor=submitted_by,
        after=snapshot,
        level="INFO",
    )
    return bid, None


@transaction.atomic
def accept_supplier_bid(
    bid_id: int,
    actor: CustomUser,
) -> Tuple[Optional[object], Optional[str]]:
    from django.utils import timezone

    from ..models import SupplierBid

    bid = SupplierBid.objects.select_for_update().select_related("deal").get(pk=bid_id)
    if bid.status != "SUBMITTED":
        return None, "BID_ACCEPT_NOT_ALLOWED"
    before_status = bid.status
    bid.status = "ACCEPTED"
    bid.accepted_at = timezone.now()
    bid.save(update_fields=["status", "accepted_at", "updated_at"])
    # Reject competitors
    rejected_count = (
        SupplierBid.objects.filter(deal=bid.deal)
        .exclude(pk=bid.pk)
        .filter(
            status="SUBMITTED",
        )
        .update(status="REJECTED")
    )
    transition_deal_stage(bid.deal, "CALCULATING", actor=actor, reason=f"Принят bid #{bid.id}")

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="supplier_bid",
        entity_id=bid.id,
        action="SupplierBid accepted",
        detail=f"Deal #{bid.deal_id} · rejected {rejected_count} competing bid(s)",
        actor=actor,
        before={"status": before_status},
        after={"status": "ACCEPTED"},
        level="SUCCESS",
    )
    log_admin_action(
        entity_type="deal",
        entity_id=bid.deal_id,
        action=f"SupplierBid #{bid.id} accepted",
        detail=f"competing bids auto-rejected: {rejected_count}",
        actor=actor,
        after={"status": "ACCEPTED"},
        level="SUCCESS",
    )
    return bid, None


@transaction.atomic
def reject_supplier_bid(
    bid_id: int,
    actor: CustomUser,
    reason: str = "",
) -> Tuple[Optional[object], Optional[str]]:
    from ..models import SupplierBid

    bid = SupplierBid.objects.select_for_update().get(pk=bid_id)
    if bid.status not in {"SUBMITTED", "DRAFT"}:
        return None, "BID_REJECT_NOT_ALLOWED"
    before_status = bid.status
    bid.status = "REJECTED"
    if reason:
        bid.notes = f"{bid.notes}\nОтклонено: {reason}".strip()
    bid.save(update_fields=["status", "notes", "updated_at"])

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="supplier_bid",
        entity_id=bid.id,
        action="SupplierBid rejected",
        detail=f"Deal #{bid.deal_id} · supplier #{bid.supplier_id}",
        actor=actor,
        reason=reason,
        before={"status": before_status},
        after={"status": "REJECTED"},
        level="WARNING",
    )
    log_admin_action(
        entity_type="deal",
        entity_id=bid.deal_id,
        action=f"SupplierBid #{bid.id} rejected",
        detail=f"supplier #{bid.supplier_id}",
        actor=actor,
        reason=reason,
        level="WARNING",
    )
    return bid, None
