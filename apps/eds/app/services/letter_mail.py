"""«Отправить адресату» — письмо на бланке почтовым сервисом CRM (P4; W18A-P1, B-W18AP1-1).

Попытка — строка `document_mailings`: `awaiting_pdf` (ждёт итоговый PDF с номером) → `requested` (событие
`mail.requested` с PDF по подписанной ссылке, `notify = true`) → `sent`/`failed` по итогу CRM (`crm.mail.sent|failed`).
EDS SMTP не знает: почта не настроена — CRM отвечает `failed` `smtp_not_configured`, и в журнале отправки причина
словами
«Почта не настроена — Настройки · Подключения · Почта» (DECISIONS 2026-10-29).
"""

import hashlib
import html
import uuid
from datetime import timedelta
from typing import Any, Final

import structlog
from pydantic import BaseModel, ConfigDict
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import conflict, invalid_fields
from app.models import Document, DocumentMailing, DocumentRender
from app.services import journal, letterhead, reply
from app.services.mail_out import LinkedAttachment, MailRequestError, request_mail
from app.services.storage import ObjectStorage

log = structlog.get_logger(__name__)

PURPOSE: Final = "outgoing_letter"
REF_KIND: Final = "document"
LINK_TTL_S: Final = 24 * 3600
_REASONS: Final = {
    "smtp_not_configured": "Почта не настроена — Настройки · Подключения · Почта",
    "rejected": "Почтовый сервер отклонил адрес — проверьте почту адресата",
    "auth_failed": "Почтовый сервер не принял вход — Настройки · Подключения · Почта",
    "unavailable": "Почтовый сервер недоступен — повторите позже",
    "tls_failed": "Не удалось защищённое соединение с почтовым сервером — Настройки · Подключения · Почта",
    "invalid_host": "Неверный адрес почтового сервера — Настройки · Подключения · Почта",
    "attachment_unavailable": "PDF письма недоступен почтовому сервису — отправьте ещё раз",
    "content_unreadable": "Почтовый сервис не прочитал письмо (ключ пары) — сообщите администратору",
}
NO_PAIR: Final = "Почта не подключена к документообороту (нет секрета пары EDS → CRM) — сообщите администратору"
NO_PDF: Final = "PDF письма не построен: "


def reason_text(code: str) -> str:
    return _REASONS.get(code, f"Письмо не отправлено ({code})")


async def _in_progress(session: AsyncSession, document_id: uuid.UUID) -> bool:
    row = await session.execute(
        select(DocumentMailing.id).where(
            DocumentMailing.document_id == document_id,
            DocumentMailing.status.in_(("awaiting_pdf", "requested")),
        )
    )
    return row.first() is not None


async def start(
    session: AsyncSession,
    bus: AsyncBus,
    storage: ObjectStorage,
    *,
    document: Document,
    render: DocumentRender,
    actor_id: int,
) -> DocumentMailing:
    """Новая попытка отправки зарегистрированного письма; PDF уже готов — запрос CRM сразу, иначе — после рендера."""
    email = (document.recipient_email or "").strip()
    if not email:
        raise invalid_fields("Укажите почту адресата.", recipient_email="required")
    if await _in_progress(session, document.id):
        raise conflict("mail_in_progress", "Письмо уже отправляется — дождитесь итога.")
    now = clock.now()
    mailing_id = uuid.uuid4()
    mailing = DocumentMailing(
        id=mailing_id,
        document_id=document.id,
        request_key=f"eds:document:{document.id}:mail:{mailing_id}",
        recipients=[email],
        status="awaiting_pdf",
        render_hash=render.hash,
        requested_by=actor_id,
        requested_at=now,
    )
    session.add(mailing)
    await session.flush()
    await journal.record(session, "document.mail_requested", by=actor_id, document_id=document.id, comment=email)
    if render.status == "ready":
        await _request(session, bus, storage, mailing, document, render)
    elif render.status == "failed":
        await _fail(session, bus, mailing, document, NO_PDF + (render.error or ""))
    return mailing


def _finish(mailing: DocumentMailing, status: str, reason: str | None) -> None:
    mailing.status, mailing.reason, mailing.finished_at = status, reason, clock.now()


async def _fail(
    session: AsyncSession, bus: AsyncBus | None, mailing: DocumentMailing, document: Document, reason: str
) -> None:
    """Письмо не ушло: итог попытки, строка журнала и уведомление автору и делопроизводителям (EDS-REPLY-1)."""
    _finish(mailing, "failed", reason)
    await journal.record(session, "document.mail_failed", by=None, document_id=document.id, comment=reason)
    if bus is not None:
        await reply.notify_mail_failed(session, bus, document, mailing_id=mailing.id, reason=reason)


