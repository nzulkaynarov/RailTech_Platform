import logging
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from ..models import Company, CustomUser, SupplierSubscription
from .permissions import is_member_of

logger = logging.getLogger(__name__)

# Single source of truth for the trial length — used both when granting the subscription and when
# telling the applicant about it (the approval email), so the two can never disagree.
TRIAL_SUBSCRIPTION_DAYS = 30

#: Потолок на разовое продление. Без него опечатка в поле «месяцев» (99999) уводила срок на
#: восемь тысяч лет вперёд, а Python падал на переполнении timedelta пятисоткой вместо
#: внятного отказа. Пять лет — заведомо больше любого разумного платежа.
MAX_PAYMENT_MONTHS = 60


def ensure_trial_subscription(company: Company, trial_days: int = TRIAL_SUBSCRIPTION_DAYS) -> SupplierSubscription:
    """Create a TRIAL subscription for the company if missing."""
    from datetime import timedelta

    sub = getattr(company, "subscription", None)
    if sub:
        return sub
    today = timezone.localdate()
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

    # Срок продлевают ВПЕРЁД. `months=-2` уводил `valid_until` на 60 дней в прошлое: подписка
    # мгновенно переставала быть операционной, статус оставался ACTIVE, а интерфейс печатал
    # успех — продавец видел «активна» и упирался в закрытые гейты (замер 25-08). Ни Stripe,
    # ни Odoo не дают продлить период назад: это не оплата, а порча срока.
    try:
        months_int = int(months)
    except (TypeError, ValueError):
        return None, "INVALID_MONTHS"
    if months_int < 1 or months_int > MAX_PAYMENT_MONTHS:
        return None, "INVALID_MONTHS"
    try:
        amount_value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return None, "INVALID_AMOUNT"
    if amount_value < 0:
        return None, "INVALID_AMOUNT"

    if actor is not None:
        if not (
            getattr(actor, "is_superuser", False) or is_member_of(actor, subscription.company_id, capability="sell")
        ):
            return None, "MEMBER_REQUIRED_FOR_ACTION"
    today = timezone.localdate()
    base = max(today, subscription.valid_until or today)
    subscription.valid_until = base + timedelta(days=30 * months_int)
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
        event_code="subscription.paid",
        event_params={
            "company_name": subscription.company.name,
            "months": months,
            "amount": str(amount),
            "valid_until": str(subscription.valid_until),
            "manual": manual,
        },
        user=actor,
        level="SUCCESS",
        company=subscription.company,
    )
    return subscription, None


@transaction.atomic
def suspend_subscription(
    subscription: SupplierSubscription,
    actor: Optional[CustomUser] = None,
    reason: str = "",
) -> Tuple[Optional[SupplierSubscription], Optional[str]]:
    """Приостановить подписку — и СКАЗАТЬ ОБ ЭТОМ арендатору.

    Замер 25-08: приостановка не рождала ни письма, ни уведомления. Единственный след —
    запись в журнале доступа, закрытом правом оператора: отключённая сторона узнавала о
    случившемся, только упёршись в закрытую функцию, и видела там общий текст «нужна
    подписка». Причина отключения ей была недоступна вовсе.

    Эталон — Stripe: сообщение об ограничении адресовано тому, кого ограничили, и называет
    причину. Механика писем и уведомлений копируется с KYC (`accounts/services/kyc.py`):
    отправка отложена до `on_commit`, чтобы письмо не ушло при откате транзакции.
    """
    if subscription.status == "SUSPENDED":
        return None, "SUBSCRIPTION_ALREADY_SUSPENDED"

    subscription.status = "SUSPENDED"
    subscription.suspended_reason = (reason or "").strip()
    subscription.suspended_at = timezone.now()
    subscription.save(update_fields=["status", "suspended_reason", "suspended_at"])

    def _notify() -> None:
        try:
            _send_subscription_suspended_email(subscription)
        except (OSError, RuntimeError, ValueError):
            logger.exception("Failed to send suspension email for subscription %s", subscription.pk)
        try:
            _create_suspension_notification(subscription)
        except (OSError, RuntimeError, ValueError):
            logger.exception("Failed to create suspension notification for %s", subscription.pk)

    transaction.on_commit(_notify)
    return subscription, None


