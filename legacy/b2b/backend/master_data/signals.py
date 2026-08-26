"""Инвалидация кэша справочников на любую запись модели."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Country, Currency, DeliveryBasis, UnitOfMeasure

#: Справочники, списки которых кэшируются в `master_data/views.py`.
CACHED_LOOKUPS = (Country, Currency, UnitOfMeasure, DeliveryBasis)


def bump_lookup_version(model) -> None:
    """Увеличить номер редакции справочника — старые страницы кэша перестают находиться.

    Ключ и его формат заданы в `master_data/views.py` (`_CachedLookupListMixin`); здесь
    повторяется ровно он. `cache.incr` не годится: он падает `ValueError`, если ключа ещё нет
    (частый случай — первая правка после рестарта Redis).
    """
    from django.core.cache import cache

    key = f"lookup-version:{model._meta.label_lower}"
    cache.set(key, (cache.get(key, 1) or 1) + 1, None)


@receiver(post_save)
@receiver(post_delete)
def _invalidate_lookup_cache(sender, **kwargs) -> None:
    # Подписка без `sender=` — один приёмник на четыре модели; отбор здесь, а не четырьмя
    # декораторами, чтобы список кэшируемых справочников жил в ОДНОМ месте.
    if sender in CACHED_LOOKUPS:
        bump_lookup_version(sender)
