"""Исходящая почта ERP через почтовый сервис CRM (W18A-P1, B-INB-6): один отправитель на ансамбль.

ERP письма сама не шлёт и SMTP не знает. Письмо — событие шины `uz.railtech.erp.mail.requested.v1`
(`packages/contracts/events/erp/mail.requested.v1.json`) в транзакции изменения (outbox rt_bus); CRM доставляет его через SMTP
из карточки «Почта» Платформы, ведёт журнал доставки и повторы и возвращает итог (`uz.railtech.crm.mail.sent|failed.v1`,
`integration/bus_handlers.py` → `apply_mail_result`).

Что здесь:
- `request_mail(...)` — собрать и опубликовать запрос (вызывать внутри `transaction.atomic()`);
- `seal_content` / `open_content` — тело письма шифртекстом ключа пары «erp → crm»: Fernet, ключ =
  urlsafe_b64(HMAC-SHA256(секрет пары, "rt-mail/v1/content")). Одноразовые ссылки входа и приглашений не лежат открыто ни в
  outbox ERP, ни в inbox CRM; CRM расшифровывает тем же секретом пары (секрет по шине не ходит, ADR-0014 L12);
- `stash_attachment` — вложение по ссылке: байты кладутся в своё хранилище ERP (бакет `erp-temp`, сервер удаляет объекты
  старше суток), CRM получает только подписанную ссылку S3 на чтение одного объекта со сроком 24 ч — ключи S3 у каждого
  сервиса свои (S0-9), ключей ERP CRM не получает. Ссылка тоже внутри шифртекста; в открытой части события —
  только имя, тип, размер и sha256 (CRM сверяет скачанное).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence

MAIL_REQUESTED = "uz.railtech.erp.mail.requested.v1"
MAIL_SENT = "uz.railtech.crm.mail.sent.v1"
MAIL_FAILED = "uz.railtech.crm.mail.failed.v1"
CONTENT_ALG = "fernet-pair-v1"
CONTENT_LABEL = b"rt-mail/v1/content"
REQUESTER = "erp"
MAIL_SERVICE = "crm"

MAX_RECIPIENTS = 10
MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
LINK_TTL = timedelta(hours=24)
DEFAULT_PURPOSE = "erp_mail"

_PURPOSE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
_REF_KIND_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,31}$")
_UNSAFE_NAME = re.compile(r"[^\w.\-]+", re.UNICODE)


class MailRequestError(Exception):
    """Запрос письма собрать нельзя (нет секрета пары, нет хранилища для вложения, лишние адреса). `code` — для журнала."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class Attachment:
    filename: str
    content: bytes
    content_type: str


def content_key(pair_secret: str) -> bytes:
    """Ключ Fernet из секрета пары: urlsafe_b64(HMAC-SHA256(secret, "rt-mail/v1/content"))."""
    digest = hmac.new(pair_secret.encode("utf-8"), CONTENT_LABEL, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest)