def _subscription_owners(subscription: SupplierSubscription):
    return list(
        CustomUser.objects.filter(
            memberships__company_id=subscription.company_id,
            memberships__is_primary=True,
            memberships__is_active=True,
        ).distinct()
    )


def _send_subscription_suspended_email(subscription: SupplierSubscription) -> None:
    from django.conf import settings

    from notifications.emails import send_templated_email

    owners = _subscription_owners(subscription)
    if not owners:
        return
    frontend = getattr(settings, "FRONTEND_URL", "http://localhost:5173")
    context = {
        "company_name": subscription.company.name if subscription.company_id else "",
        "reason": subscription.suspended_reason,
        "subscription_url": f"{frontend}/#my-subscription",
    }
    for owner in owners:
        send_templated_email(
            "subscription_suspended",
            context,
            to=[owner.email],
            channel="transactional",
            user=owner,
            fail_silently=True,
        )


def _create_suspension_notification(subscription: SupplierSubscription) -> None:
    from notifications.models import Notification, NotificationType

    notification_type = NotificationType.objects.filter(code="WARNING").first()
    for owner in _subscription_owners(subscription):
        Notification.objects.create(
            user=owner,
            type=notification_type,
            title="Подписка приостановлена",
            message=subscription.suspended_reason or "",
            link="/#my-subscription",
            event_code="subscription.suspended",
            event_params={
                "company_name": subscription.company.name if subscription.company_id else "",
                "reason": subscription.suspended_reason,
            },
        )


def check_and_expire_subscriptions() -> dict:
    """Move expired TRIAL/ACTIVE subscriptions to PAST_DUE, then to SUSPENDED if 14+ days overdue."""
    from datetime import timedelta

    today = timezone.localdate()
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


def expired_subscription_ids(subscriptions: QuerySet[SupplierSubscription]) -> list:
    """Подписки, у которых срок уже вышел, — их нельзя «активировать» одной сменой статуса.

    Доступ к платным путям считается по ДВУМ признакам сразу (`is_operational`: статус И
    дата). Смена одного статуса рисовала ACTIVE, оставляя `valid_until` в прошлом: обе
    витрины врали одновременно — реестр показывал «Активна», а `/me` отдавал
    `subscription_active=False`, — и ночная задача через сутки откатывала статус обратно.
    """
    today = timezone.localdate()
    return list(subscriptions.filter(valid_until__lt=today).values_list("id", flat=True))


def change_subscription_status(
    subscriptions: QuerySet[SupplierSubscription],
    new_status: str,
) -> int:
    """
    Change subscription status (ACTIVE / SUSPENDED / CANCELLED / TRIAL).
    Returns: count of updated rows.

    ВАЖНО: активацию просроченной подписки этот сервис НЕ выполняет — вызывающий обязан
    сначала спросить `expired_subscription_ids` и отбить действие кодом
    `SUBSCRIPTION_EXPIRED_EXTEND_FIRST`. Продлевает срок только оплата
    (`record_subscription_payment`), как у Stripe и Odoo: возобновление подписки — это
    новый период, а не переключатель статуса.
    """
    valid_statuses = {"ACTIVE", "SUSPENDED", "CANCELLED", "TRIAL", "PAST_DUE"}
    if new_status not in valid_statuses:
        raise ValueError(f"Invalid status '{new_status}'. Allowed: {valid_statuses}")
    if new_status == "ACTIVE":
        subscriptions = subscriptions.exclude(id__in=expired_subscription_ids(subscriptions))
    return subscriptions.update(status=new_status)
