"""Лид ждёт менеджера (`owner_mode=paused`): по сути отвечает человек, но бот не молчит.

ADR-0015: каждое сообщение в очереди подтверждается (не чаще раза в `ACK_INTERVAL`),
а просьба позвать человека или стоп-слово поднимают приоритет открытой эскалации.
Решает код, модель не вызывается.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.keywords import find_terms
from app.domain.language import Language
from app.domain.triggers import TriggerSignals, evaluate
from app.models.leads import Conversation, Lead
from app.schemas.settings import AppSettings
from app.services import escalation, message_log

ACK_INTERVAL: Final = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class WaitingReply:
    text: str | None
    message_id: int | None
    escalation_id: int | None


def ack_due(last_bot_msg_at: datetime | None, now: datetime) -> bool:
    return last_bot_msg_at is None or now - last_bot_msg_at >= ACK_INTERVAL


async def while_waiting(
    session: AsyncSession,
    conversation: Conversation,
    lead: Lead,
    *,
    text: str,
    human_requested: bool,
    language: Language,
    cfg: AppSettings,
    now: datetime,
) -> WaitingReply:
    applied = None
    stop_word = bool(find_terms(text, cfg.stop_words.terms))
    if human_requested or stop_word:
        signals = TriggerSignals(human_requested=human_requested, stop_word_hit=stop_word)
        hits = evaluate(signals, cfg.escalation.triggers())
        applied = await escalation.apply(session, lead, hits, cfg, now)
    escalation_id = applied.escalation_id if applied else None
    # Явная просьба позвать человека (кнопка, «соедините с менеджером») подтверждается всегда:
    # тишина на нажатие выглядит как сломанная кнопка. Прочие сообщения — не чаще ACK_INTERVAL.
    if not human_requested and not ack_due(lead.last_bot_msg_at, now):
        return WaitingReply(None, None, escalation_id)
    reply = cfg.texts.waiting_for_manager.get(language)
    message = await message_log.add(
        session,
        conversation,
        role="bot",
        text=reply,
        meta={"notice": "waiting_for_manager"},
    )
    lead.last_bot_msg_at = now
    return WaitingReply(reply, message.id, escalation_id)
