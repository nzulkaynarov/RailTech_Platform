"""Исход исходящего письма (СЦ-1, `ui-standard.md` §14 п. 1): письмо ушло адресату или сотрудник снял отправку.

Письмо зарегистрировано с почтой адресата — значит, цель — доставка. Пока ни одна попытка не завершилась `sent` и
сотрудник не отметил «вручено иначе», письмо не доставлено: оно остаётся в «Исходящих», а не уходит в «Архив».
"""

from sqlalchemy import ColumnElement, and_, exists, func

from app.models import Document, DocumentMailing
from app.schemas.documents import DocumentKind, DocumentStatus


def undelivered() -> ColumnElement[bool]:
    sent = exists().where(DocumentMailing.document_id == Document.id, DocumentMailing.status == "sent")
    return and_(
        Document.kind == DocumentKind.LETTER_OUT.value,
        Document.status == DocumentStatus.SENT.value,
        func.coalesce(func.btrim(Document.recipient_email), "") != "",
        Document.mail_waived_at.is_(None),
        ~sent,
    )


def is_undelivered(document: Document, mailing_statuses: list[str]) -> bool:
    """То же правило для уже загруженного документа и статусов его попыток."""
    return (
        document.kind == DocumentKind.LETTER_OUT.value
        and document.status == DocumentStatus.SENT.value
        and bool((document.recipient_email or "").strip())
        and document.mail_waived_at is None
        and "sent" not in mailing_statuses
    )
