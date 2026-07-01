from django.core.cache import cache
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver
from rest_framework.exceptions import ValidationError

from .models import Category, EquipmentGroup, Product


@receiver(m2m_changed, sender=Product.equipment_groups.through)
def validate_railway_equipment_groups(sender, instance, action, **kwargs):
    """
    Post-save M2M validation: RAILWAY_MACHINERY products must have
    at least one equipment group after M2M relations are set.

    Raises a DRF ``ValidationError`` (not a Django one) so the API path
    returns a clean HTTP 400 instead of an unhandled 500 (H6). DRF's
    exception handler maps this exception to a 400 response.
    """
    if action in ("post_add", "post_remove", "post_clear"):
        if (
            instance.domain_type
            and getattr(instance.domain_type, "code", None) == "RAILWAY_MACHINERY"
            and not instance.equipment_groups.exists()
        ):
            raise ValidationError(
                {
                    "equipment_groups": (
                        "Товары домена RAILWAY_MACHINERY должны быть привязаны " "минимум к одной группе оборудования."
                    )
                }
            )


@receiver([post_save, post_delete], sender=Product)
def invalidate_product_cache(sender, instance, **kwargs):
    """Invalidate product list/detail cache on any product change."""
    cache.delete("catalog_product_list")
    cache.delete(f"catalog_product_{instance.pk}")


@receiver([post_save, post_delete], sender=Category)
def invalidate_category_cache(sender, instance, **kwargs):
    """Invalidate category cache on changes."""
    cache.delete("catalog_categories")


@receiver([post_save, post_delete], sender=EquipmentGroup)
def invalidate_equipment_group_cache(sender, instance, **kwargs):
    """Invalidate equipment group cache on changes."""
    cache.delete("catalog_equipment_groups")
