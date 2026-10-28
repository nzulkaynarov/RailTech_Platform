"""Канал команды (SPEC §8.2, §9.1): пост-карточка передачи, SLA, напоминания, сводка.

Пост всегда рендерится из текущего состояния БД — `sync` идемпотентен:
нет поста → отправить, есть → отредактировать. Вызывается из воркера.
Пост удалён или бот потерял канал → карточка публикуется заново (если передачу ещё можно
забрать) или молча завершается — «Забрать» на устаревшей карточке не остаётся.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from typing import Final

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    ReplyParameters,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.platform_links import LinkBase
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.schemas.settings import AppSettings
from app.services import channel_texts as tx
from app.services.channel_card import (
    PRIORITY_RANK,
    CardData,
    can_take,
    duration,
    is_silent,
    needs_sla,
    render,
    take_data,
    why,
)
from app.services.notification_data import lead_link, load_card, mentions
from app.services.settings import SettingsService
from app.services.staff_notifier import SEND_TIMEOUT_S

logger = structlog.get_logger(__name__)
DIGEST_LIMIT: Final = 30
# Ответы Telegram, после которых пост править бессмысленно: удалён, канал сменился/недоступен.
_GONE: Final = (
    "message to edit not found",
    "message can't be edited",
    "chat not found",
    "message_id_invalid",
    "message not found",
)


@dataclass(frozen=True, slots=True)
class SyncResult:
    ok: bool
    raised_to_hot: bool = False  # карточка стала горячей — срок реакции заново (задача ставит SLA)


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
        return (await self.publish(escalation_id)).ok

    async def publish(self, escalation_id: int) -> SyncResult:
        """Пост карточки: отправить, отредактировать или опубликовать заново."""
        cfg = await self._settings.get()
        if self._bot is None:
            logger.info("channel_not_configured", escalation_id=escalation_id)
            return SyncResult(ok=False)
        async with self._sessions() as session:
            loaded = await load_card(session, escalation_id, cfg, await self._settings.links())
        if loaded is None:
            return SyncResult(ok=False)
        escalation, card = loaded
        if escalation.channel_message_id is None:
            return SyncResult(ok=await self._post(cfg, escalation, card))
        chat = escalation.channel_chat_id or cfg.notifications.channel_id
        if chat is None or not await self._edit(chat, escalation.channel_message_id, card):
            await self._forget_post(escalation_id)
            logger.info("channel_post_gone", escalation_id=escalation_id)
            return SyncResult(ok=await self._post(cfg, escalation, card))
        raised = (
            card.priority == "hot"
            and escalation.posted_priority not in (None, "hot")
            and card.status == "open"
        )
        await self._save_post(escalation_id, chat, escalation.channel_message_id, card.priority)
        if raised:
            await self._reply(chat, escalation.channel_message_id, tx.RAISED_HOT, escalation_id)
        return SyncResult(ok=True, raised_to_hot=raised)

    async def reopened(self, escalation_id: int) -> None:
        """«Отложить» истекло: ответ на карточку, чтобы пост снова заметили."""
        async with self._sessions() as session:
            row = await session.get(Escalation, escalation_id)
        if row is not None and row.channel_message_id and row.channel_chat_id:
            chat, message_id = row.channel_chat_id, row.channel_message_id
            await self._reply(chat, message_id, tx.SNOOZE_OVER, escalation_id)

    async def handed_over(self, lead_id: int, user_id: int) -> int | None:
        """«Передать коллеге»: передача лида закреплена за новым ответственным (для карточки)."""
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(Escalation)
                .where(Escalation.lead_id == lead_id, Escalation.status == "taken")
                .order_by(Escalation.id.desc())
                .limit(1)
                .with_for_update()
            )
            if row is None:
                return None
            row.taken_by_user_id, row.taken_at = user_id, datetime.now(UTC)
            return row.id

    async def mark_sla_overdue(self, escalation_id: int) -> bool:
        """SLA истёк, а эскалацию не забрали: пометить пост и упомянуть дежурных.

        Info-передачи — сигналы без срока реакции (бот продолжает отвечать)."""
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            row = await session.get(Escalation, escalation_id, with_for_update=True)
            if (
                row is None
                or row.status != "open"
                or row.sla_notified_at is not None
                or not needs_sla(row.priority)
                or (row.sla_due_at is not None and row.sla_due_at > datetime.now(UTC))
            ):
                return False  # срок перезапущен (стал горячим, вернулся из «Отложить»)
            row.sla_notified_at = datetime.now(UTC)
        await self.sync(escalation_id)
        await self._remind(cfg, row, tx.SLA_REMINDER)
        return True

    async def remind(self, escalation_id: int) -> bool:
        cfg = await self._settings.get()
        async with self._sessions() as session:
            row = await session.get(Escalation, escalation_id)
        if row is None or row.status != "open" or not needs_sla(row.priority):
            return False
        await self._remind(cfg, row, tx.REMINDER)
        return True

    async def digest(self) -> int:
        """Ежедневная сводка открытых эскалаций (09:05 по Ташкенту): горячие первыми."""
        cfg = await self._settings.get()
        links = await self._settings.links()
        channel = cfg.notifications.channel_id
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(Escalation)
                    .where(Escalation.status.in_(("open", "snoozed")))
                    .order_by(Escalation.created_at, Escalation.id)
                )
            ).all()
            if self._bot is None or channel is None or not rows:
                return 0
            ordered = sorted(rows, key=lambda r: (PRIORITY_RANK.get(r.priority, 9), r.created_at))
            lines = [tx.DIGEST_TITLE.format(count=len(rows))]
            for r in ordered[:DIGEST_LIMIT]:
                lines.append(await _digest_line(session, r, links))
        if len(rows) > DIGEST_LIMIT:
            lines.append(tx.DIGEST_MORE.format(count=len(rows) - DIGEST_LIMIT))
        await self._send(channel, "\n".join(lines), "digest")
        return len(rows)

    async def _post(self, cfg: AppSettings, escalation: Escalation, card: CardData) -> bool:
        channel = cfg.notifications.channel_id
        if self._bot is None or channel is None:
            logger.info("channel_not_configured", escalation_id=escalation.id)
            return False
        if not can_take(card) or is_silent(card.reason_codes):
            return False
        sent = await self._bot.send_message(
            channel,
            render(card),
            parse_mode="HTML",
            reply_markup=_keyboard(card),
            request_timeout=SEND_TIMEOUT_S,
        )
        await self._save_post(escalation.id, channel, sent.message_id, card.priority)
        return True

    async def _edit(self, chat: int, message_id: int, card: CardData) -> bool:
        """False — поста больше нет (удалён, канал сменился); сетевые сбои — наверх, на ретрай."""
        if self._bot is None:
            return True
        try:
            await self._bot.edit_message_text(
                render(card),
                chat_id=chat,
                message_id=message_id,
                parse_mode="HTML",
                reply_markup=_keyboard(card),
                request_timeout=SEND_TIMEOUT_S,
            )
        except TelegramForbiddenError:
            return False
        except TelegramBadRequest as exc:
            text = str(exc).lower()
            if "not modified" in text:
                return True
            if any(marker in text for marker in _GONE):
                return False
            raise
        return True

    async def _save_post(self, escalation_id: int, chat: int, message_id: int, prio: str) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(Escalation, escalation_id, with_for_update=True)
            if row is not None:
                row.channel_message_id, row.channel_chat_id = message_id, chat
                row.posted_priority = prio

    async def _forget_post(self, escalation_id: int) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(Escalation, escalation_id, with_for_update=True)
            if row is not None:
                row.channel_message_id = row.channel_chat_id = None

    async def _remind(self, cfg: AppSettings, row: Escalation, template: str) -> None:
        channel = row.channel_chat_id or cfg.notifications.channel_id
        if channel is None:
            return
        async with self._sessions() as session:
            people = await mentions(session, cfg.notifications.duty_user_ids)
        lead = lead_link(await self._settings.links(), row.lead_id)
        waited = duration(datetime.now(UTC) - row.created_at)
        text = template.format(lead=lead, waited=waited) + (f"\n{people}" if people else "")
        await self._send(channel, text, "reminder", reply_to=row.channel_message_id)

    async def _reply(self, chat: int, message_id: int, text: str, escalation_id: int) -> None:
        await self._send(chat, text, f"reply-{escalation_id}", reply_to=message_id)

    async def _send(self, chat: int, text: str, key: str, *, reply_to: int | None = None) -> bool:
        if self._bot is None:
            return False
        try:
            await self._bot.send_message(
                chat,
                text,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
                reply_parameters=(
                    ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)
                    if reply_to
                    else None
                ),
                request_timeout=SEND_TIMEOUT_S,
            )
        except TelegramAPIError as exc:
            logger.warning("channel_send_failed", key=key, error=type(exc).__name__)
            return False
        return True


def _keyboard(card: CardData) -> InlineKeyboardMarkup | None:
    row: list[InlineKeyboardButton] = []
    if can_take(card):
        row.append(
            InlineKeyboardButton(text=tx.TAKE_BUTTON, callback_data=take_data(card.escalation_id))
        )
    if card.crm_url.startswith("https://"):
        row.append(InlineKeyboardButton(text=tx.OPEN_BUTTON, url=card.crm_url))
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


async def _digest_line(session: AsyncSession, row: Escalation, links: LinkBase) -> str:
    lead = await session.get(Lead, row.lead_id)
    name = escape((lead.display_name if lead else "") or tx.NO_NAME)
    reason = escape(why(row.reason_codes or [], None) or tx.PRIORITY.get(row.priority, ""))
    return tx.DIGEST_LINE.format(
        icon=tx.PRIORITY_ICON.get(row.priority, "•"),
        lead=lead_link(links, row.lead_id),
        name=name,
        why=reason,
        waited=duration(datetime.now(UTC) - row.created_at),
    )
