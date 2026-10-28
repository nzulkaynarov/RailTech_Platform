"""Templated email delivery — single entry point for all outbound mail of ERP.

Usage:
    from notifications.emails import send_templated_email

    send_templated_email(
        'setup_password',
        {'first_name': 'Алиса', 'setup_url': 'https://...'},
        to=['user@example.com'],
        user=user_obj,               # optional — for searchability in admin
        ref=('quote', quote.pk),     # optional — объект ERP, к которому относится письмо (итог доставки)
    )

Every call renders three templates from backend/templates/emails/ (or an active DB EmailTemplate row):
    emails/{name}_subject.txt   — subject line (stripped)
    emails/{name}.txt           — plain-text body
    emails/{name}.html          — HTML body (extends emails/base.html)

Доставка (W18A-P1, B-INB-6): ERP письма сама не шлёт и SMTP не знает. Шаблон рендерит ERP (шаблоны — у системы-владельца),
а письмо уходит событием шины `uz.railtech.erp.mail.requested.v1` почтовому сервису CRM (`notifications/bus_backend.py`,
`notifications/mail_bus.py`) — один отправитель на ансамбль, SMTP задаёт админ в карточке «Почта» Платформы. Строка
`EmailLog` пишется в той же транзакции со статусом QUEUED («в очереди почты»); итог (SENT / FAILED с причиной) приходит
обратным событием CRM (`uz.railtech.crm.mail.sent|failed.v1`). Пауза почты — выключатель «Почта» в CRM: очередь CRM копит
письма и отправляет их после включения.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import DatabaseError, transaction
from django.template import Context, Template, TemplateDoesNotExist
from django.template.loader import get_template, render_to_string
from django.utils import translation

from .bus_backend import (
    HEADER_LANGUAGE,
    HEADER_NOTIFY,
    HEADER_PURPOSE,
    HEADER_REF_ID,
    HEADER_REF_KIND,
    HEADER_REQUEST_KEY,
)
from .models import EmailLog

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Письмо не передано почтовому сервису CRM (публикация не удалась). Callers decide whether to retry or roll back."""


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


def _render_string_plaintext(source: str, context: dict) -> str:
    """Render a stored (DB) template string with HTML auto-escaping DISABLED.

    Same rationale as `_render_plaintext`: a text/plain body must not be
    HTML-escaped, or '&' in a URL query becomes '&amp;' and the link breaks.
    """
    return Template(source).render(Context(context, autoescape=False))


def _render_string_html(source: str, context: dict) -> str:
    """Render a stored (DB) HTML template string with normal auto-escaping ON."""
    return Template(source).render(Context(context))


def _db_template(template_name: str):
    """Return the active DB EmailTemplate row for this key, or None.

    A missing table (migrations not yet applied) or any DB error degrades
    gracefully to the file fallback — the email must still go out.
    """
    try:
        from .models import EmailTemplate

        # L2: сначала оверрайд ИМЕННО на языке письма, затем «на все языки» (пустой
        # language — так выглядят строки, заведённые до L2). Порядок сортировки ставит
        # языковой раньше всеязычного.
        language = translation.get_language() or settings.LANGUAGE_CODE
        rows = EmailTemplate.objects.filter(key=template_name, is_active=True, language__in=[language, ""])
        return rows.order_by("-language").first()
    except DatabaseError:
        logger.exception("EmailTemplate lookup failed for key=%s — using file fallback", template_name)
        return None


def render_bodies_from_row(db_template, context: dict) -> tuple[str, str, str]:
    """Тема, текст и HTML письма из строки `EmailTemplate` (активность и язык строки здесь не проверяются)."""
    subject = _render_string_plaintext(db_template.subject, context).strip()
    text_body = _render_string_plaintext(db_template.text_body, context)
    html_body = _render_string_html(db_template.html_body, context) if db_template.html_body else ""
    return subject, text_body, html_body


