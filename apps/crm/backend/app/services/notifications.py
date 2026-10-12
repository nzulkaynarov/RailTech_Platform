"""Канал команды (SPEC §8.2, §9.1): пост-карточка передачи, SLA, напоминания, сводка.

Пост всегда рендерится из текущего состояния БД — `sync` идемпотентен:
нет поста → отправить, есть → отредактировать. Вызывается из воркера.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from html import escape
from typing import Any

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    ReplyParameters,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.auth import User
from app.models.leads import Conversation, Lead, Message
from app.models.qualification import Escalation
from app.schemas.settings import AppSettings
from app.services import channel_texts as tx
from app.services.channel_card import TAKE_PREFIX, CardData, can_take, render
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)


class NotificationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        bot: Bot | None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._bot = bot

    async def sync(self, escalation_id: int) -> bool:
        cfg = await self._settings.get()
        channel = cfg.notifications.channel_id
        if self._bot is None or channel is None:
            logger.info("channel_not_configured", escalation_id=escalation_id)
            return False
        async with self._sessions() as session:
            loaded = await _load(session, escalation_id, cfg)
        if loaded is None:
            return False
        escalation, card = loaded
        text, markup = render(card), _keyboard(card)
        if escalation.channel_message_id is None:
            if not can_take(card):
                return False
            sent = await self._bot.send_message(
                channel, text, parse_mode="HTML", reply_markup=markup
            )
            async with self._sessions() as session, session.begin():
                row = await session.get(Escalation, escalation_id, with_for_update=True)
                if row is not None:
                    row.channel_message_id = sent.message_id
            return True
        try:
            await self._bot.edit_message_text(
                text,
                chat_id=channel,
                message_id=escalation.channel_message_id,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except TelegramBadRequest as exc:
            if "not modified" not in str(exc):
                raise
        return True

    async def mark_sla_overdue(self, escalation_id: int) -> bool:
        """SLA истёк, а эскалацию не забрали: пометить пост и упомянуть дежурных."""
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            row = await session.get(Escalation, escalation_id, with_for_update=True)
            if row is None or row.status != "open" or row.sla_notified_at is not None:
                return False
            row.sla_notified_at = datetime.now(UTC)
        await self.sync(escalation_id)
        text = tx.SLA_REMINDER.format(lead_id=row.lead_id, minutes=_waiting_minutes(row))
        await self._remind(cfg, escalation_id, text)
        return True

    async def remind(self, escalation_id: int) -> bool:
        cfg = await self._settings.get()
        async with self._sessions() as session:
            row = await session.get(Escalation, escalation_id)
        if row is None or row.status != "open":
            return False
        text = tx.REMINDER.format(lead_id=row.lead_id, minutes=_waiting_minutes(row))
        await self._remind(cfg, escalation_id, text)
        return True

    async def digest(self) -> int:
        """Ежедневная сводка открытых эскалаций (09:05 по Ташкенту)."""
        cfg = await self._settings.get()
        channel = cfg.notifications.channel_id
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(Escalation)
                    .where(Escalation.status.in_(("open", "snoozed")))
                    .order_by(Escalation.priority, Escalation.id)
                )
            ).all()
        if self._bot is None or channel is None or not rows:
            return 0
        base = cfg.company.crm_base_url.rstrip("/")
        lines = [tx.DIGEST_TITLE.format(count=len(rows))]
        lines += [
            tx.DIGEST_LINE.format(
                icon=tx.PRIORITY_ICON.get(r.priority, "•"),
                lead_id=r.lead_id,
                priority=tx.PRIORITY.get(r.priority, r.priority),
                url=f"{base}/leads/{r.lead_id}",
            )
            for r in rows[:30]
        ]
        await self._bot.send_message(
            channel, "\n".join(lines), link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return len(rows)

    async def _remind(self, cfg: AppSettings, escalation_id: int, title: str) -> None:
        channel = cfg.notifications.channel_id
        if self._bot is None or channel is None:
            return
        async with self._sessions() as session:
            row = await session.get(Escalation, escalation_id)
            duty = await _mentions(session, cfg.notifications.duty_user_ids)
        text = title + (f"\n{duty}" if duty else "")
        await self._bot.send_message(
            channel,
            text,
            parse_mode="HTML",
            reply_parameters=(
                ReplyParameters(message_id=row.channel_message_id, allow_sending_without_reply=True)
                if row is not None and row.channel_message_id
                else None
            ),
        )


def _keyboard(card: CardData) -> InlineKeyboardMarkup | None:
    row: list[InlineKeyboardButton] = []
    if can_take(card):
        row.append(
            InlineKeyboardButton(text=tx.TAKE_BUTTON, callback_data=f"{TAKE_PREFIX}{card.lead_id}")
        )
    if card.crm_url.startswith("https://"):
        row.append(InlineKeyboardButton(text=tx.OPEN_BUTTON, url=card.crm_url))
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


async def _load(
    session: AsyncSession, escalation_id: int, cfg: AppSettings
) -> tuple[Escalation, CardData] | None:
    escalation = await session.get(Escalation, escalation_id)
    if escalation is None:
        return None
    lead = await session.get(Lead, escalation.lead_id)
    if lead is None:
        return None
    taken_by = (
        await session.get(User, escalation.taken_by_user_id)
        if escalation.taken_by_user_id
        else None
    )
    stored: dict[str, Any] = dict(lead.qualification or {})
    card = CardData(
        lead_id=lead.id,
        display_name=lead.display_name,
        language=lead.language,
        score=lead.score,
        stage=lead.stage,
        need_summary=lead.need_summary,
        product_interest=list(lead.product_interest or []),
        timeline=stored.get("timeline"),
        decision_role=stored.get("decision_role"),
        priority=escalation.priority,
        reason_codes=list(escalation.reason_codes or []),
        reason_text=escalation.reason_text,
        recommendation=escalation.recommendation,
        status=escalation.status,
        taken_by=taken_by.full_name if taken_by else None,
        taken_at=escalation.taken_at,
        sla_overdue=escalation.sla_notified_at is not None,
        last_lead_message=await _last_lead_text(session, lead.id),
        crm_url=f"{cfg.company.crm_base_url.rstrip('/')}/leads/{lead.id}",
        timezone=cfg.business_hours.timezone,
        kb_gap_streak=cfg.escalation.kb_gap_streak,
    )
    return escalation, card


def _waiting_minutes(escalation: Escalation) -> int:
    """Сколько лид ждёт с момента передачи — в напоминании вместо «всё ещё ждёт»."""
    return max(0, int((datetime.now(UTC) - escalation.created_at).total_seconds() // 60))


async def _last_lead_text(session: AsyncSession, lead_id: int) -> str | None:
    stmt = (
        select(Message.text)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.lead_id == lead_id, Message.role == "lead", Message.text != "")
        .order_by(Message.id.desc())
        .limit(1)
    )
    value: str | None = await session.scalar(stmt)
    return value


async def _mentions(session: AsyncSession, user_ids: Sequence[int]) -> str:
    if not user_ids:
        return ""
    users = (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()
    return " ".join(
        f'<a href="tg://user?id={u.tg_user_id}">{escape(u.full_name)}</a>'
        for u in users
        if u.tg_user_id
    )
