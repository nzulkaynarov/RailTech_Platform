import threading
from contextlib import contextmanager

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from accounts.models import CompanySettings
from core.models import ExchangeRate

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


@receiver(post_save, sender=ExchangeRate, dispatch_uid="crm_reprice_margin_quotes_on_rate")
def reprice_margin_quotes_on_rate(sender, instance, **kwargs):
    """РАСЧ-3: курс валюты записан (ЦБ или вручную) — цены «от маржи» в черновиках КП с этой валютой пересчитываются
    сами. Одно место для любого источника курса; после фиксации транзакции записи курса."""
    code = instance.currency.code
    transaction.on_commit(lambda: _reprice(code=code))


@receiver(post_save, sender=CompanySettings, dispatch_uid="crm_reprice_margin_quotes_on_settings")
def reprice_margin_quotes_on_settings(sender, instance, created, update_fields=None, **kwargs):
    """РАСЧ-3: поменяли целевую маржу или шаг округления — цены «от маржи» в черновиках этой компании пересчитываются."""
    if created:
        return
    if update_fields is not None and not {"target_margin_percent", "price_rounding_step"} & set(update_fields):
        return
    company_id = instance.company_id
    transaction.on_commit(lambda: _reprice(company_id=company_id))


def _reprice(code: str | None = None, company_id: int | None = None) -> None:
    from .services.quotes import QuoteCalculationService

    QuoteCalculationService.reprice_live_margin_quotes(code, company_id)