def _render_bodies(template_name: str, context: dict) -> tuple[str, str, str]:
    """Render subject, text body, HTML body.

    Prefers an active DB EmailTemplate row (Platform-Operator editable); falls
    back to the file templates in backend/templates/emails/ when no active row
    exists. Raises TemplateDoesNotExist early if neither source has the template.
    """
    db_template = _db_template(template_name)
    if db_template is not None:
        return render_bodies_from_row(db_template, context)

    subject = _render_plaintext(f"emails/{template_name}_subject.txt", context).strip()
    text_body = _render_plaintext(f"emails/{template_name}.txt", context)
    try:
        html_body = render_to_string(f"emails/{template_name}.html", context)
    except TemplateDoesNotExist:
        html_body = ""
    return subject, text_body, html_body


def email_brand(company) -> dict:
    """White-label header bundle for a CLIENT-facing email (D1e): the SELLER's name + accent go in
    the header, the platform stays named in the footer (Stripe/DocuSign pattern). Spread into the
    email context (``**email_brand(seller)``). Returns ``{}`` (→ platform default header) when the
    company is None or has no filled brand. Read-only."""
    if not company:
        return {}
    from accounts.models import CompanyDocumentProfile
    from crm.services.documents import accent_contrast

    profile = CompanyDocumentProfile.objects.filter(company=company).first()
    name = (getattr(profile, "legal_name", "") or getattr(company, "name", "") or "").strip()
    accent = (getattr(profile, "accent_color", "") or "").strip()
    brand = {}
    if name:
        brand["brand_name"] = name
    if accent:
        brand["brand_accent"] = accent
        brand["brand_contrast"] = accent_contrast(accent)
    return brand


def send_templated_email(
    template_name: str,
    context: dict,
    to: Iterable[str],
    *,
    channel: str = "transactional",
    user=None,
    attachments: Optional[Iterable[tuple]] = None,
    fail_silently: bool = False,
    language: Optional[str] = None,
    purpose: Optional[str] = None,
    ref: Optional[tuple] = None,
    notify: bool = True,
) -> EmailLog:
    """Render a template bundle and hand the letter to the CRM mail service (W18A-P1).

    Returns the EmailLog row (QUEUED — письмо в очереди почты CRM; итог придёт событием). Если письмо передать не удалось
    (публикация в шину упала: нет сопряжения с CRM, нет хранилища для вложения…):
      - fail_silently=False (default) → raises EmailDeliveryError AFTER logging FAILED.
      - fail_silently=True            → logs FAILED and returns normally.

    `channel` — историческая метка журнала (transactional / system), на доставку не влияет. `purpose` — назначение письма
    в журнале доставки CRM (по умолчанию — код шаблона); `ref` — `(kind, id)` объекта ERP, итог доставки которого нужен
    (КП → `Quote.send_report`); `notify` — получать ли итог (по умолчанию да: журнал ERP узнаёт SENT / FAILED).

    L2 (spec-bilingual-ru-en): письмо рендерится на языке ПОЛУЧАТЕЛЯ — канон Odoo
    (`partner.lang`) и Stripe (`preferred_locales`). Счёт выставляет продавец, а письмо
    читает покупатель, поэтому язык того, кто нажал кнопку, здесь ни при чём. Порядок:
    явный `language` (внешний адресат без учётной записи) → настройка `user` → язык
    платформы.
    """
    recipients = list(to)
    if not recipients:
        raise ValueError("`to` must contain at least one recipient")

    # Platform-wide defaults every email template may reference (footer support contact, links).
    # Merged UNDER the caller's context so an explicit value always wins.
    platform_name = getattr(settings, "PLATFORM_NAME", "ERP")
    support_email = getattr(settings, "SUPPORT_EMAIL", "support@example.com")
    try:
        from core.models.settings import SystemSetting

        sys_settings = SystemSetting.load()
        if sys_settings.platform_name:
            platform_name = sys_settings.platform_name
        if sys_settings.support_email:
            support_email = sys_settings.support_email
    except Exception:
        pass

    context = {
        "platform_name": platform_name,
        "brand_name": platform_name,
        "support_email": support_email,
        "frontend_url": getattr(settings, "FRONTEND_URL", ""),
        **context,
    }

    from core.i18n import resolve_user_language, supported_languages

    requested = (language or "").strip().lower()
    target_language = requested if requested in supported_languages() else resolve_user_language(user)
    # Рендер (и только он) выполняется на языке адресата: активировать язык шире было бы
    # неверно — вызывающий код продолжает работать в своём контексте.
    with translation.override(target_language):
        subject, text_body, html_body = _render_bodies(template_name, context)

    headers = {
        HEADER_PURPOSE: purpose or template_name,
        HEADER_NOTIFY: "true" if notify else "false",
        HEADER_LANGUAGE: target_language or "",
    }
    if ref is not None:
        headers[HEADER_REF_KIND], headers[HEADER_REF_ID] = str(ref[0]), str(ref[1])

    try:
        with transaction.atomic():
            log = EmailLog.objects.create(
                template=template_name,
                channel=channel,
                subject=subject[:255],
                from_email=MAIL_SENDER,
                to_emails=recipients,
                user=user,
                body_text=_redact_secrets(text_body),
                body_html=_redact_secrets(html_body),
                status=EmailLog.STATUS_QUEUED,
                error="",
            )
            headers[HEADER_REQUEST_KEY] = f"erp:email_log:{log.pk}"
            message = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                to=recipients,
                headers=headers,
                connection=get_connection(fail_silently=False),
            )
            if html_body:
                message.attach_alternative(html_body, "text/html")
            # Optional binary attachments, e.g. a rendered КП PDF: (filename, content_bytes, mimetype).
            for filename, content, mimetype in attachments or []:
                message.attach(filename, content, mimetype)
            message.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 — любой сбой передачи письма → EmailLog(FAILED)
        error_text = f"{getattr(exc, 'code', exc.__class__.__name__)}: {exc}"[:2000]
        logger.exception("Email hand-off to CRM failed: template=%s channel=%s", template_name, channel)
        failed_log = _record_log(
            template_name,
            channel,
            subject,
            MAIL_SENDER,
            recipients,
            user,
            text_body,
            html_body,
            EmailLog.STATUS_FAILED,
            error_text,
        )
        if fail_silently:
            return failed_log
        raise EmailDeliveryError(error_text) from exc
    return log


