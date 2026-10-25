"""Журнал «кто, что, когда, файл»: запись в транзакции изменения и выборка для карточек."""

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.models import JournalEntry
from app.schemas.common import JournalEntry as JournalOut
from app.services.people import Directory, load_directory

Owner = Literal["letter", "document", "approval"]
_COLUMN = {
    "letter": JournalEntry.letter_id,
    "document": JournalEntry.document_id,
    "approval": JournalEntry.approval_id,
}


async def record(
    session: AsyncSession,
    action: str,
    *,
    by: int | None,
    letter_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    approval_id: uuid.UUID | None = None,
    comment: str | None = None,
    file_id: uuid.UUID | None = None,
    version: int | None = None,
) -> None:
    """Добавить строку журнала. `by=None` — действие системы. Текст комментария — только человеческий, без секретов."""
    session.add(
        JournalEntry(
            at=clock.now(),
            action=action,
            by_crm_user_id=by,
            comment=comment,
            file_id=file_id,
            version=version,
            letter_id=letter_id,
            document_id=document_id,
            approval_id=approval_id,
        )
    )
    await session.flush()


async def entries(
    session: AsyncSession, owner: Owner, owner_id: uuid.UUID, directory: Directory | None = None
) -> list[JournalOut]:
    """Журнал объекта по порядку записи (от старых к новым)."""
    rows = list(
        (await session.execute(select(JournalEntry).where(_COLUMN[owner] == owner_id).order_by(JournalEntry.id)))
        .scalars()
        .all()
    )
    names = directory or await load_directory(session, (r.by_crm_user_id for r in rows))
    return [
        JournalOut(
            at=r.at,
            action=r.action,
            by=names.person_or_none(r.by_crm_user_id),
            comment=r.comment,
            file_id=r.file_id,
            version=r.version,
        )
        for r in rows
    ]
