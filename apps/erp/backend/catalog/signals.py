from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Category, Product


@receiver([post_save, post_delete], sender=Product)
def invalidate_product_cache(sender, instance, **kwargs):
    """Invalidate product list/detail cache on any product change."""
    cache.delete("catalog_product_list")
    cache.delete(f"catalog_product_{instance.pk}")


@receiver([post_save, post_delete], sender=Category)
def invalidate_category_cache(sender, instance, **kwargs):
    """Invalidate category cache on changes."""
    cache.delete("catalog_categories")
