import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def refresh_exchange_rates():
    """Daily Celery-beat job: pull CBU FX rates into ExchangeRate."""
    from .fx import fetch_cbu_rates

    count = fetch_cbu_rates()
    logger.info("FX: upserted %s exchange rates from CBU", count)
    return count


# Лимиты выше конвенционных 600с — как у bulk-импортов sourcing: tarif.customs.uz отдаёт
# ~8 строк/сек, полная выгрузка ~13 тыс. кодов занимает около получаса. Задача ходит по
# очереди `imports` (см. CELERY_TASK_ROUTES), чтобы не занимать слоты транзакционных задач.
@shared_task(
    time_limit=3600,
    soft_time_limit=3400,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def refresh_tnved_codes():
    """Weekly Celery-beat job: синхронизация классификатора ТН ВЭД с tarif.customs.uz."""
    from .tnved import sync_tnved_codes

    summary = sync_tnved_codes()
    logger.info("ТН ВЭД: %s", summary)
    return summary