def seal_content(pair_secret: str, *, text: str, html: Optional[str], links: Sequence[dict[str, str]]) -> str:
    from cryptography.fernet import Fernet

    plain = json.dumps(
        {"text": text, "html": html or None, "links": list(links)}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return Fernet(content_key(pair_secret)).encrypt(plain).decode("ascii")


def open_content(pair_secrets: Iterable[str], ciphertext: str) -> dict[str, Any]:
    """Обратная операция (CRM делает её у себя; здесь — для тестов и проверки формата). Пробует каждый секрет пары."""
    from cryptography.fernet import Fernet, InvalidToken

    for secret in pair_secrets:
        try:
            return json.loads(Fernet(content_key(secret)).decrypt(ciphertext.encode("ascii")))
        except InvalidToken:
            continue
    raise MailRequestError("MAIL_CONTENT_UNREADABLE")


def _pair_secret() -> str:
    from integration.bus import pair_secrets

    secrets = pair_secrets(REQUESTER, MAIL_SERVICE)
    if not secrets:
        raise MailRequestError("MAIL_PAIR_SECRET_MISSING", "нет секрета пары erp → crm (сопряжение с CRM)")
    return secrets[0]


def _safe_filename(name: str) -> str:
    cleaned = _UNSAFE_NAME.sub("_", (name or "").strip()).strip("._") or "attachment"
    return cleaned[:120]


def stash_attachment(attachment: Attachment, *, now: Optional[datetime] = None) -> dict[str, str]:
    """Байты вложения → объект `erp-temp` (`mail/<uuid>/<имя>`) и подписанная ссылка на чтение (24 ч)."""
    from django.core.files.base import ContentFile

    from core.storage import get_temp_storage

    storage = get_temp_storage()
    if not hasattr(storage, "bucket"):  # FileSystemStorage (DEBUG/тесты без S3): ссылки, которую CRM прочтёт, нет
        raise MailRequestError("MAIL_ATTACHMENT_STORAGE_UNAVAILABLE")
    name = storage.save(
        f"mail/{uuid.uuid4().hex}/{_safe_filename(attachment.filename)}", ContentFile(attachment.content)
    )
    key = storage._normalize_name(name)
    url = storage.bucket.meta.client.generate_presigned_url(
        "get_object",
        Params={"Bucket": storage.bucket_name, "Key": key},
        ExpiresIn=int(LINK_TTL.total_seconds()),
    )
    expires = (now or datetime.now(timezone.utc)) + LINK_TTL
    return {"url": url, "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ")}


