from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import QuoteItem


@receiver(post_delete, sender=QuoteItem)
def update_quote_on_delete(sender, instance, **kwargs):
    """Recalculate parent Quote totals when an item is deleted."""
    if instance.quote_id:
        instance.quote.recalculate_totals()
