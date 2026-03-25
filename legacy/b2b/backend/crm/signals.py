from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import QuoteItem


@receiver(post_save, sender=QuoteItem)
def update_quote_on_save(sender, instance, **kwargs):
    """Recalculate parent Quote totals when an item is saved."""
    if instance.quote:
        instance.quote.recalculate_totals()


@receiver(post_delete, sender=QuoteItem)
def update_quote_on_delete(sender, instance, **kwargs):
    """Recalculate parent Quote totals when an item is deleted."""
    if instance.quote:
        instance.quote.recalculate_totals()
