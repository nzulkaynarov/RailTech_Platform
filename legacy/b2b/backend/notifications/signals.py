import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from accounts.models import Company
from crm.constants import DealStageCode
from crm.models import Deal, Message

from .models import Notification, NotificationType
from .services import push_notification_ws

logger = logging.getLogger(__name__)


def notify_new_rfq_by_email(deal, user_ids, *, assigned: bool = False) -> None:
    """W1 (spec-inbound-rfq): the instant-assign-notification email — the seller must learn
    about a new заявка even OFFLINE (the in-app bell reaches only who is logged in; the B2B
    median first response of 42h is lost exactly here). One task PER RECIPIENT — routed
    companies are competitors, their addresses must never share one message. Enqueued
    on_commit (never announce a заявка a rollback would erase); a broker outage must not
    break the stage transition — log and move on."""
    from accounts.models import CustomUser

    emails = list(
        CustomUser.objects.filter(pk__in=user_ids, is_active=True).exclude(email="").values_list("email", "pk")
    )
    if not emails:
        return
    context = {
        "buyer_name": deal.company.name if deal.company else "",
        "deal_title": deal.title or "",
        "deal_url": f"{settings.FRONTEND_URL}/#request-detail/{deal.pk}",
        "assigned": assigned,
    }

    def _enqueue():
        from .tasks import send_transactional_email

        for email, user_id in emails:
            try:
                send_transactional_email.delay(
                    "new_rfq_seller", context, to=[email], channel="transactional", user_id=user_id
                )
            except Exception:  # noqa: BLE001 — a dead broker must not fail the заявка submit
                logger.exception("new_rfq_seller email enqueue failed for deal %s", deal.pk)

    transaction.on_commit(_enqueue)


def _seller_user_ids_for_companies(company_ids) -> set:
    """Active can_sell member user ids of the given seller companies."""
    from accounts.models import CustomUser

    company_ids = list(company_ids)
    if not company_ids:
        return set()
    return set(
        CustomUser.objects.filter(
            is_active=True,
            memberships__is_active=True,
            memberships__can_sell=True,
            memberships__company_id__in=company_ids,
        )
        .values_list("id", flat=True)
        .distinct()
    )


def _routed_seller_user_ids(deal) -> set:
    """Active can_sell members of the seller companies this deal was ROUTED to (DealSellerRouting)."""
    return _seller_user_ids_for_companies(deal.seller_routings.values_list("seller_company_id", flat=True))


def _notify_seller_team(deal, info_type):
    """Alert ONLY the seller teams this заявка was ROUTED to (DealSellerRouting), deep-linking to
    the specific deal — not a fan-out to the whole seller pool (ADR-0006 Move 2). Fires on the
    RFQ_OPEN transition, by which point routing is set. A заявка lands in the routed company's
    shared work-queue; a member then CLAIMS it (crm.services.assignment) — that's the targeted,
    quiet, scalable signal, replacing the noisy whole-pool blast that linked to a generic list."""
    seller_user_ids = _routed_seller_user_ids(deal)
    if not seller_user_ids:
        return
    company_name = deal.company.name if deal.company else ""
    notifications = [
        Notification(
            user_id=uid,
            type=info_type,
            title="Новая заявка",
            message=f"Заявка #{deal.pk} от «{company_name}» ожидает КП",
            link=f"/crm/deals/{deal.pk}",
            deal=deal,
        )
        for uid in seller_user_ids
    ]
    if notifications:
        for notif in Notification.objects.bulk_create(notifications):
            push_notification_ws(notif)
    # W1: the same event by EMAIL — the only channel that reaches an offline seller.
    notify_new_rfq_by_email(deal, seller_user_ids)


@receiver(post_save, sender=Deal)
def notify_deal_created(sender, instance, created, **kwargs):
    """Notify manager when a new deal is created by a client."""
    if not created:
        return

    # Notify assigned manager (if any)
    if instance.manager and instance.client and instance.manager != instance.client:
        info_type = NotificationType.objects.filter(code="INFO").first()
        company_name = instance.company.name if instance.company else ""
        notif = Notification.objects.create(
            user=instance.manager,
            type=info_type,
            title="Новая сделка",
            message=f"Создана сделка #{instance.pk} от {company_name}",
            link="/crm/deals",
            deal=instance,
        )
        push_notification_ws(notif)


