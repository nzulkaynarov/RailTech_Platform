"""Обезличивание лида — общий шаг для `/delete` в боте и для «Тест» у сотрудника (LH-1).

Внутри транзакции: беседа кабинета и перенос неотвеченной передачи на новый якорь, закрытие передач,
стирание текстов и контактов, отвязка Telegram, событие `lead.erased` с тем, чьи сообщения кабинета
стереть. После коммита: файлы вложений и состояние агента бота (`forget_after_commit`), пост по
перенесённым передачам — у вызывающего.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.models.leads import Lead
from app.repositories import leads as repo
from app.schemas.settings import AppSettings
from app.security.audit import Actor
from app.services import cabinet_erasure

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LeadErasure:
    keys: list[str]
    closed: list[int]
    moved: list[tuple[int, int]]
    messages: int


async def erase_in_session(
    session: AsyncSession, lead: Lead, cfg: AppSettings, actor: Actor, now: datetime
) -> LeadErasure:
    from app.services.contact_telegram import unlink_erased  # цикл импортов на уровне модуля

    keys = await repo.attachment_keys(session, lead.id)
    # Кабинет (CHAT-1, CHAT-1b): только сообщения этого человека; беседа и неотвеченная передача
    # `cabinet_message` переходят на новый якорь — до закрытия передач лида.
    cabinet = await cabinet_erasure.erase_for_lead(session, lead, cfg)
    closed = await repo.close_escalations(session, lead.id, now)
    # Контакты клиента ищутся по `telegram_identity_id` — берём идентичности до отвязки.
    identity_ids = await repo.identity_ids_of_lead(session, lead.id)
    count = await repo.erase_lead(session, lead, now)
    # Telegram отвязывается от контактов (решение архитектора 2026-11-04, NOTIFY-1).
    await unlink_erased(session, identity_ids, now, actor)
    # Подписчики стирают у себя копии: событие без данных, только id и — для ленты кабинета — чьи
    # сообщения стереть.
    await bus_events.lead_erased(session, lead, actor, cabinet=cabinet.event)
    return LeadErasure(keys, closed, cabinet.moved_escalations, count)


async def forget_after_commit(
    lead_id: int,
    keys: list[str],
    forget_agent: Callable[[int], Awaitable[None]] | None,
    erase_attachments: Callable[[list[str]], Awaitable[None]] | None,
) -> None:
    """Состояние агента (чекпоинты хранят тексты) и файлы вложений; сбой не отменяет стирание."""
    try:
        if forget_agent is not None:
            await forget_agent(lead_id)
        if keys and erase_attachments is not None:
            await erase_attachments(keys)
    except Exception:
        logger.exception("lead_erase_cleanup_failed", lead_id=lead_id)
