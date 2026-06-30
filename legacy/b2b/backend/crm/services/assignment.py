"""Deal ownership / work-queue (ADR-0006 Move 2).

World-standard, team-size-agnostic ownership: a routed seller team sees its заявки as a shared
work-queue; a member CLAIMS one to own it (claim-lock prevents a race), an admin can ASSIGN it,
and either can RELEASE it back to the queue. This replaces the "everyone stares at one shared
pile, processed serially" anti-pattern — it scales from a 1-person to an N-person team without a
hard-coded routing rule (the owner's "5 people" was an illustration, not a spec).

Thin services (Rule 8); the viewset is a wrapper. Ownership is seller-side and bound to the deal's
routing (a member can only claim a deal routed to their company — no cross-tenant grab).
"""

from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from accounts.models import CustomUser

from ..models import Deal


def _seller_may_act_on_deal(actor: CustomUser, deal_id: int) -> bool:
    """True if `actor` is a seller routed to this deal (or superuser) — the claim/own gate."""
    from accounts.services import is_seller, seller_company_routed_to_deal

    if getattr(actor, "is_superuser", False):
        return True
    return is_seller(actor) and seller_company_routed_to_deal(actor, deal_id)


@transaction.atomic
def claim_deal(deal_id: int, actor: CustomUser) -> Tuple[Optional[Deal], Optional[str]]:
    """A routed seller-team member takes ownership of an unclaimed deal (pull from the queue).
    Claim-lock: select_for_update serialises concurrent claims so two members can't both win."""
    from accounts.services import is_platform_admin_viewer

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    deal = Deal.objects.select_for_update().filter(pk=deal_id).first()
    if deal is None:
        return None, "DEAL_NOT_FOUND"
    if not _seller_may_act_on_deal(actor, deal_id):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if deal.assigned_to_id and deal.assigned_to_id != actor.id:
        return None, "DEAL_ALREADY_CLAIMED"  # someone else owns it — release/reassign first
    deal.assigned_to = actor
    deal.assigned_at = timezone.now()
    deal.save(update_fields=["assigned_to", "assigned_at", "updated_at"])
    _log(deal, actor, "Заявка взята в работу", f"{actor.email} взял заявку #{deal_id}")
    return deal, None


@transaction.atomic
def release_deal(deal_id: int, actor: CustomUser) -> Tuple[Optional[Deal], Optional[str]]:
    """Return a deal to the shared queue (the current owner, or an admin with team.manage)."""
    from accounts.services import is_platform_admin_viewer, member_has_permission

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    deal = Deal.objects.select_for_update().filter(pk=deal_id).first()
    if deal is None:
        return None, "DEAL_NOT_FOUND"
    is_owner = deal.assigned_to_id == actor.id
    can_manage = any(
        member_has_permission(actor, m.seller_company_id, "team.manage")
        for m in deal.seller_routings.all()
    )
    if not (getattr(actor, "is_superuser", False) or is_owner or can_manage):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    deal.assigned_to = None
    deal.assigned_at = None
    deal.save(update_fields=["assigned_to", "assigned_at", "updated_at"])
    _log(deal, actor, "Заявка возвращена в очередь", f"{actor.email} освободил заявку #{deal_id}")
    return deal, None


@transaction.atomic
def assign_deal(deal_id: int, actor: CustomUser, assignee_id: int) -> Tuple[Optional[Deal], Optional[str]]:
    """A company admin (team.manage on a routed seller company) assigns the deal to a member.
    The assignee must belong to one of the deal's routed seller companies (no cross-tenant)."""
    from accounts.services import is_platform_admin_viewer, member_has_permission

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    deal = Deal.objects.select_for_update().filter(pk=deal_id).first()
    if deal is None:
        return None, "DEAL_NOT_FOUND"
    routed_company_ids = list(deal.seller_routings.values_list("seller_company_id", flat=True))
    can_manage = getattr(actor, "is_superuser", False) or any(
        member_has_permission(actor, cid, "team.manage") for cid in routed_company_ids
    )
    if not can_manage:
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    assignee = CustomUser.objects.filter(pk=assignee_id).first()
    if assignee is None:
        return None, "ASSIGNEE_NOT_FOUND"
    if not assignee.memberships.filter(is_active=True, company_id__in=routed_company_ids).exists():
        return None, "ASSIGNEE_NOT_IN_ROUTED_COMPANY"
    deal.assigned_to = assignee
    deal.assigned_at = timezone.now()
    deal.save(update_fields=["assigned_to", "assigned_at", "updated_at"])
    _notify_assignee(deal, assignee)
    _log(deal, actor, "Заявка назначена", f"{actor.email} назначил заявку #{deal_id} → {assignee.email}")
    return deal, None


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
    push_notification_ws(notif)


def _log(deal: Deal, actor: CustomUser, action: str, detail: str) -> None:
    from ..models import ActivityLog

    ActivityLog.objects.create(action=action, detail=detail, user=actor, level="INFO", entity_type="deal", entity_id=deal.pk)
