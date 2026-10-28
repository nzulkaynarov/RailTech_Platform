"""Сборка письма строки журнала перед отправкой (M3-CRM-08, W18A-P1): тело, HTML, вложения.

Строка `email_log` хранит тело, HTML и ссылки на вложения шифртекстом `SECRETS_KEY`; здесь они
открываются, вложения скачиваются по ссылкам (`app/integrations/mail_attachments.py`), и письмо
уходит транспортом SMTP. Простое письмо CRM (только текст) идёт прежним вызовом транспорта.
"""

import json
from dataclasses import dataclass
from typing import Any

from app.integrations.mail_attachments import AttachmentError, AttachmentFetcher, AttachmentRef
from app.integrations.smtp import MailAttachment, SmtpConnection, SmtpProbeError, SmtpTransport
from app.models.email import EmailLog
from app.security.secrets_store import SecretCipher, SecretsKeyError


@dataclass(frozen=True, slots=True)
class Outgoing:
    """Что отправить: расшифрованное тело и ссылки на вложения строки журнала."""

    to: str
    subject: str
    body: str
    html: str | None
    reply_to: str | None
    refs: tuple[AttachmentRef, ...]


class UndeliverableError(Exception):
    """Письмо этой строки уже не отправить: итог `failed` с причиной (без повтора)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def decode(row: EmailLog, cipher: SecretCipher | None) -> Outgoing:
    if row.body_ciphertext is None:
        raise UndeliverableError("body_expired")
    if cipher is None:
        raise UndeliverableError("smtp_not_configured")
    try:
        body = cipher.decrypt(row.body_ciphertext)
        html = cipher.decrypt(row.html_ciphertext) if row.html_ciphertext else None
        links = json.loads(cipher.decrypt(row.links_ciphertext)) if row.links_ciphertext else []
    except SecretsKeyError as exc:
        raise UndeliverableError("secrets_key_changed") from exc
    meta = list(row.attachments or [])
    if len(links) != len(meta):
        raise UndeliverableError("attachment_unavailable")
    refs = tuple(
        AttachmentRef(
            url=str(link),
            filename=str(item["filename"]),
            content_type=str(item["content_type"]),
            size=int(item["size"]),
            sha256=str(item["sha256"]),
        )
        for link, item in zip(links, meta, strict=True)
    )
    return Outgoing(row.to_email, row.subject, body, html, row.reply_to or None, refs)


async def download(
    fetcher: AttachmentFetcher | None, refs: tuple[AttachmentRef, ...]
) -> tuple[MailAttachment, ...]:
    if not refs:
        return ()
    if fetcher is None:
        raise AttachmentError("attachment_unavailable", "no fetcher", permanent=True)
    files = []
    for ref in refs:
        content = await fetcher.fetch(ref)
        files.append(MailAttachment(ref.filename, ref.content_type, content))
    return tuple(files)


async def send(
    transport: SmtpTransport,
    connection: SmtpConnection,
    outgoing: Outgoing,
    files: tuple[MailAttachment, ...],
) -> None:
    # Простое письмо — прежний вызов: подмены транспорта в тестах о новых полях не знают.
    extra: dict[str, Any] = {}
    if outgoing.html:
        extra["html"] = outgoing.html
    if outgoing.reply_to:
        extra["reply_to"] = outgoing.reply_to
    if files:
        extra["attachments"] = files
    await transport.send(connection, outgoing.to, outgoing.subject, outgoing.body, **extra)


def error_text(exc: SmtpProbeError | AttachmentError) -> str:
    if isinstance(exc, AttachmentError):
        return f"{exc.reason}: {exc.detail}" if exc.detail else exc.reason
    return f"{exc.kind}: {exc.detail}" if exc.detail else exc.kind
