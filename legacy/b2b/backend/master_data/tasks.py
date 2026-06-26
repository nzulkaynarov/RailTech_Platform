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
