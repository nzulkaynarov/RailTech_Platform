"""
Celery tasks for accounts app:
  - expire subscriptions (PAST_DUE → SUSPENDED after 14 days overdue)
"""

import logging

from celery import shared_task

from . import services as accounts_services

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="accounts.expire_subscriptions",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def expire_subscriptions_task(self) -> dict:
    """Daily scan: demote expired subscriptions. Hook up via celery-beat."""
    result = accounts_services.check_and_expire_subscriptions()
    logger.info("expire_subscriptions_task: %s", result)
    return result
