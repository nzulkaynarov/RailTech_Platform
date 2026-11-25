"""Группы Telegram с секретарём (ADR-0032): список, привязка кодом к клиенту, отключение, настройки.

Права — те же, что у клиентов: чтение — `clients:read`, привязка и настройки — `clients:write`.
Переписка привязанной группы — обычный `GET /leads/{lead_id}/messages` (`channel = "group"`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ContainerDep, require
from app.schemas.leads import ActionResult
from app.schemas.telegram_groups import (
    TelegramGroupBindIn,
    TelegramGroupOut,
    TelegramGroupSettingsIn,
)
from app.security.principal import Principal
from app.services.telegram_groups import GroupView

router = APIRouter(prefix="/api/v1/telegram-groups", tags=["telegram-groups"])

Reader = Annotated[Principal, Depends(require("clients", "read"))]
Writer = Annotated[Principal, Depends(require("clients", "write"))]


def _out(view: GroupView) -> TelegramGroupOut:
    return TelegramGroupOut.model_validate(view, from_attributes=True)


@router.get("", response_model=list[TelegramGroupOut])
async def list_groups(
    _: Reader,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TelegramGroupOut]:
    """Группы, где бот администратор: ждущие код первыми, с просроченным кодом — последними."""
    return [_out(view) for view in await container.telegram_groups.groups(limit, offset)]


@router.post("/bind", response_model=TelegramGroupOut)
async def bind_group(
    body: TelegramGroupBindIn, who: Writer, container: ContainerDep
) -> TelegramGroupOut:
    """Привязать группу к клиенту по коду из группы; секретарь пишет и закрепляет уведомление."""
    view = await container.telegram_groups.bind(who, body.code, body.client_id, body.language)
    return _out(view)


@router.post("/{chat_id}/unbind", response_model=ActionResult)
async def unbind_group(chat_id: int, who: Writer, container: ContainerDep) -> ActionResult:
    """Отключить группу: запись прекращается, прежняя переписка остаётся у клиента."""
    await container.telegram_groups.unbind(who, chat_id)
    return ActionResult(ok=True)


@router.patch("/{chat_id}", response_model=TelegramGroupOut)
async def update_group(
    chat_id: int, body: TelegramGroupSettingsIn, who: Writer, container: ContainerDep
) -> TelegramGroupOut:
    view = await container.telegram_groups.update_settings(
        who, chat_id, topic_mode=body.topic_mode, language=body.language
    )
    return _out(view)
