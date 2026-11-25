"""Заявки в канал команды: бот одобряет активного привязанного сотрудника, остальных отклоняет."""

import structlog
from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatJoinRequest

from app.services.staff_channel import StaffChannelService

logger = structlog.get_logger(__name__)
router = Router(name="staff-channel")


@router.chat_join_request()
async def on_join_request(
    request: ChatJoinRequest, bot: Bot, staff_channel: StaffChannelService | None = None
) -> None:
    if staff_channel is None:
        return
    decision = await staff_channel.decide_join(request.chat.id, request.from_user.id)
    try:
        if decision == "approve":
            await bot.approve_chat_join_request(request.chat.id, request.from_user.id)
            await staff_channel.record_joined(request.from_user.id)  # only after Telegram accepted
        elif decision == "decline":
            await bot.decline_chat_join_request(request.chat.id, request.from_user.id)
    except TelegramAPIError as exc:
        logger.warning("join_request_answer_failed", decision=decision, error=type(exc).__name__)
