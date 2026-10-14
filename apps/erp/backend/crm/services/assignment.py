"""Deal ownership / work-queue of the back office (ADR-0006 Move 2).

The seller of every deal is the own company (BUSINESS §3.3 — ERP is not a marketplace), so a deal
has ONE owner: `Deal.assigned_to` (+ `assigned_at`, the time-to-first-touch SLA anchor). NULL =
unclaimed, sitting in the team's shared queue; a staff member claims it, releases it back, or a
team admin (`team.manage`) assigns it to a colleague. Each function returns the Deal (the viewset
serializes it).

Thin services (Rule 8); the viewset is a wrapper.
"""

from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from accounts.models import CustomUser

from ..models import Deal


def assign_creator_as_owner(deal: Deal, actor: CustomUser) -> None:
    """Wave E F1 — a deal a staff member opened for their own offline client (or a company-less
    calculator draft) is «taken in work» by its creator from the start, so `claim_deal` is a no-op
    success for them and a teammate can still `release`/`assign` it. No-op for non-staff (a
    buyer-initiated request lands unclaimed in the back-office queue) and for an already-owned deal.
    """
    from accounts.services import is_seller

    if deal.assigned_to_id or not is_seller(actor):
        return
    deal.assigned_to = actor
    deal.assigned_at = timezone.now()
    deal.save(update_fields=["assigned_to", "assigned_at"])


def _locked_deal(deal_id: int) -> Optional[Deal]:
    """The deal row under select_for_update — serialises concurrent claims/releases."""
    return Deal.objects.select_for_update().filter(pk=deal_id).first()


@transaction.atomic
def claim_deal(deal_id: int, actor: CustomUser) -> Tuple[Optional[Deal], Optional[str]]:
    """A staff member claims the заявка (pull from the shared queue). The row lock serialises
    concurrent claims so two teammates can't both win."""
    from accounts.services import is_seller

    if not is_seller(actor):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    deal = _locked_deal(deal_id)
    if deal is None:
        return None, "DEAL_NOT_FOUND"
    if deal.assigned_to_id and deal.assigned_to_id != actor.id:
        return None, "DEAL_ALREADY_CLAIMED"  # a teammate owns it — release first
    if deal.assigned_to_id == actor.id:
        return deal, None  # already owned by this member — no-op (keep the assigned_at SLA anchor)
    deal.assigned_to = actor
    deal.assigned_at = timezone.now()
    deal.save(update_fields=["assigned_to", "assigned_at"])
    _log(
        deal_id,
        actor,
        "Заявка взята в работу",
        f"{actor.email} взял заявку #{deal_id}",
        company_id=deal.company_id,
        event_code="deal.claimed",
        event_params={"actor_email": actor.email, "deal_id": deal_id},
    )
    return deal, None


def _may_manage_queue(actor: CustomUser) -> bool:
    """Administrator, or a staff member holding `team.manage` in the own company."""
    from accounts.services import member_has_permission, primary_seller_company_id

    if getattr(actor, "is_superuser", False):
        return True
    company_id = primary_seller_company_id(actor)
    return bool(company_id) and member_has_permission(actor, company_id, "deal.assign")


@transaction.atomic
def release_deal(deal_id: int, actor: CustomUser) -> Tuple[Optional[Deal], Optional[str]]:
    """Return the deal to the shared queue — the current owner, or an admin with team.manage."""
    from accounts.services import is_seller

    if not (getattr(actor, "is_superuser", False) or is_seller(actor)):
        return None, "DEAL_NOT_FOUND"
    deal = _locked_deal(deal_id)
    if deal is None:
        return None, "DEAL_NOT_FOUND"
    if deal.assigned_to_id is None:
        return deal, None  # already in the queue — no-op
    if deal.assigned_to_id != actor.id and not _may_manage_queue(actor):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    deal.assigned_to = None
    deal.assigned_at = None
    deal.save(update_fields=["assigned_to", "assigned_at"])
    _log(
        deal_id,
        actor,
        "Заявка возвращена в очередь",
        f"{actor.email} освободил заявку #{deal_id}",
        company_id=deal.company_id,
        event_code="deal.released",
        event_params={"actor_email": actor.email, "deal_id": deal_id},
    )
    return deal, None


@transaction.atomic
def assign_deal(deal_id: int, actor: CustomUser, assignee_id: int) -> Tuple[Optional[Deal], Optional[str]]:
    """A team admin (team.manage in the own company) assigns the deal to a colleague — an active
    member of the own company; never to an outsider (a client account or a foreign company)."""
    from accounts.services import is_seller

    assignee = CustomUser.objects.filter(pk=assignee_id).first()
    if assignee is None:
        return None, "ASSIGNEE_NOT_FOUND"
    if not _may_manage_queue(actor):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    deal = _locked_deal(deal_id)
    if deal is None:
        return None, "DEAL_NOT_FOUND"
    if not is_seller(assignee):
        return None, "ASSIGNEE_NOT_IN_OWN_COMPANY"
    deal.assigned_to = assignee
    deal.assigned_at = timezone.now()
    deal.save(update_fields=["assigned_to", "assigned_at"])
    _notify_assignee(deal, assignee)
    _log(
        deal_id,
        actor,
        "Заявка назначена",
        f"{actor.email} назначил заявку #{deal_id} → {assignee.email}",
        company_id=deal.company_id,
        event_code="deal.assigned",
        event_params={"actor_email": actor.email, "deal_id": deal_id, "assignee_email": assignee.email},
    )
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
        event_code="deal.assigned",
        event_params={"deal_id": deal.pk},
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
