"""Вложение сообщения переписки лида (D1-1): файл из хранилища CRM, без адреса хранилища.

Бот сохраняет вложения Telegram в бакет `tg-attachments` (`app/bot/attachments.py`); в переписке
у вложения — имя, тип, размер и ключ хранилища. Экран сотрудника получает файл этим маршрутом по
номеру вложения в сообщении — ключ и адрес хранилища наружу не уходят. Право — `leads:read`.
"""

from typing import Annotated
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Depends, Path
from fastapi.responses import Response

from app.api.deps import ContainerDep, require
from app.domain.errors import NotFoundError, UpstreamUnavailableError
from app.repositories import crm
from app.repositories import leads as leads_repo
from app.security.principal import Principal

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["leads"])

Reader = Annotated[Principal, Depends(require("leads", "read"))]
MAX_ATTACHMENTS = 20


def _disposition(name: str) -> str:
    """`attachment` с именем файла в UTF-8 (RFC 6266) и запасным ASCII-именем."""
    safe = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in name)
    return f"attachment; filename=\"{safe or 'file'}\"; filename*=UTF-8''{quote(name)}"


@router.get(
    "/leads/{lead_id}/messages/{message_id}/attachments/{index}",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def message_attachment(
    lead_id: int,
    message_id: int,
    index: Annotated[int, Path(ge=0, lt=MAX_ATTACHMENTS)],
    _: Reader,
    container: ContainerDep,
) -> Response:
    """Файл вложения; 404 — нет лида, сообщения, вложения или файл не сохранён (до согласия,
    больше 20 МБ, лид обезличен)."""
    async with container.session_factory() as session:
        lead = await leads_repo.get_lead(session, lead_id)
        message = await crm.lead_message(session, lead_id, message_id)
    if lead is None or lead.erased_at is not None or message is None:
        raise NotFoundError("message not found")
    items = list(message.attachments or [])
    item = items[index] if index < len(items) else None
    key = item.get("storage_key") if isinstance(item, dict) and item.get("stored") else None
    if item is None or not isinstance(key, str) or not key:
        raise NotFoundError("attachment not stored")
    try:
        data = await container.storage.get(container.settings.s3_bucket_attachments, key)
    except Exception as exc:  # хранилище недоступно: 502, а не 500
        logger.warning("attachment_read_failed", lead_id=lead_id, error=type(exc).__name__)
        raise UpstreamUnavailableError("attachment storage unavailable") from exc
    name = str(item.get("name") or "file")
    mime = str(item.get("mime") or "application/octet-stream")
    headers = {"Content-Disposition": _disposition(name), "Cache-Control": "private, no-store"}
    return Response(data, media_type=mime, headers=headers)