def _letter_text(document: Document, company: str) -> tuple[str, str]:
    number = document.number or ""
    lines = [
        "Здравствуйте!",
        "",
        f"Направляем письмо {number} «{document.subject}». Письмо на бланке — во вложении (PDF).",
        "",
        "С уважением,",
        company,
    ]
    text = "\n".join(lines)
    body = "".join(f"<p>{html.escape(line)}</p>" if line else "" for line in lines)
    return text, body


async def _request(
    session: AsyncSession,
    bus: AsyncBus,
    storage: ObjectStorage,
    mailing: DocumentMailing,
    document: Document,
    render: DocumentRender,
) -> None:
    head = await letterhead.current(session)
    company = head.company_name if head else ""
    key = render.storage_key or ""
    data = b"".join([chunk async for chunk in storage.stream(key)])
    expires = clock.now() + timedelta(seconds=LINK_TTL_S)
    attachment = LinkedAttachment(
        filename=f"{(document.number or 'letter').replace('/', '-')}.pdf",
        content_type="application/pdf",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        url=await storage.presign(key, LINK_TTL_S),
        expires_at=expires.isoformat().replace("+00:00", "Z"),
    )
    text, body = _letter_text(document, company)
    subject = f"{document.number} — {document.subject}" if document.number else document.subject
    try:
        await request_mail(
            bus,
            session,
            request_key=mailing.request_key,
            purpose=PURPOSE,
            to=list(mailing.recipients),
            subject=subject,
            text=text,
            html=body,
            language=str((document.body or {}).get("lang") or "ru"),
            ref=(REF_KIND, str(document.id)),
            notify=True,
            attachments=[attachment],
        )
    except MailRequestError:
        await _fail(session, bus, mailing, document, NO_PAIR)
        return
    mailing.status = "requested"
    await session.flush()


def on_render_finished(bus: AsyncBus, storage: ObjectStorage) -> Any:
    """Обработчик итога рендера (`renders.run`): ждущие этот PDF письма уходят в CRM или получают ошибку."""

    async def handle(session: AsyncSession, render: DocumentRender) -> None:
        rows = list(
            (
                await session.execute(
                    select(DocumentMailing, Document)
                    .join(Document, Document.id == DocumentMailing.document_id)
                    .where(DocumentMailing.render_hash == render.hash, DocumentMailing.status == "awaiting_pdf")
                    .with_for_update(of=DocumentMailing)
                )
            ).all()
        )
        for mailing, document in rows:
            if render.status == "ready":
                await _request(session, bus, storage, mailing, document, render)
            else:
                await _fail(session, bus, mailing, document, NO_PDF + (render.error or ""))

    return handle


class _Ref(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    id: str


class MailResult(BaseModel):
    """Итог CRM `crm.mail.sent|failed.v1` (терпимое чтение)."""

    model_config = ConfigDict(extra="ignore")
    requester: str
    request_key: str
    ref: _Ref | None = None
    reason: str | None = None


async def apply_result(session: AsyncSession, data: MailResult, *, sent: bool, bus: AsyncBus | None = None) -> bool:
    """Применить итог письма EDS: `False` — чужой, неизвестный или уже применённый («ошибка» после «отправлено» —
    нет)."""
    if data.requester != "eds":
        return False
    mailing = (
        await session.execute(
            select(DocumentMailing).where(DocumentMailing.request_key == data.request_key).with_for_update()
        )
    ).scalar_one_or_none()
    if mailing is None or mailing.status in ("sent", "failed"):
        return False
    if sent:
        _finish(mailing, "sent", None)
        await journal.record(
            session,
            "document.mail_sent",
            by=None,
            document_id=mailing.document_id,
            comment=", ".join(mailing.recipients),
        )
    else:
        document = await session.get(Document, mailing.document_id)
        if document is not None:
            await _fail(session, bus, mailing, document, reason_text(data.reason or "unknown"))
    await session.flush()
    return True


async def for_document(session: AsyncSession, document_id: uuid.UUID) -> list[DocumentMailing]:
    rows = await session.execute(
        select(DocumentMailing)
        .where(DocumentMailing.document_id == document_id)
        .order_by(DocumentMailing.requested_at, DocumentMailing.id)
    )
    return list(rows.scalars())