def build_request(
    *,
    request_key: str,
    purpose: str,
    to: Sequence[str],
    subject: str,
    text: str,
    html: Optional[str] = None,
    reply_to: Optional[str] = None,
    language: Optional[str] = None,
    ref: Optional[tuple[str, str]] = None,
    notify: bool = False,
    attachments: Sequence[Attachment] = (),
) -> dict[str, Any]:
    """`data` события `erp.mail.requested.v1` строго по схеме (вложения уже уходят в хранилище)."""
    recipients = list(dict.fromkeys(a.strip() for a in to if a and a.strip()))
    if not recipients:
        raise MailRequestError("MAIL_NO_RECIPIENTS")
    if len(recipients) > MAX_RECIPIENTS:
        raise MailRequestError("MAIL_TOO_MANY_RECIPIENTS", f"не больше {MAX_RECIPIENTS} адресов")
    if len(attachments) > MAX_ATTACHMENTS:
        raise MailRequestError("MAIL_TOO_MANY_ATTACHMENTS", f"не больше {MAX_ATTACHMENTS} вложений")
    if not _KEY_RE.match(request_key):
        raise MailRequestError("MAIL_BAD_REQUEST_KEY", request_key[:40])
    purpose = purpose.strip().lower().replace("-", "_") if purpose else DEFAULT_PURPOSE
    if not _PURPOSE_RE.match(purpose):
        purpose = DEFAULT_PURPOSE

    secret = _pair_secret()
    meta, links = [], []
    for item in attachments:
        content = item.content if isinstance(item.content, bytes) else str(item.content).encode("utf-8")
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise MailRequestError("MAIL_ATTACHMENT_TOO_LARGE", item.filename[:60])
        meta.append(
            {
                "filename": (item.filename or "attachment")[:255],
                "content_type": item.content_type or "application/octet-stream",
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
        links.append(stash_attachment(Attachment(item.filename, content, item.content_type)))

    subject_line = " ".join((subject or "").split())[:255] or "—"
    data: dict[str, Any] = {
        "request_key": request_key,
        "purpose": purpose,
        "to": recipients,
        "subject": subject_line,
        "notify": bool(notify),
        "content": {"alg": CONTENT_ALG, "ciphertext": seal_content(secret, text=text or "", html=html, links=links)},
    }
    if reply_to:
        data["reply_to"] = reply_to.strip()
    lang = (language or "").strip().lower()[:2]
    if re.fullmatch(r"[a-z]{2}", lang or ""):
        data["language"] = lang
    if ref is not None:
        kind, ref_id = str(ref[0]), str(ref[1])
        if _REF_KIND_RE.match(kind) and 0 < len(ref_id) <= 64:
            data["ref"] = {"kind": kind, "id": ref_id}
    if meta:
        data["attachments"] = meta
    return data


def request_mail(**kwargs: Any):
    """Опубликовать запрос письма в текущей транзакции (`transaction.atomic()` — свой или вызывающего)."""
    from django.db import transaction
    from integration.bus import get_bus

    data = build_request(**kwargs)
    with transaction.atomic():
        return get_bus().publish(MAIL_REQUESTED, data, subject=f"mail/{data['request_key']}")


# ── Итог доставки от CRM ──────────────────────────────────────────────────────────────────────────

EMAIL_LOG_KEY = re.compile(r"^erp:email_log:(\d+)$")


def apply_mail_result(event_type: str, data: dict[str, Any]) -> None:
    """`crm.mail.sent|failed.v1` → журнал писем ERP (и журнал/итог КП). Чужие итоги (requester ≠ erp) пропускаются;
    повтор идемпотентен; «ошибка» после «отправлено» не применяется."""
    import logging

    from core.models import EmailLog

    logger = logging.getLogger(__name__)
    if data.get("requester") != REQUESTER:
        return
    sent = event_type == MAIL_SENT
    match = EMAIL_LOG_KEY.match(str(data.get("request_key", "")))
    if match:
        log = EmailLog.objects.select_for_update().filter(pk=int(match.group(1))).first()
        if log is None:
            logger.info("mail result for unknown EmailLog %s", match.group(1))
        elif log.status != EmailLog.STATUS_SENT:
            if sent:
                log.status, log.error = EmailLog.STATUS_SENT, ""
                log.save(update_fields=["status", "error"])
            elif log.status != EmailLog.STATUS_FAILED:
                log.status, log.error = EmailLog.STATUS_FAILED, _failure_text(data)
                log.save(update_fields=["status", "error"])
    ref = data.get("ref") or {}
    if ref.get("kind") == "quote" and str(ref.get("id", "")).isdigit():
        _apply_quote_result(int(ref["id"]), sent, data)


def _failure_text(data: dict[str, Any]) -> str:
    reason = str(data.get("reason") or "failed")
    detail = str(data.get("detail") or "").strip()
    return f"{reason}: {detail}" if detail else reason


def _apply_quote_result(quote_id: int, sent: bool, data: dict[str, Any]) -> None:
    """Итог письма с КП: `send_report` (если КП отправлялось письмом) и журнал КП; повтор — без второй записи."""
    from crm.models import Quote
    from crm.services.quotes._shared import _log_quote

    quote = Quote.objects.select_for_update().filter(pk=quote_id).first()
    if quote is None:
        return
    report = dict(quote.send_report or {})
    marker = "email_sent_at" if sent else "email_failed_at"
    stamp = data.get("sent_at") if sent else data.get("failed_at")
    if report.get(marker):
        return  # итог уже применён
    if report.get("email_sent_at") and not sent:
        return  # «ошибка» после «отправлено» не применяется
    changed = False
    if report:
        if sent:
            report["email_sent_at"] = stamp
            changed = True
        elif "email" in (report.get("sent_via") or []):
            report["sent_via"] = [c for c in report["sent_via"] if c != "email"]
            skipped = list(report.get("skipped") or [])
            skipped.append(
                {"channel": "email", "reason": "EMAIL_DELIVERY_FAILED", "detail": str(data.get("reason", ""))}
            )
            report["skipped"] = skipped
            report["email_failed_at"] = stamp
            changed = True
        else:
            report["email_failed_at"] = stamp
            changed = True
    if changed:
        quote.send_report = report
        quote.save(update_fields=["send_report", "updated_at"])
    if sent:
        _log_quote(
            quote,
            None,
            "Письмо с КП отправлено",
            "",
            event_code="quote.email_sent",
            event_params={"number": quote.number or quote.pk},
        )
    else:
        _log_quote(
            quote,
            None,
            "Письмо с КП не отправлено",
            _failure_text(data)[:200],
            event_code="quote.email_failed",
            event_params={"number": quote.number or quote.pk, "reason": str(data.get("reason", ""))},
        )
