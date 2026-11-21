"""Записка о звонке: `/api/v1/call-notes` (eds.yaml, тег `files`); правила — `services/call_note.py`."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_container, get_session, get_storage, require_permission
from app.container import Container
from app.models import Employee
from app.schemas.call_notes import CallNote, CallNoteIn
from app.security.permissions import EdsPermission as P
from app.services import call_note, renders
from app.services.storage import ObjectStorage

router = APIRouter(prefix="/api/v1/call-notes", tags=["files"])

# Те же права, что у загрузки файла: записка — файл автора, который он прикрепляет к письму по заявке.
Author = Annotated[
    Employee,
    Depends(
        require_permission(
            P.LETTERS_REGISTER, P.LETTERS_RESOLVE, P.MEMOS_CREATE, P.MEMOS_APPROVE, P.APPROVALS_DECIDE, P.FILES_UPLOAD
        )
    ),
]
Session = Annotated[AsyncSession, Depends(get_session)]
Storage = Annotated[ObjectStorage, Depends(get_storage)]
Box = Annotated[Container, Depends(get_container)]


@router.post("", response_model=CallNote, status_code=202, operation_id="createCallNote")
async def create_call_note(
    body: CallNoteIn, employee: Author, session: Session, storage: Storage, box: Box
) -> CallNote:
    """Заказать записку; повтор с тем же `request_key` — тот же файл. Нет бланка — 409 `letterhead_missing`."""
    async with session.begin():
        result = await call_note.request(session, storage, employee, body)
    await box.defer_render(renders.take_pending(session))
    return result


@router.get("/{note_id}", response_model=CallNote, operation_id="getCallNote")
async def get_call_note(note_id: uuid.UUID, employee: Author, session: Session) -> CallNote:
    return await call_note.state(session, employee, note_id)
