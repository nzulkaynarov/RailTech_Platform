"""«На подписи» (СЦ-8): письмо передано на подпись, но ещё не подписано.

Статус документа остаётся `draft` (на нём стоят проверка подписи, правка и видимость), поэтому слово «На подписи» —
не значение перечисления, а факт: исходящее письмо в `draft` с отметкой передачи `registration_requested_at`.
После `sign()` статус `sent` — признак гаснет сам.
"""

from typing import Any

from sqlalchemy import ColumnElement, and_

from app.models import Document
from app.schemas.documents import DocumentKind, DocumentStatus


def awaiting_signature(document: Any = Document) -> ColumnElement[bool]:
    """Предикат SQL; `document` — `Document` или его `aliased(...)` (подзапрос значения курсора порядка)."""
    return and_(
        document.kind == DocumentKind.LETTER_OUT.value,
        document.status == DocumentStatus.DRAFT.value,
        document.registration_requested_at.is_not(None),
    )


def is_awaiting_signature(document: Document) -> bool:
    """То же правило для уже загруженного документа."""
    return (
        document.kind == DocumentKind.LETTER_OUT.value
        and document.status == DocumentStatus.DRAFT.value
        and document.registration_requested_at is not None
    )
