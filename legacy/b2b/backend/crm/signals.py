from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Message, QuoteItem


@receiver(post_delete, sender=QuoteItem)
def update_quote_on_delete(sender, instance, **kwargs):
    """Recalculate parent Quote totals when an item is deleted."""
    if instance.quote_id:
        instance.quote.recalculate_totals()


@receiver(post_save, sender=Message)
def broadcast_new_message(sender, instance: Message, created: bool, **kwargs):
    """
    Broadcast newly created Message to the deal's chat room so REST- and
    WebSocket-created messages both reach live listeners.
    """
    if not created:
        return
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    sender_user = instance.sender
    payload = {
        "type": "chat_message",
        "id": instance.id,
        "deal": instance.deal_id,
        "seller_company": instance.seller_company_id,
        "text": instance.text,
        "sender": sender_user.id if sender_user else None,
        "sender_name": (sender_user.get_full_name() if sender_user else "")
        or (sender_user.email if sender_user else ""),
        "message_type": instance.message_type,
        "timestamp": instance.timestamp.isoformat(),
    }
    # SEC (audit #4): push only to the message's LANE group — the buyer + that one seller —
    # so a competing seller's live socket never receives another lane's message. A NULL lane
    # ('all') is a deal-level/system message every connected party receives.
    from .services.messaging import message_lane_group_name

    async_to_sync(channel_layer.group_send)(
        message_lane_group_name(instance.deal_id, instance.seller_company_id),
        payload,
    )
