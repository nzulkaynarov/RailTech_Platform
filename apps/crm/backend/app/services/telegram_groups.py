"""Группа с секретарём (ADR-0032): привязка группы Telegram к клиенту и запись её переписки.

Бот, ставший администратором группы, заводит запись `pending` и пишет в группу код. Сотрудник с
правом на клиентов вводит код в Платформе и выбирает клиента (`bind`): группа становится `bound`,
заводятся якорный лид `source = 'group'` и беседа `channel = 'group'`, секретарь пишет и закрепляет
уведомление. Сообщения пишутся только в `bound`; в остальных состояниях — только запись группы.
Канал команды клиентской группой не становится: его chat_id из настроек отсекается и при записи
группы, и при привязке.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.domain import telegram_groups as rules
from app.domain.errors import ConflictError, NotFoundError
from app.domain.stages import Stage
from app.models.clients import Client
from app.models.integrations import TelegramGroup
from app.models.leads import Conversation, Lead
from app.repositories import telegram_groups as repo
from app.security import audit
from app.security.audit import Actor
from app.security.principal import Principal
from app.services import message_log
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

GroupBotProvider = Callable[[], Awaitable[Any]]


class GroupBot(Protocol):
    """Часть Bot API, которой пользуется секретарь (aiogram `Bot` подходит как есть)."""

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> Any: ...

    async def pin_chat_message(self, chat_id: int, message_id: int, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class GroupView:
    chat_id: int
    title: str
    chat_type: str
    status: str
    access: str
    client_id: int | None
    client_name: str | None
    lead_id: int | None
    topic_mode: str
    language: str | None
    code_active: bool
    bound_at: datetime | None
    detected_at: datetime


@dataclass(frozen=True, slots=True)
class GroupMessage:
    """Сообщение группы в виде, не зависящем от aiogram."""

    chat_id: int
    message_id: int
    sender_id: int | None
    sender_name: str
    sender_username: str | None
    text: str
    reply_to_message_id: int | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


class TelegramGroupService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        bot: GroupBotProvider | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._bot = bot
        self._clock = clock

    # --- бот в группе -------------------------------------------------------------------------

    async def bot_membership(
        self,
        chat_id: int,
        title: str,
        chat_type: str,
        *,
        status: str,
        can_pin: bool,
    ) -> str | None:
        """Бота добавили, повысили, понизили или убрали (`my_chat_member`).

        Возвращает код, который боту нужно написать в группу, — только когда он выпущен сейчас."""
        if chat_type not in rules.GROUP_CHAT_TYPES:
            return None
        team_channel = (await self._settings.get()).notifications.channel_id
        if team_channel == chat_id:
            return None
        is_admin = status in {"administrator", "creator"}
        gone = status in {"left", "kicked"}
        now = self._clock()
        async with self._sessions() as session, session.begin():
            group = await repo.get(session, chat_id, for_update=True)
            if group is None:
                if not is_admin:
                    return None
                group = TelegramGroup(
                    chat_id=chat_id, title=title[:255], chat_type=chat_type, status="pending"
                )
                session.add(group)
            group.title = title[:255]
            group.chat_type = chat_type
            group.bot_is_admin = is_admin
            group.can_pin = is_admin and can_pin
            if gone:
                group.status = "removed"
                group.connect_code = group.code_expires_at = None
                return None
            if group.status == "removed":
                group.status = "bound" if group.client_id is not None else "pending"
            if group.status == "pending" and is_admin and not self._code_alive(group, now):
                return self._issue(group, now)
            return None

    async def issue_code(self, chat_id: int) -> str | None:
        """Новый код для группы, которая ещё не привязана (`/connect`); привязанной — None."""
        async with self._sessions() as session, session.begin():
            group = await repo.get(session, chat_id, for_update=True)
            if group is None or group.status == "bound":
                return None
            if (await self._settings.get()).notifications.channel_id == chat_id:
                return None
            if group.status in {"unbound", "removed"}:
                group.status = "pending"
            return self._issue(group, self._clock())

    def _issue(self, group: TelegramGroup, now: datetime) -> str:
        code = rules.new_code()
        group.connect_code = code
        group.code_expires_at = rules.code_expiry(now)
        return code

    @staticmethod
    def _code_alive(group: TelegramGroup, now: datetime) -> bool:
        return (
            group.connect_code is not None
            and group.code_expires_at is not None
            and group.code_expires_at > now
        )

    async def language_of(self, chat_id: int) -> str:
        async with self._sessions() as session:
            group = await repo.get(session, chat_id)
        if group is not None and group.language is not None:
            return group.language
        return rules.DEFAULT_LANGUAGE

    # --- Платформа ----------------------------------------------------------------------------

    async def groups(self, limit: int = 100, offset: int = 0) -> list[GroupView]:
        async with self._sessions() as session:
            rows = await repo.list_all(session, self._clock(), limit, offset)
            return await self._views(session, rows)

    async def bind(
        self, who: Principal, code: str, client_id: int, language: str | None = None
    ) -> GroupView:
        try:
            return await self._bind(who, code, client_id, language)
        except (NotFoundError, ConflictError) as exc:
            # Неверный и просроченный код — след в журнале (виден перебор). Отдельная транзакция:
            # в той, что откатилась, записи бы не осталось.
            async with self._sessions() as session, session.begin():
                await audit.record(
                    session,
                    Actor(who.user_id, "user", who.ip),
                    "telegram_group.bind_failed",
                    "telegram_group",
                    None,
                    after={"reason": exc.details.get("reason"), "client_id": client_id},
                )
            raise

    async def _bind(
        self, who: Principal, code: str, client_id: int, language: str | None
    ) -> GroupView:
        now = self._clock()
        async with self._sessions() as session, session.begin():
            group = await repo.by_code(session, rules.normalize_code(code))
            if group is None:
                raise NotFoundError("code not found", reason=rules.GROUP_CODE_INVALID)
            if (await self._settings.get()).notifications.channel_id == group.chat_id:
                raise ConflictError(
                    "the team channel is not a client group", reason=rules.GROUP_IS_TEAM_CHANNEL
                )
            if group.status == "bound":
                raise ConflictError("group is already bound", reason=rules.GROUP_ALREADY_BOUND)
            if not self._code_alive(group, now):
                raise ConflictError("code has expired", reason=rules.GROUP_CODE_EXPIRED)
            client = await session.get(Client, client_id)
            if client is None:
                raise NotFoundError("client not found", field="client_id")
            group.status = "bound"
            group.client_id = client.id
            group.connect_code = group.code_expires_at = None
            group.bound_by_user_id = who.user_id
            group.bound_at = now
            if language is not None:
                group.language = language
            await self._attach_conversation(session, group, client)
            await audit.record(
                session,
                Actor(who.user_id, "user", who.ip),
                "telegram_group.bind",
                "telegram_group",
                group.chat_id,
                after={"client_id": client.id, "title": group.title},
            )
            chat_id = group.chat_id
        await self._announce(chat_id)
        async with self._sessions() as session:
            fresh = await repo.get(session, chat_id)
            assert fresh is not None  # noqa: S101 — только что привязали
            [view] = await self._views(session, [fresh])
        return view

    async def _attach_conversation(
        self, session: AsyncSession, group: TelegramGroup, client: Client
    ) -> Lead:
        """Якорный лид клиента и беседа группы; прежняя история остаётся у прежнего клиента."""
        lead = await repo.group_lead(session, client.id)
        if lead is None:
            lead = Lead(
                display_name=client.name[:255],
                company_name=client.name[:255] or None,
                source=repo.GROUP,
                stage=Stage.CUSTOMER.value,
                client_id=client.id,
                assigned_user_id=client.owner_user_id,
            )
            session.add(lead)
            await session.flush()
            await bus_events.lead_created(session, lead, Actor.system())
        conversation = await repo.conversation_of(session, group.chat_id, for_update=True)
        if conversation is not None and conversation.client_id != client.id:
            # Группу отдали другому клиенту: прежняя история остаётся у прежнего клиента.
            conversation.is_open = False
            conversation.tg_chat_id = None
            conversation = None
        if conversation is None:
            session.add(
                Conversation(
                    lead_id=lead.id,
                    channel=repo.GROUP,
                    tg_chat_id=group.chat_id,
                    client_id=client.id,
                )
            )
        else:
            conversation.is_open = True
        await session.flush()
        return lead

    async def _announce(self, chat_id: int) -> None:
        """Уведомление в группу и закреп; нет прав — состояние «нужны права администратора»."""
        provider = self._bot
        bot = await provider() if provider is not None else None
        if bot is None:
            return  # бот не запущен: прав не знаем, состояние не меняем
        language = await self.language_of(chat_id)
        message_id: int | None = None
        pinned = False
        try:
            sent = await bot.send_message(chat_id, rules.text(rules.NOTICE, language))
            message_id = int(sent.message_id)
            await bot.pin_chat_message(chat_id, message_id, disable_notification=True)
            pinned = True
        except TelegramAPIError as exc:
            logger.warning("group_notice_failed", chat_id=chat_id, error=type(exc).__name__)
        async with self._sessions() as session, session.begin():
            group = await repo.get(session, chat_id, for_update=True)
            if group is None:
                return
            group.notice_message_id = message_id
            if pinned:
                group.notice_pinned_at = self._clock()
            else:
                group.can_pin = False

    async def unbind(self, who: Principal, chat_id: int) -> None:
        async with self._sessions() as session, session.begin():
            group = await repo.get(session, chat_id, for_update=True)
            if group is None:
                raise NotFoundError("group not found")
            if group.status != "bound":
                raise ConflictError("group is not bound", reason=rules.GROUP_NOT_BOUND)
            before = {"client_id": group.client_id}
            group.status = "unbound"
            group.client_id = None
            group.connect_code = group.code_expires_at = None
            conversation = await repo.conversation_of(session, chat_id, for_update=True)
            if conversation is not None:
                conversation.is_open = False
            await audit.record(
                session,
                Actor(who.user_id, "user", who.ip),
                "telegram_group.unbind",
                "telegram_group",
                chat_id,
                before=before,
            )

    async def update_settings(
        self, who: Principal, chat_id: int, *, topic_mode: str | None, language: str | None
    ) -> GroupView:
        async with self._sessions() as session, session.begin():
            group = await repo.get(session, chat_id, for_update=True)
            if group is None:
                raise NotFoundError("group not found")
            before = {"topic_mode": group.topic_mode, "language": group.language}
            if topic_mode is not None:
                group.topic_mode = topic_mode
            if language is not None:
                group.language = language
            await audit.record(
                session,
                Actor(who.user_id, "user", who.ip),
                "telegram_group.settings",
                "telegram_group",
                chat_id,
                before=before,
                after={"topic_mode": group.topic_mode, "language": group.language},
            )
            await session.flush()
            [view] = await self._views(session, [group])
            return view

    async def _views(self, session: AsyncSession, rows: Sequence[TelegramGroup]) -> list[GroupView]:
        """Представления пакетом: имена клиентов и якорные лиды — двумя запросами на страницу."""
        names = await repo.client_names(session, [r.client_id for r in rows if r.client_id])
        leads = await repo.lead_ids(session, [r.chat_id for r in rows if r.status == "bound"])
        now = self._clock()
        return [
            GroupView(
                chat_id=g.chat_id,
                title=g.title,
                chat_type=g.chat_type,
                status=g.status,
                access=rules.access_of(bot_is_admin=g.bot_is_admin, can_pin=g.can_pin),
                client_id=g.client_id,
                client_name=names.get(g.client_id) if g.client_id is not None else None,
                lead_id=leads.get(g.chat_id),
                topic_mode=g.topic_mode,
                language=g.language,
                code_active=g.status == "pending" and self._code_alive(g, now),
                bound_at=g.bound_at,
                detected_at=g.created_at,
            )
            for g in rows
        ]

    # --- запись переписки ---------------------------------------------------------------------

    async def _is_team_channel(self, chat_id: int) -> bool:
        return (await self._settings.get()).notifications.channel_id == chat_id

    async def is_bound(self, chat_id: int) -> bool:
        if await self._is_team_channel(chat_id):
            return False
        async with self._sessions() as session:
            group = await repo.get(session, chat_id)
        return group is not None and group.status == "bound"

    async def capture(self, incoming: GroupMessage) -> bool:
        """Сообщение привязанной группы — в беседу клиента. Не привязана — ничего не пишем."""
        if await self._is_team_channel(incoming.chat_id):
            return False  # канал команды клиентской группой не бывает, даже если запись осталась
        async with self._sessions() as session, session.begin():
            group = await repo.get(session, incoming.chat_id)
            if group is None or group.status != "bound":
                return False
            conversation = await repo.conversation_of(session, incoming.chat_id, for_update=True)
            if conversation is None:
                return False
            if await repo.message_by_tg_id(session, conversation.id, incoming.message_id):
                return False
            staff = (
                await repo.staff_by_telegram(session, incoming.sender_id)
                if incoming.sender_id is not None
                else None
            )
            meta: dict[str, Any] = {
                "channel": repo.GROUP,
                "author_name": incoming.sender_name,
                "tg_user_id": incoming.sender_id,
                "tg_username": incoming.sender_username,
                "is_staff": staff is not None,
                "group_chat_id": incoming.chat_id,
            }
            if staff is not None:
                meta |= {"mode": "manager", "delivery": "sent"}
            if incoming.reply_to_message_id is not None:
                meta["reply_to_tg_message_id"] = incoming.reply_to_message_id
            needs_notice = group.notice_message_id is None
            await message_log.add(
                session,
                conversation,
                role="manager" if staff is not None else "lead",
                text=incoming.text,
                tg_message_id=incoming.message_id,
                sent_by_user_id=staff.id if staff is not None else None,
                attachments=incoming.attachments,
                meta=meta,
            )
        if needs_notice:
            # Уведомление при привязке не вышло (бот был недоступен): повтор на сообщении группы.
            await self._announce(incoming.chat_id)
        return True

    async def edit(self, chat_id: int, message_id: int, new_text: str) -> bool:
        """Правка сообщения: текст обновляется, прежний остаётся в `previous_texts`."""
        if await self._is_team_channel(chat_id):
            return False
        async with self._sessions() as session, session.begin():
            group = await repo.get(session, chat_id)
            if group is None or group.status != "bound":
                return False
            conversation = await repo.conversation_of(session, chat_id)
            if conversation is None:
                return False
            message = await repo.message_by_tg_id(session, conversation.id, message_id)
            if message is None or message.text == new_text:
                return False
            meta = dict(message.meta or {})
            previous = [*meta.get("previous_texts", []), message.text]
            meta["previous_texts"] = previous[-rules.MAX_PREVIOUS_TEXTS :]
            meta["edited_at"] = self._clock().isoformat()
            message.text = new_text
            message.meta = meta
            return True
