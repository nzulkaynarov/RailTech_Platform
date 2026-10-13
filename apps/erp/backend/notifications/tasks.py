"""Celery tasks for the notifications app.

Currently a single thin wrapper that dispatches a templated email off the request
thread. Auth flows (registration setup-link, password reset) previously called
``send_templated_email`` synchronously inside the DRF handler, which:
  * blocked the ASGI worker for the whole SMTP round-trip, and
  * for the neutral-200 forgot-password endpoint, opened a timing side-channel —
    a KNOWN email did the (slow) SMTP send while an UNKNOWN one returned instantly,
    letting an attacker enumerate accounts despite the identical 200 body.

Enqueuing the send removes both problems: the handler returns immediately and the
delivery (with retries) happens on the worker. The payload is primitives only
(template name, a JSON-serialisable context, recipient strings, an optional user
id) — never ORM instances, which the JSON broker cannot serialise.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="notifications.send_transactional_email",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_transactional_email(
    self, template_name: str, context: dict, to: list, channel: str = "transactional", user_id: int = None
) -> dict:
    """Render + send a templated email off-thread.

    Thin wrapper over ``notifications.emails.send_templated_email`` (Rule 8: the
    rendering/transport logic stays in that single entry point). Resolves the
    optional ``user_id`` back to a CustomUser for the EmailLog attribution. A
    transport failure raises EmailDeliveryError, which the ``autoretry_for`` config
    retries with backoff — strictly more robust than the old inline single-attempt.
    """
    from django.contrib.auth import get_user_model

    from .emails import send_templated_email

    user = None
    if user_id:
        user = get_user_model().objects.filter(pk=user_id).first()

    send_templated_email(
        template_name,
        context,
        to=to,
        channel=channel,
        user=user,
    )
    logger.info("send_transactional_email: template=%s to=%s dispatched", template_name, to)
    return {"template": template_name, "to": to, "status": "sent"}
