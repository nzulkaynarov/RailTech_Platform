"""Кнопка «Забрать» в канале команды (SPEC §9.1): те же правила, что «Забрать» в CRM."""

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import DomainError
from app.repositories import users as users_repo
from app.security.principal import Principal
from app.security.rbac import Rbac
from app.services.channel_card import TAKE_PREFIX
from app.services.leads import LeadService

logger = structlog.get_logger(__name__)
router = Router(name="team-channel")

# Ответы команде (канал — внутренний, на русском). Привязку Telegram делает админ.
NOT_LINKED = (
    "Ваш Telegram не привязан к CRM. Ваш ID: {tg_id}. "
    "Попросите администратора указать его в разделе «Пользователи»."
)
NO_RIGHTS = "Недостаточно прав, чтобы забрать лида."
TEMPORARY_CREDENTIALS_HINT = "Сначала войдите в CRM и смените временный пароль."
TAKEN = "Лид ваш. Откройте карточку в CRM."
REJECTED: dict[str, str] = {
    "conflict": "Лида уже забрал другой менеджер.",
    "invalid_transition": "Из текущей стадии лида забрать нельзя — откройте карточку в CRM.",
    "not_found": "Лид удалён по запросу клиента.",
}


@router.callback_query(F.data.startswith(TAKE_PREFIX))
async def on_take(
    query: CallbackQuery,
    sessions: async_sessionmaker[AsyncSession],
    leads: LeadService,
    rbac: Rbac,
) -> None:
    raw = (query.data or "").removeprefix(TAKE_PREFIX)
    if not raw.isdigit():
        await query.answer()
        return
    async with sessions() as session:
        user = await users_repo.by_tg_user_id(session, query.from_user.id)
        roles = await users_repo.roles_of(session, user.id) if user else []
    if user is None:
        await query.answer(NOT_LINKED.format(tg_id=query.from_user.id), show_alert=True)
        return
    principal = Principal(user.id, user.full_name, tuple(roles), user.must_change_password)
    if principal.must_change_password:
        await query.answer(TEMPORARY_CREDENTIALS_HINT, show_alert=True)
        return
    if not rbac.allowed(principal.roles, "leads", "take"):
        await query.answer(NO_RIGHTS, show_alert=True)
        return
    try:
        await leads.take(principal, int(raw))
    except DomainError as exc:
        logger.info("channel_take_rejected", lead_id=raw, code=exc.code)
        await query.answer(REJECTED.get(exc.code, NO_RIGHTS), show_alert=True)
        return
    await query.answer(TAKEN)