@receiver(post_save, sender=Message)
def notify_new_message(sender, instance, created, **kwargs):
    """Notify deal participants about new chat messages."""
    if not created or instance.message_type != "CHAT":
        return

    deal = instance.deal
    sender_user = instance.sender
    info_type = NotificationType.objects.filter(code="INFO").first()
    short_text = instance.text[:80] + ("..." if len(instance.text) > 80 else "")

    # Collect recipients, excluding the sender. Buyer↔seller must be symmetric: the seller side of a
    # claimed deal is `assigned_to` (the КП author), NOT `manager` (legacy, ~always NULL for real
    # buyer/seller deals — ADR-0006 Move 2). If the deal is still unclaimed, alert the routed seller
    # team so the buyer's message isn't lost in the queue.
    recipients = set()
    if deal.client_id and deal.client_id != sender_user.id:
        recipients.add(deal.client_id)
    if deal.manager_id and deal.manager_id != sender_user.id:
        recipients.add(deal.manager_id)
    # Per-seller ownership (ADR-0006 Move 2): notify each routed seller's claimed owner; for a routing
    # still in the queue, alert that company's seller team. Competition is hidden — each seller hears
    # only about their own thread.
    unclaimed_company_ids = []
    for routing in deal.seller_routings.all():
        if routing.assigned_to_id:
            recipients.add(routing.assigned_to_id)
        else:
            unclaimed_company_ids.append(routing.seller_company_id)
    recipients.update(_seller_user_ids_for_companies(unclaimed_company_ids))
    recipients.discard(sender_user.id)

    notifications = [
        Notification(
            user_id=uid,
            type=info_type,
            title=f"Сообщение по сделке #{deal.pk}",
            message=f"{sender_user.get_full_name() or sender_user.email}: {short_text}",
            link="/crm/deals",
            deal=deal,
        )
        for uid in recipients
    ]
    if notifications:
        created = Notification.objects.bulk_create(notifications)
        for notif in created:
            push_notification_ws(notif)


@receiver(pre_save, sender=Deal)
def notify_deal_stage_change(sender, instance, **kwargs):
    """Notify client when deal stage changes."""
    if not instance.pk:
        return  # New deal, skip

    try:
        old_deal = Deal.objects.select_related("stage").get(pk=instance.pk)
    except Deal.DoesNotExist:
        return

    if old_deal.stage_id == instance.stage_id:
        return

    info_type = NotificationType.objects.filter(code="INFO").first()
    new_stage = instance.stage
    new_stage_name = new_stage.name if new_stage else "N/A"

    # Buyer (client) learns their заявка/deal moved stage.
    if instance.client:
        notif = Notification.objects.create(
            user=instance.client,
            type=info_type,
            title="Статус сделки изменён",
            message=f"Сделка #{instance.pk} перешла в стадию: {new_stage_name}",
            link="/cabinet/deals",
            deal=instance,
        )
        push_notification_ws(notif)

    # Seller team learns a new заявка has opened for sourcing (no deal.manager
    # is assigned in the single-seller model, so this is their only signal).
    if new_stage and new_stage.code == DealStageCode.RFQ_OPEN:
        _notify_seller_team(instance, info_type)


@receiver(pre_save, sender=Company)
def notify_kyc_status_change(sender, instance, **kwargs):
    """Notify company members when KYC status changes."""
    if not instance.pk:
        return

    try:
        old_company = Company.objects.get(pk=instance.pk)
    except Company.DoesNotExist:
        return

    if old_company.verification_status_id != instance.verification_status_id:
        info_type = NotificationType.objects.filter(code="SUCCESS").first()
        new_status_name = instance.verification_status.name if instance.verification_status else "N/A"

        # Notify all company members
        member_user_ids = instance.members.filter(is_active=True).values_list("user_id", flat=True)
        notifications = [
            Notification(
                user_id=uid,
                type=info_type,
                title="Статус верификации обновлён",
                message=f"Статус вашей компании: {new_status_name}",
                link="/cabinet/profile",
            )
            for uid in member_user_ids
        ]
        if notifications:
            created = Notification.objects.bulk_create(notifications)
            for notif in created:
                push_notification_ws(notif)
