"""Инвалидация кэша справочников на любую запись модели."""

from django.db.models.signals import post_delete, post_save

from .models import Country, Currency, DeliveryBasis, UnitOfMeasure

#: Справочники, списки которых кэшируются в `master_data/views.py`.
CACHED_LOOKUPS = (Country, Currency, UnitOfMeasure, DeliveryBasis)

#: Срок жизни номера редакции. Не `None`: кэш — `volatile-lru` (S0-2), у ключа без срока вытеснять нечего и он копился бы вечно.
#: Номер заметно дольше страниц, которые от него зависят (10 минут): сброшенный в 1 номер найдёт только уже протухшие страницы.
LOOKUP_VERSION_TTL = 7 * 24 * 3600


def lookup_version_key(model) -> str:
    """Ключ редакции справочника. ЕДИНСТВЕННОЕ место, где задан его формат.

    До 27-08 формула была выписана дословно и здесь, и в `_CachedLookupListMixin`: ключ жил в
    двух файлах, а расхождение проявлялось не падением, а тихо устаревшим справочником —
    ровно тем дефектом, ради которого сигнал и написан.
    """
    return f"lookup-version:{model._meta.label_lower}"


def bump_lookup_version(model) -> None:
    """Увеличить номер редакции — старые страницы кэша перестают находиться.

    `cache.incr` не годится: он падает `ValueError`, если ключа ещё нет (частый случай —
    первая правка после рестарта Redis).
    """
    from django.core.cache import cache

    key = lookup_version_key(model)
    cache.set(key, (cache.get(key, 1) or 1) + 1, LOOKUP_VERSION_TTL)


def _invalidate_lookup_cache(sender, **kwargs) -> None:
    bump_lookup_version(sender)


def connect() -> None:
    """Подписка ПО КАЖДОЙ модели, а не глобальная.

    Глобальный приёмник (`post_save.connect(fn)` без `sender=`) убивает быстрый выход Django
    `NO_RECEIVERS` для ВСЕХ моделей проекта: каждый `save()` любой сущности начинает искать
    приёмники ради четырёх редко пишущихся справочников. Список моделей при этом остаётся в
    одном месте — цикл ниже, — так что обещание «сброс держит сигнал» не нарушено.

    `dispatch_uid` защищает от двойной подписки при повторном импорте модуля.
    """
    for model in CACHED_LOOKUPS:
        uid = f"lookup-cache-{model._meta.label_lower}"
        post_save.connect(_invalidate_lookup_cache, sender=model, dispatch_uid=uid)
        post_delete.connect(_invalidate_lookup_cache, sender=model, dispatch_uid=uid)