#: Кто отправляет письма ERP: почтовый сервис CRM (адрес отправителя — в карточке «Почта» Платформы).
MAIL_SENDER = "crm"


# SEC-02: one-time credential params carried in email links (setup/reset). The SENT email
# keeps the real link; the copy PERSISTED to EmailLog (viewable in Unfold / DB backups) must
# not expose a still-valid token, or a Platform Engineer / backup reader could take over the
# account before the legitimate click (OWASP A09).
# Prefix handles `?`, raw `&`, AND the HTML-escaped `&amp;` (the html_body renders links escaped).
_SECRET_QS_RE = re.compile(r"((?:\?|&amp;|&)(?:token|uid|code)=)[^&\s\"'<>]+", re.IGNORECASE)
# FIX-14 (P-9): ссылка входа в портал несёт токен в пути (`/auth/magic/<token>`), не в query.
_SECRET_PATH_RE = re.compile(r"(/auth/magic/)[^/?#&\s\"'<>]+")
# FIX-21: ссылка входа из писем — `/auth/magic#token=<token>` (токен во фрагменте, контракт 0.2.0); прежний вид
# с токеном в пути остаётся для устаревшего `GET /auth/magic/{token}`, поэтому прячем оба.
_SECRET_FRAGMENT_RE = re.compile(r"(/auth/magic#token=)[^&\s\"'<>]+")


def _redact_secrets(body: Optional[str]) -> str:
    redacted = _SECRET_QS_RE.sub(r"\1[REDACTED]", body or "")
    return _SECRET_FRAGMENT_RE.sub(r"\1[REDACTED]", _SECRET_PATH_RE.sub(r"\1[REDACTED]", redacted))


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
            body_text=_redact_secrets(text_body),
            body_html=_redact_secrets(html_body),
            status=status,
            error=error_text,
        )
    except DatabaseError:
        # Log-write failure must never break the caller. Transport succeeded,
        # audit trail didn't — record to app log and move on.
        logger.exception("EmailLog write failed (template=%s)", template)
        return None  # type: ignore[return-value]
