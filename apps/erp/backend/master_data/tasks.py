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
    from finance.services.fx import fetch_cbu_rates

    from core.external_status import ExternalSwitchedOff, external_call

    try:
        # M3-ERP-06: исход — в состояние сервиса «курсы ЦБ» (`/health` integration); выключатель из CRM пропускает прогон.
        with external_call("cbu_rates"):
            count = fetch_cbu_rates()
    except ExternalSwitchedOff:
        logger.info("FX: refresh skipped — service switched off from CRM")
        return 0
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
    from core.external_status import ExternalSwitchedOff, external_call

    from .tnved import sync_tnved_codes

    try:
        # M3-ERP-06: исход — в состояние сервиса «ТН ВЭД / тариф»; выключатель из CRM пропускает прогон.
        with external_call("customs_tariff"):
            summary = sync_tnved_codes()
    except ExternalSwitchedOff:
        logger.info("ТН ВЭД: синхронизация пропущена — сервис выключен из CRM")
        return {"skipped": "switched_off"}
    logger.info("ТН ВЭД: %s", summary)
    return summary
