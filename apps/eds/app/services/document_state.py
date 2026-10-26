"""Статус документа по исходу маршрута и архив (eds.yaml, `DocumentStatus`; SPEC-v3 §2.4 «Служебная записка»).

Архив — признак `archived_at`, итоговый статус сохраняется; `document.archived` публикуется без отдельной
операции: при окончательном завершении маршрута (одобрен на последнем шаге или отклонён) и при отправке
исходящего письма.
"""

from typing import Any

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.models import Document
from app.schemas.approvals import Decision
from app.schemas.documents import DocumentStatus
from app.services import events, journal


def document_ref(document: Document) -> dict[str, Any]:
    if document.number is None:
        raise RuntimeError("ссылка на документ строится только для документа с номером реестра")
    return {"eds_document_id": str(document.id), "kind": document.kind, "number": document.number}


async def archive(
    session: AsyncSession, bus: AsyncBus, document: Document, *, actor_id: int | None, reason: str
) -> None:
    """Перенести в архив и опубликовать `document.archived` (`reason` — итоговый статус)."""
    now = clock.now()
    document.archived_at = now
    data = {
        "document": document_ref(document),
        "archived_at": now.isoformat(),
        "reason": reason,
        "actor": events.actor(actor_id),
    }
    await events.publish(bus, session, "document.archived", data, subject=str(document.number))
    await journal.record(session, "document.archived", by=actor_id, document_id=document.id, comment=reason)


async def apply_decision(
    session: AsyncSession,
    bus: AsyncBus,
    document: Document,
    *,
    decision: Decision,
    last_step: bool,
    with_accountant: bool,
    actor_id: int,
) -> None:
    """Статус документа после решения на шаге: `approved`/`paid`/`to_accountant`/`returned`/`rejected` (+ архив)."""
    document.updated_at = clock.now()
    if decision is Decision.RETURN:
        document.status = DocumentStatus.RETURNED.value
    elif decision is Decision.REJECT:
        document.status = DocumentStatus.REJECTED.value
        await archive(session, bus, document, actor_id=actor_id, reason=document.status)
    elif not last_step:
        document.status = DocumentStatus.TO_ACCOUNTANT.value
    else:
        document.status = (DocumentStatus.PAID if with_accountant else DocumentStatus.APPROVED).value
        await archive(session, bus, document, actor_id=actor_id, reason=document.status)
