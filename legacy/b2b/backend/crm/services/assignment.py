"""Deal ownership / work-queue (ADR-0006 Move 2) — PER SELLER COMPANY.

Competition between routed sellers is HIDDEN: each routed seller works the заявка independently and
the buyer picks a winner at the end. So ownership lives on DealSellerRouting (one row per
deal+seller_company), NOT a single Deal-level FK — seller A claiming must NOT block seller B from
owning their own copy of the same RFQ. A member may act ONLY on the routing of their OWN seller
company (no cross-tenant grab). Each function returns the Deal (the viewset serializes it).

Thin services (Rule 8); the viewset is a wrapper.
"""

from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from accounts.models import CustomUser

from ..models import Deal, DealSellerRouting


def _actor_seller_company_ids(actor: CustomUser) -> set:
    """Active seller (can_sell) company ids the actor belongs to."""
    return set(actor.memberships.filter(is_active=True, can_sell=True).values_list("company_id", flat=True))


def ensure_creator_seller_routing(deal: Deal, actor: CustomUser) -> Optional[DealSellerRouting]:
    """Wave E F1 — the keystone of the SELLER-OWNED deal (offline contact / company-less
    calculator draft).

    Seller visibility is ROUTING-ONLY (`seller_visible_deal_ids`): without a
    DealSellerRouting row a deal the seller just created for their own offline client is
    invisible to its own creator — they cannot claim it, build a КП, or send it. The buyer
    path gets its routing rows from `submit_request` / `route_request_to_sellers`; the
    seller-initiated path had none. This writes the missing row.

    Scoped, never widening: the row is created for the ACTOR'S OWN primary seller company
    only, so no other tenant gains visibility. Idempotent (the unique constraint on
    deal+seller_company is the real guard). The creator is also the owner from the start —
    a deal you opened for your own client is already «taken in work» — so `claim_deal`
    degenerates to a no-op success for them and a teammate can still `release`/`assign` it.
    Returns None when the actor has no seller company (buyer-initiated deals are unaffected).
    """
    from accounts.services.permissions import primary_seller_company_id

    seller_company_id = primary_seller_company_id(actor)
    if not seller_company_id:
        return None
    routing, _created = DealSellerRouting.objects.get_or_create(
        deal=deal,
        seller_company_id=seller_company_id,
        defaults={"assigned_to": actor, "assigned_at": timezone.now()},
    )
    return routing


@transaction.atomic
def claim_deal(deal_id: int, actor: CustomUser) -> Tuple[Optional[Deal], Optional[str]]:
    """A routed seller-team member claims THEIR company's copy of the заявка (pull from the queue).
    Per-company claim-lock: select_for_update on the routing row serialises concurrent claims so two
    members of the same company can't both win; a different company's claim is independent."""
    from accounts.services import is_platform_admin_viewer, is_seller, seller_company_routed_to_deal

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    if not (is_seller(actor) and seller_company_routed_to_deal(actor, deal_id)):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    routing = (
        DealSellerRouting.objects.select_for_update()
        .select_related("deal")
        .filter(deal_id=deal_id, seller_company_id__in=_actor_seller_company_ids(actor))
        .first()
    )
    if routing is None:
        return None, "DEAL_NOT_FOUND"  # not routed to the actor's company
    if routing.assigned_to_id and routing.assigned_to_id != actor.id:
        return None, "DEAL_ALREADY_CLAIMED"  # a teammate owns this company's copy — release first
    if routing.assigned_to_id == actor.id:
        return routing.deal, None  # already owned by this member — no-op (keep the assigned_at SLA anchor)
    routing.assigned_to = actor
    routing.assigned_at = timezone.now()
    routing.save(update_fields=["assigned_to", "assigned_at"])
    _log(
        deal_id,
        actor,
        "Заявка взята в работу",
        f"{actor.email} взял заявку #{deal_id}",
        company_id=routing.deal.company_id,
        event_code="deal.claimed",
        event_params={"actor_email": actor.email, "deal_id": deal_id},
    )
    return routing.deal, None


