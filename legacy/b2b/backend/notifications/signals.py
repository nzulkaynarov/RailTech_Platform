from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from crm.models import Deal, Quote, QuoteStatus
from accounts.models import Company, VerificationStatus
from .models import Notification, NotificationType


@receiver(pre_save, sender=Deal)
def notify_deal_stage_change(sender, instance, **kwargs):
    """Notify client when deal stage changes."""
    if not instance.pk:
        return  # New deal, skip

    try:
        old_deal = Deal.objects.select_related('stage').get(pk=instance.pk)
    except Deal.DoesNotExist:
        return

    if old_deal.stage_id != instance.stage_id and instance.client:
        info_type = NotificationType.objects.filter(code='INFO').first()
        new_stage_name = instance.stage.name if instance.stage else 'N/A'
        Notification.objects.create(
            user=instance.client,
            type=info_type,
            title=f"Статус сделки изменён",
            message=f"Сделка #{instance.pk} перешла в стадию: {new_stage_name}",
            link="/cabinet/deals",
            deal=instance,
        )


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
        info_type = NotificationType.objects.filter(code='SUCCESS').first()
        new_status_name = instance.verification_status.name if instance.verification_status else 'N/A'

        # Notify all company members
        member_user_ids = instance.members.filter(is_active=True).values_list('user_id', flat=True)
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
            Notification.objects.bulk_create(notifications)
