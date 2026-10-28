"""Django EmailBackend ERP: письмо → запрос почтовому сервису CRM по шине (W18A-P1, `notifications/mail_bus.py`).

`settings.EMAIL_BACKEND` ERP — этот класс: любой `send_mail()` / `EmailMessage.send()` публикует
`uz.railtech.erp.mail.requested.v1` в транзакции вызывающего (или своей), SMTP-соединений из ERP нет. Метаданные запроса
`send_templated_email` передаёт служебными заголовками `X-RT-*` (бэкенд их снимает, в письмо они не попадают); без них —
назначение `erp_mail`, случайный ключ запроса, итог не нужен. cc/bcc контракт не знает: адреса сливаются в `to` (до 10).
"""

from __future__ import annotations

import uuid
from typing import Optional

from django.core.mail.backends.base import BaseEmailBackend

from .mail_bus import Attachment, MailRequestError, request_mail

HEADER_PURPOSE = "X-RT-Purpose"
HEADER_REQUEST_KEY = "X-RT-Request-Key"
HEADER_REF_KIND = "X-RT-Ref-Kind"
HEADER_REF_ID = "X-RT-Ref-Id"
HEADER_NOTIFY = "X-RT-Notify"
HEADER_LANGUAGE = "X-RT-Language"
RT_HEADERS = (HEADER_PURPOSE, HEADER_REQUEST_KEY, HEADER_REF_KIND, HEADER_REF_ID, HEADER_NOTIFY, HEADER_LANGUAGE)


def _header(headers: dict, name: str) -> Optional[str]:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return str(value)
    return None


def _html(message) -> Optional[str]:
    for alternative in getattr(message, "alternatives", None) or []:
        content, mimetype = alternative[0], alternative[1]
        if mimetype == "text/html":
            return content if isinstance(content, str) else content.decode("utf-8")
    return None


def _attachments(message) -> list[Attachment]:
    out = []
    for item in message.attachments or []:
        if isinstance(item, tuple):  # (filename, content, mimetype) — EmailAttachment в Django 6
            filename, content, mimetype = item[0], item[1], item[2]
        else:  # MIMEBase
            filename, content, mimetype = item.get_filename(), item.get_payload(decode=True), item.get_content_type()
        if isinstance(content, str):
            content = content.encode("utf-8")
        out.append(Attachment(filename or "attachment", content or b"", mimetype or "application/octet-stream"))
    return out


class BusEmailBackend(BaseEmailBackend):
    """Не открывает соединений: каждое письмо — событие outbox rt_bus."""

    def send_messages(self, email_messages) -> int:
        sent = 0
        for message in email_messages or []:
            try:
                self._request(message)
            except Exception:
                if not self.fail_silently:
                    raise
                continue
            sent += 1
        return sent

    def _request(self, message) -> None:
        headers = dict(message.extra_headers or {})
        recipients = [*message.to, *message.cc, *message.bcc]
        ref_kind, ref_id = _header(headers, HEADER_REF_KIND), _header(headers, HEADER_REF_ID)
        if not recipients:
            raise MailRequestError("MAIL_NO_RECIPIENTS")
        request_mail(
            request_key=_header(headers, HEADER_REQUEST_KEY) or f"erp:mail:{uuid.uuid4().hex}",
            purpose=_header(headers, HEADER_PURPOSE) or "erp_mail",
            to=recipients,
            subject=message.subject,
            text=message.body or "",
            html=_html(message),
            reply_to=(message.reply_to or [None])[0],
            language=_header(headers, HEADER_LANGUAGE),
            ref=(ref_kind, ref_id) if ref_kind and ref_id else None,
            notify=(_header(headers, HEADER_NOTIFY) or "").lower() in ("1", "true", "yes"),
            attachments=_attachments(message),
        )