@transaction.atomic
def release_deal(deal_id: int, actor: CustomUser) -> Tuple[Optional[Deal], Optional[str]]:
    """Return the actor's OWN company's copy to that company's shared queue — the current owner, or
    an admin with team.manage on that seller company. Never touches a competitor seller's routing."""
    from accounts.services import is_platform_admin_viewer, member_has_permission

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    routings = list(
        DealSellerRouting.objects.select_for_update()
        .select_related("deal")
        .filter(deal_id=deal_id, seller_company_id__in=_actor_seller_company_ids(actor))
    )
    if not routings:
        return None, "DEAL_NOT_FOUND"
    target = next(
        (
            r
            for r in routings
            if r.assigned_to_id == actor.id
            or getattr(actor, "is_superuser", False)
            or member_has_permission(actor, r.seller_company_id, "team.manage")
        ),
        None,
    )
    if target is None:
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if target.assigned_to_id is None:
        return target.deal, None  # already in this company's queue — no-op
    target.assigned_to = None
    target.assigned_at = None
    target.save(update_fields=["assigned_to", "assigned_at"])
    _log(
        deal_id,
        actor,
        "Заявка возвращена в очередь",
        f"{actor.email} освободил заявку #{deal_id}",
        company_id=target.deal.company_id,
        event_code="deal.released",
        event_params={"actor_email": actor.email, "deal_id": deal_id},
    )
    return target.deal, None


@transaction.atomic
def assign_deal(deal_id: int, actor: CustomUser, assignee_id: int) -> Tuple[Optional[Deal], Optional[str]]:
    """A company admin (team.manage on a routed seller company) assigns the deal to a member of THAT
    SAME company. Scoped per routing — an admin can neither assign on a competitor's routing nor
    assign to a member outside their own company."""
    from accounts.services import is_platform_admin_viewer, member_has_permission

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    assignee = CustomUser.objects.filter(pk=assignee_id).first()
    if assignee is None:
        return None, "ASSIGNEE_NOT_FOUND"
    managed = [
        r
        for r in DealSellerRouting.objects.select_for_update().select_related("deal").filter(deal_id=deal_id)
        if getattr(actor, "is_superuser", False) or member_has_permission(actor, r.seller_company_id, "team.manage")
    ]
    if not managed:
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    target = next(
        (r for r in managed if assignee.memberships.filter(is_active=True, company_id=r.seller_company_id).exists()),
        None,
    )
    if target is None:
        return None, "ASSIGNEE_NOT_IN_ROUTED_COMPANY"
    target.assigned_to = assignee
    target.assigned_at = timezone.now()
    target.save(update_fields=["assigned_to", "assigned_at"])
    _notify_assignee(target.deal, assignee)
    _log(
        deal_id,
        actor,
        "Заявка назначена",
        f"{actor.email} назначил заявку #{deal_id} → {assignee.email}",
        company_id=target.deal.company_id,
        event_code="deal.assigned",
        event_params={"actor_email": actor.email, "deal_id": deal_id, "assignee_email": assignee.email},
    )
    return target.deal, None


def _notify_assignee(deal: Deal, assignee: CustomUser) -> None:
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    info = NotificationType.objects.filter(code="INFO").first()
    notif = Notification.objects.create(
        user=assignee,
        type=info,
        title="Вам назначена заявка",
        message=f"Заявка #{deal.pk} назначена вам — нужен КП",
        link=f"/crm/deals/{deal.pk}",
        deal=deal,
    )
    # Defer the WS push until the surrounding transaction commits (codebase on_commit convention) —
    # never announce a notification id that a rollback would delete.
    transaction.on_commit(lambda: push_notification_ws(notif))
    # W1 (spec-inbound-rfq): the addressed assignment also lands by EMAIL — the assignee may be
    # offline, and «вам назначена заявка» is exactly the message that must not wait for a login.
    from notifications.signals import notify_new_rfq_by_email

    notify_new_rfq_by_email(deal, [assignee.pk], assigned=True)


def _log(
    deal_id: int,
    actor: CustomUser,
    action: str,
    detail: str,
    company_id: Optional[int] = None,
    event_code: str = "",
    event_params: Optional[dict] = None,
) -> None:
    from ..models import ActivityLog

    ActivityLog.objects.create(
        action=action,
        detail=detail,
        event_code=event_code,
        event_params=event_params or {},
        user=actor,
        level="INFO",
        entity_type="deal",
        entity_id=deal_id,
        deal_id=deal_id,
        company_id=company_id,
    )
