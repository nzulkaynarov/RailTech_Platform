import threading
from contextlib import contextmanager

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import QuoteItem

#: Пересчёт КП на КАЖДУЮ удалённую строку — правильное поведение для одиночного удаления и
#: лишняя работа для пачки: массовое удаление делает один пересчёт в конце. Флаг потоко-локален,
#: как и полагается: под ASGI в одном процессе живут параллельные запросы, и глобальный
#: переключатель отключил бы пересчёт соседям. Близнец `save(skip_recalculate=True)` у модели.
_suppress_recalc = threading.local()


@contextmanager
def suppress_quote_item_recalc():
    """Внутри блока удаление строк КП не пересчитывает итоги — вызывающий делает это сам, один раз."""
    previous = getattr(_suppress_recalc, "on", False)
    _suppress_recalc.on = True
    try:
        yield
    finally:
        _suppress_recalc.on = previous


@receiver(post_delete, sender=QuoteItem)
def update_quote_on_delete(sender, instance, **kwargs):
    """Recalculate parent Quote totals when an item is deleted."""
    if getattr(_suppress_recalc, "on", False):
        return
    if instance.quote_id:
        instance.quote.recalculate_totals()
