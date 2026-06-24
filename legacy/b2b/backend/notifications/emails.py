"""Templated email delivery — single entry point for all outbound mail.

Usage:
    from notifications.emails import send_templated_email

    send_templated_email(
        'setup_password',
        {'first_name': 'Алиса', 'setup_url': 'https://...'},
        to=['user@example.com'],
        channel='transactional',
        user=user_obj,               # optional — for searchability in admin
    )

Every call renders three templates from backend/templates/emails/:
    emails/{name}_subject.txt   — subject line (stripped)
    emails/{name}.txt           — plain-text body
    emails/{name}.html          — HTML body (extends emails/base.html)

Every attempt is persisted in notifications.EmailLog so Ops can audit
"what was sent to whom" via Django Unfold admin.

Why channels (transactional / marketing / system):
    Different purposes demand different SMTP/ESP providers in production —
    transactional reputation is destroyed when marketing gets spam-flagged.
    The channel is chosen in code (service layer), never in admin UI:
    transport is infra configuration, not business data.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template import Context, TemplateDoesNotExist
from django.template.loader import get_template, render_to_string

from .models import EmailLog

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Raised when SMTP/ESP transport fails. Callers decide whether to retry or roll back."""


def _channel_config(channel: str) -> dict:
    try:
        return settings.EMAIL_CHANNELS[channel]
    except KeyError as exc:
        raise ValueError(f"Unknown email channel '{channel}'. " f"Available: {list(settings.EMAIL_CHANNELS)}") from exc


def _render_plaintext(template_path: str, context: dict) -> str:
    """Render a text/plain template with HTML auto-escaping DISABLED.

    Django escapes template output by default, which turns '&' in a URL query
    into '&amp;'. That is correct inside an HTML body (the browser decodes it),
    but a text/plain body has nothing to decode — so a setup link
    '?uid=X&token=Y' arrives as '?uid=X&amp;token=Y' and the 'token' param is
    silently lost, breaking the password-setup / reset flows. Plain text must
    never be HTML-escaped.
    """
    template = get_template(template_path)
    return template.template.render(Context(context, autoescape=False))


def _render_bodies(template_name: str, context: dict) -> tuple[str, str, str]:
    """Render subject, text body, HTML body. Raises TemplateDoesNotExist early."""
    subject = _render_plaintext(f"emails/{template_name}_subject.txt", context).strip()
    text_body = _render_plaintext(f"emails/{template_name}.txt", context)
    try:
        html_body = render_to_string(f"emails/{template_name}.html", context)
    except TemplateDoesNotExist:
        html_body = ""
    return subject, text_body, html_body


def send_templated_email(
    template_name: str,
    context: dict,
    to: Iterable[str],
    *,
    channel: str = "transactional",
    user=None,
    cc: Optional[Iterable[str]] = None,
    bcc: Optional[Iterable[str]] = None,
    attachments: Optional[Iterable[tuple]] = None,
    fail_silently: bool = False,
) -> EmailLog:
    """Render a template bundle and send it through the named channel.

    Returns the EmailLog row. On transport failure:
      - fail_silently=False (default) → raises EmailDeliveryError AFTER logging.
      - fail_silently=True            → logs FAILED and returns normally.
    """
    recipients = list(to)
    if not recipients:
        raise ValueError("`to` must contain at least one recipient")

    cfg = _channel_config(channel)
    subject, text_body, html_body = _render_bodies(template_name, context)

    connection = get_connection(
        backend=cfg["backend"],
        host=cfg["host"],
        port=cfg["port"],
        username=cfg["username"],
        password=cfg["password"],
        use_tls=cfg["use_tls"],
        fail_silently=False,
    )

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=cfg["from_email"],
        to=recipients,
        cc=list(cc) if cc else None,
        bcc=list(bcc) if bcc else None,
        connection=connection,
    )
    if html_body:
        message.attach_alternative(html_body, "text/html")
    # Optional binary attachments, e.g. a rendered КП PDF: (filename, content_bytes, mimetype).
    for filename, content, mimetype in attachments or []:
        message.attach(filename, content, mimetype)

    status = EmailLog.STATUS_SENT
    error_text = ""
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        status = EmailLog.STATUS_FAILED
        error_text = f"{exc.__class__.__name__}: {exc}"
        logger.exception(
            "Email delivery failed: template=%s channel=%s to=%s",
            template_name,
            channel,
            recipients,
        )
        if not fail_silently:
            # Persist the failure first so Ops can see it in Unfold,
            # THEN propagate so the caller can compensate (e.g. roll back user).
            _record_log(
                template_name,
                channel,
                subject,
                cfg["from_email"],
                recipients,
                user,
                text_body,
                html_body,
                status,
                error_text,
            )
            raise EmailDeliveryError(error_text) from exc

    return _record_log(
        template_name,
        channel,
        subject,
        cfg["from_email"],
        recipients,
        user,
        text_body,
        html_body,
        status,
        error_text,
    )


def _record_log(
    template, channel, subject, from_email, recipients, user, text_body, html_body, status, error_text
) -> EmailLog:
    try:
        return EmailLog.objects.create(
            template=template,
            channel=channel,
            subject=subject,
            from_email=from_email,
            to_emails=recipients,
            user=user,
            body_text=text_body,
            body_html=html_body,
            status=status,
            error=error_text,
        )
    except Exception:
        # Log-write failure must never break the caller. Transport succeeded,
        # audit trail didn't — record to app log and move on.
        logger.exception("EmailLog write failed (template=%s)", template)
        return None  # type: ignore[return-value]
