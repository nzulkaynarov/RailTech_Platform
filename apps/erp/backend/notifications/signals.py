import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from crm.constants import DealStageCode
from crm.models import Deal

from .models import Notification, NotificationType
from .services import push_notification_ws

logger = logging.getLogger(__name__)


def notify_new_rfq_by_email(deal, user_ids, *, assigned: bool = False) -> None:
    """W1 (spec-inbound-rfq): the instant-assign-notification email — the seller must learn
    about a new заявка even OFFLINE (the in-app bell reaches only who is logged in; the B2B
    median first response of 42h is lost exactly here). One task PER RECIPIENT — addresses
    never share one message. Enqueued
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


def _own_staff_user_ids() -> set:
    """Active can_sell staff of the own company — the seller of every deal (BUSINESS §3.3)."""
    from core.tenant import own_company_id

    company_id = own_company_id()
    return _seller_user_ids_for_companies([company_id] if company_id else [])


def _notify_seller_team(deal, info_type):
    """Alert the back-office team about a new заявка, deep-linking to the specific deal (ADR-0006
    Move 2). Fires on the RFQ_OPEN transition. The заявка lands in the team's shared work-queue; a
    member then CLAIMS it (crm.services.assignment)."""
    seller_user_ids = _own_staff_user_ids()
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
            event_code="rfq.new",
            event_params={"deal_id": deal.pk, "company": company_name},
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
            event_code="deal.created",
            event_params={"deal_id": instance.pk, "company": company_name},
        )
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
            event_code="deal.stage_changed",
            # Код стадии, а не её RU-название: клиент печатает стадию из своего словаря
            # dealStages — того же, что питает канбан и карточку сделки.
            event_params={"deal_id": instance.pk, "stage_code": new_stage.code if new_stage else ""},
        )
        push_notification_ws(notif)

    # Seller team learns a new заявка has opened for sourcing (no deal.manager
    # is assigned in the single-seller model, so this is their only signal).
    if new_stage and new_stage.code == DealStageCode.RFQ_OPEN:
        _notify_seller_team(instance, info_type)
