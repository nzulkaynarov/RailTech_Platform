from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from accounts.models import Company
from crm.constants import DealStageCode
from crm.models import Deal, Message

from .models import Notification, NotificationType
from .services import push_notification_ws


def _notify_seller_team(deal, info_type):
    """Alert the seller team that a new заявка is open for sourcing.

    Single-seller model: a buyer's deal has no `deal.manager`, so every existing
    seller-facing notification (which targets a specific user) never reached the
    seller — its bell stayed empty ("уведомления не активны"). Here we fan out to
    every active can_sell member of a SELLER-type company (= the RailTech team
    today). TODO multi-seller: target only the addressed seller(s) once заявка
    routing exists (roadmap F#1) instead of the whole seller pool.
    """
    from accounts.constants import SELLER_COMPANY_TYPES
    from accounts.models import CustomUser

    seller_user_ids = (
        CustomUser.objects.filter(
            is_active=True,
            memberships__is_active=True,
            memberships__can_sell=True,
            memberships__company__types__code__in=SELLER_COMPANY_TYPES,
        )
        .values_list("id", flat=True)
        .distinct()
    )
    company_name = deal.company.name if deal.company else ""
    notifications = [
        Notification(
            user_id=uid,
            type=info_type,
            title="Новая заявка",
            message=f"Заявка #{deal.pk} от «{company_name}» ожидает КП",
            link="/crm/deals",
            deal=deal,
        )
        for uid in seller_user_ids
    ]
    if notifications:
        for notif in Notification.objects.bulk_create(notifications):
            push_notification_ws(notif)


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

    # Collect recipients: client + manager, excluding the sender
    recipients = set()
    if deal.client_id and deal.client_id != sender_user.id:
        recipients.add(deal.client_id)
    if deal.manager_id and deal.manager_id != sender_user.id:
        recipients.add(deal.manager_id)

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
