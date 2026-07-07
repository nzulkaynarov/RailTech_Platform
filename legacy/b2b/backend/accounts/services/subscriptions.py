import logging
from typing import Optional, Tuple

from django.db.models import QuerySet
from django.utils import timezone

from ..models import Company, CustomUser, SupplierSubscription
from .permissions import is_member_of, is_platform_admin_viewer

logger = logging.getLogger(__name__)


def ensure_trial_subscription(company: Company, trial_days: int = 30) -> SupplierSubscription:
    """Create a TRIAL subscription for the company if missing."""
    from datetime import timedelta

    sub = getattr(company, "subscription", None)
    if sub:
        return sub
    today = timezone.now().date()
    sub = SupplierSubscription.objects.create(
        company=company,
        plan="BASIC",
        status="TRIAL",
        monthly_rate=0,
        valid_from=today,
        valid_until=today + timedelta(days=trial_days),
        next_payment_date=today + timedelta(days=trial_days),
        notes=f"Auto-created TRIAL on {today}",
    )
    return sub


def record_subscription_payment(
    subscription: SupplierSubscription,
    amount,
    months: int = 1,
    actor: Optional[CustomUser] = None,
    manual: bool = True,
) -> Tuple[Optional[SupplierSubscription], Optional[str]]:
    """Extend subscription and set ACTIVE after a successful payment.

    NOTE: manual=True flag indicates the payment was recorded by hand (no provider webhook).
    Logged in ActivityLog with MANUAL_MODE marker so reconciliation is possible later
    when a real payment provider (Click/Payme/Stripe) replaces the manual flow.
    See memory `tech_debt_payment_esign.md`.

    Returns (subscription, error_or_None). Platform-admin viewers cannot pay
    on behalf of a company (`ADMIN_VIEWER_CANNOT_ACT`); the paying user must be
    an active member of the subscription's company with `can_sell` (subscription
    is a seller-side billing concern), or a superuser.
    """
    from datetime import timedelta

    from crm.models import ActivityLog

    if actor is not None:
        if is_platform_admin_viewer(actor):
            return None, "ADMIN_VIEWER_CANNOT_ACT"
        if not (
            getattr(actor, "is_superuser", False) or is_member_of(actor, subscription.company_id, capability="sell")
        ):
            return None, "MEMBER_REQUIRED_FOR_ACTION"
    today = timezone.now().date()
    base = max(today, subscription.valid_until or today)
    subscription.valid_until = base + timedelta(days=30 * months)
    subscription.last_payment_date = today
    subscription.next_payment_date = subscription.valid_until
    subscription.status = "ACTIVE"
    subscription.save(
        update_fields=[
            "valid_until",
            "last_payment_date",
            "next_payment_date",
            "status",
            "updated_at",
        ]
    )
    marker = "[MANUAL_MODE] " if manual else ""
    ActivityLog.objects.create(
        action=f"{marker}Оплата подписки",
        detail=(
            f"Подписка компании {subscription.company.name}: "
            f"+{months} мес, сумма {amount}. Действует до {subscription.valid_until}."
        ),
        user=actor,
        level="SUCCESS",
        company=subscription.company,
    )
    return subscription, None


def check_and_expire_subscriptions() -> dict:
    """Move expired TRIAL/ACTIVE subscriptions to PAST_DUE, then to SUSPENDED if 14+ days overdue."""
    from datetime import timedelta

    today = timezone.now().date()
    # Step 1: fresh expirations → PAST_DUE
    just_expired = SupplierSubscription.objects.filter(
        status__in=["TRIAL", "ACTIVE"],
        valid_until__lt=today,
    )
    past_due_count = just_expired.update(status="PAST_DUE")
    # Step 2: PAST_DUE >= 14 days → SUSPENDED
    threshold = today - timedelta(days=14)
    suspended_count = SupplierSubscription.objects.filter(
        status="PAST_DUE",
        valid_until__lt=threshold,
    ).update(status="SUSPENDED")
    return {"past_due": past_due_count, "suspended": suspended_count}


def change_subscription_status(
    subscriptions: QuerySet[SupplierSubscription],
    new_status: str,
) -> int:
    """
    Change subscription status (ACTIVE / SUSPENDED / CANCELLED / TRIAL).
    Returns: count of updated rows.
    """
    valid_statuses = {"ACTIVE", "SUSPENDED", "CANCELLED", "TRIAL", "PAST_DUE"}
    if new_status not in valid_statuses:
        raise ValueError(f"Invalid status '{new_status}'. Allowed: {valid_statuses}")
    return subscriptions.update(status=new_status)
