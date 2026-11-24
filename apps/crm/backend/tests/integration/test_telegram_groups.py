"""Группа с секретарём (ADR-0032): привязка кодом, запись только привязанной группы, бот молчит.

Привязка — код из группы, ошибки кода, канал команды, повторная привязка; запись — текст, правка,
файл, файл больше предела, сотрудник, свои сообщения; непривязанная группа не пишется; в группе нет
ни ответа ИИ, ни сценария лида личного чата; нет прав администратора — состояние «нужны права».
"""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import TelegramMethod
from aiogram.types import Update
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot import channel, chat_member, client_handlers, handlers, staff_link
from app.bot import groups as groups_router
from app.bot.runtime import build_dispatcher
from app.bus import runtime
from app.bus.runtime import build_bus
from app.config import Settings
from app.domain import telegram_groups as rules
from app.domain.errors import ConflictError, NotFoundError
from app.main import create_app
from app.models.auth import AuditLog, User
from app.models.clients import Client
from app.models.integrations import TelegramGroup
from app.models.leads import Conversation, Lead, Message
from app.repositories import telegram_chats
from app.security.principal import Principal
from app.services.settings import SettingsService
from app.services.telegram_groups import GroupMessage, TelegramGroupService
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration

GROUP = -1001700000001
TEAM = -1001700000099
BOT_ID = 777
_update_ids = iter(range(1000, 10**6))


class FakeBot(Bot):
    """Bot API без сети: исходящие вызовы копятся в `calls`, скачивание пишет заготовку."""

    def __init__(self) -> None:
        super().__init__("777:fake-token-for-tests-0000")
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.pin_fails = False
        self.download_fails = False
        self.member_status = "administrator"

    async def __call__(
        self, method: TelegramMethod[Any], request_timeout: int | None = None
    ) -> Any:
        name = type(method).__name__
        data = method.model_dump(exclude_none=True)
        self.calls.append((name, data))
        if name == "SendMessage":
            chat = {"id": data["chat_id"], "type": "supergroup"}
            return SimpleNamespace(message_id=500 + len(self.calls), chat=chat)
        if name == "PinChatMessage":
            if self.pin_fails:
                raise TelegramBadRequest(method=method, message="not enough rights to pin")
            return True
        if name == "GetChatMember":
            return SimpleNamespace(status=self.member_status)
        return True

    async def download(  # type: ignore[override]
        self, file: Any, destination: Any = None, **_: Any
    ) -> Any:
        if self.download_fails:
            raise TelegramBadRequest(method=None, message="file is too big")  # type: ignore[arg-type]
        destination.write(b"file-body")
        return destination

    def sent(self) -> list[str]:
        return [d["text"] for n, d in self.calls if n == "SendMessage"]


class Storage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def put(self, bucket: str, key: str, body: bytes, mime: str) -> None:
        self.files[key] = body


class Spy:
    """Сервис диалога: любое обращение к нему — ответ ИИ или сценарий лида; тест требует ноль."""

    def __init__(self) -> None:
        self.touched: list[str] = []

    def __getattr__(self, name: str) -> Callable[..., Any]:
        async def call(*_: Any, **__: Any) -> Any:
            self.touched.append(name)
            return []

        return call


@pytest.fixture
def bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Any]:
    stand = build_bus(sessions, None)
    runtime.set_bus(stand)
    yield stand
    runtime.set_bus(None)


@pytest.fixture(autouse=True)
async def binder(sessions: async_sessionmaker[AsyncSession]) -> None:
    account, _ = await make_user(sessions, "binder@railtech.uz", ["manager"])
    BINDER["id"] = account.id


@pytest.fixture
def bot() -> FakeBot:
    return FakeBot()


@pytest.fixture
def groups(
    sessions: async_sessionmaker[AsyncSession], bot: FakeBot, bus: Any
) -> TelegramGroupService:
    async def provider() -> FakeBot:
        return bot

    return TelegramGroupService(sessions, SettingsService(sessions, ttl_s=0), provider)


@pytest.fixture
def spy() -> Spy:
    return Spy()


@pytest.fixture
def storage() -> Storage:
    return Storage()


def dispatcher(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    spy: Spy,
    storage: Storage,
) -> Any:
    for module in (channel, chat_member, client_handlers, groups_router, handlers, staff_link):
        module.router._parent_router = None  # роутеры модулей одни на процесс, диспетчер — на тест
    return build_dispatcher(
        sessions,
        spy,  # type: ignore[arg-type]
        SettingsService(sessions, ttl_s=0),
        storage,  # type: ignore[arg-type]
        "attachments",
        client_groups=groups,
    )


def group_message(
    text: str | None, sender: int = 55, message_id: int = 10, **extra: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "message_id": message_id,
        "date": int(time.time()),
        "chat": {"id": GROUP, "type": "supergroup", "title": "Клиент"},
        "from": {"id": sender, "is_bot": False, "first_name": "Азиз", "last_name": "Каримов"},
        **extra,
    }
    if text is not None:
        body["text"] = text
    return body


async def feed(dp: Any, bot: FakeBot, **fields: Any) -> None:
    payload = {"update_id": next(_update_ids), **fields}
    await dp.feed_update(bot, Update.model_validate(payload))


def member_update(
    status: str, *, can_pin: bool = True, chat_id: int = GROUP, kind: str = "supergroup"
) -> dict[str, Any]:
    new: dict[str, Any] = {
        "status": status,
        "user": {"id": BOT_ID, "is_bot": True, "first_name": "bot"},
    }
    if status == "administrator":
        new |= {
            "can_be_edited": False,
            "is_anonymous": False,
            "can_manage_chat": True,
            "can_delete_messages": True,
            "can_manage_video_chats": False,
            "can_restrict_members": True,
            "can_promote_members": False,
            "can_change_info": False,
            "can_invite_users": True,
            "can_post_stories": False,
            "can_edit_stories": False,
            "can_delete_stories": False,
            "can_send_welcome_messages": False,
            "can_pin_messages": can_pin,
        }
    return {
        "my_chat_member": {
            "chat": {"id": chat_id, "type": kind, "title": "Клиент"},
            "from": {"id": 55, "is_bot": False, "first_name": "Азиз"},
            "date": int(time.time()),
            "old_chat_member": {"status": "left", "user": new["user"]},
            "new_chat_member": new,
        }
    }


async def make_client(sessions: async_sessionmaker[AsyncSession], name: str = "ООО Порядок") -> int:
    async with sessions() as session, session.begin():
        client = Client(name=name)
        session.add(client)
        await session.flush()
        return client.id


BINDER: dict[str, int] = {}


def principal() -> Principal:
    return Principal(user_id=BINDER["id"], full_name="Менеджер", roles=("manager",))


async def pending_code(groups: TelegramGroupService) -> str:
    code = await groups.bot_membership(
        GROUP, "Клиент", "supergroup", status="administrator", can_pin=True
    )
    assert code is not None
    return code


async def bound(
    sessions: async_sessionmaker[AsyncSession], groups: TelegramGroupService
) -> tuple[int, int]:
    client_id = await make_client(sessions)
    await groups.bind(principal(), await pending_code(groups), client_id)
    return client_id, GROUP


async def messages(sessions: async_sessionmaker[AsyncSession]) -> list[Message]:
    async with sessions() as session:
        return list((await session.scalars(select(Message).order_by(Message.id))).all())


# --- бот становится администратором: запись группы и код ------------------------------------------


async def test_admin_bot_creates_pending_record_and_posts_the_code(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    dp = dispatcher(sessions, groups, spy, storage)
    await feed(dp, bot, **member_update("administrator"))
    async with sessions() as session:
        group = await session.get(TelegramGroup, GROUP)
        candidate = await telegram_chats.get(session, GROUP)
    assert group is not None
    assert group.status == "pending"
    assert group.bot_is_admin
    assert candidate is not None  # путь канала команды не сломан
    assert group.connect_code is not None
    assert [group.connect_code in text for text in bot.sent()] == [True]
    assert "RailTech" not in bot.sent()[0]  # без названия продукта: простой текст
    # Повторный апдейт с прежним живым кодом второй код не выпускает.
    await feed(dp, bot, **member_update("administrator"))
    assert len(bot.sent()) == 1


async def test_channel_is_not_a_client_group(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    dp = dispatcher(sessions, groups, spy, storage)
    await feed(dp, bot, **member_update("administrator", chat_id=TEAM, kind="channel"))
    async with sessions() as session:
        assert await session.get(TelegramGroup, TEAM) is None
        assert await telegram_chats.get(session, TEAM) is not None
    assert bot.sent() == []


async def test_configured_team_group_never_becomes_a_client_group(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    code = await pending_code(groups)
    settings = SettingsService(sessions, ttl_s=0)
    current = (await settings.raw())["notifications"]
    await settings.update("notifications", {**current, "channel_id": GROUP}, None)
    client_id = await make_client(sessions)
    with pytest.raises(ConflictError) as raised:
        await groups.bind(principal(), code, client_id)
    assert raised.value.details["reason"] == rules.GROUP_IS_TEAM_CHANNEL
    assert (
        await groups.bot_membership(
            GROUP, "Команда", "supergroup", status="administrator", can_pin=True
        )
        is None
    )


# --- привязка кодом -------------------------------------------------------------------------------


async def test_bind_creates_conversation_pins_notice_and_audits(
    sessions: async_sessionmaker[AsyncSession], groups: TelegramGroupService, bot: FakeBot
) -> None:
    client_id = await make_client(sessions)
    code = await pending_code(groups)
    view = await groups.bind(principal(), f" {code.lower()} ", client_id, "uz")
    assert (view.status, view.client_id, view.access, view.language) == (
        "bound",
        client_id,
        "ok",
        "uz",
    )
    assert view.lead_id is not None
    assert [n for n, _ in bot.calls] == ["PinChatMessage", "SendMessage"][::-1]
    assert bot.sent() == [rules.NOTICE["uz"]]
    async with sessions() as session:
        group = await session.get(TelegramGroup, GROUP)
        lead = await session.get(Lead, view.lead_id)
        conversation = (await session.scalars(select(Conversation))).one()
        audit = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "telegram_group.bind"))
        ).one()
    assert group is not None
    assert group.connect_code is None
    assert group.notice_pinned_at is not None
    assert lead is not None
    assert (lead.source, lead.client_id) == ("group", client_id)
    assert (conversation.channel, conversation.tg_chat_id, conversation.lead_id) == (
        "group",
        GROUP,
        lead.id,
    )
    assert audit.after is not None
    assert audit.after["client_id"] == client_id


async def test_notice_texts_are_in_three_languages() -> None:
    assert (
        rules.NOTICE["ru"]
        == "Сообщения и файлы этой группы сохраняются в карточке клиента RailTech."
    )
    assert (
        set(rules.NOTICE)
        == set(rules.CODE_MESSAGE)
        == set(rules.NEEDS_ADMIN_MESSAGE)
        == {"ru", "uz", "en"}
    )


async def test_wrong_code_is_not_found(
    sessions: async_sessionmaker[AsyncSession], groups: TelegramGroupService
) -> None:
    client_id = await make_client(sessions)
    await pending_code(groups)
    with pytest.raises(NotFoundError) as raised:
        await groups.bind(principal(), "ZZZZZZ", client_id)
    assert raised.value.details["reason"] == rules.GROUP_CODE_INVALID


async def test_expired_code_is_refused_and_connect_issues_a_new_one(
    sessions: async_sessionmaker[AsyncSession], groups: TelegramGroupService
) -> None:
    client_id = await make_client(sessions)
    code = await pending_code(groups)
    async with sessions() as session, session.begin():
        await session.execute(
            update(TelegramGroup).values(code_expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    with pytest.raises(ConflictError) as raised:
        await groups.bind(principal(), code, client_id)
    assert raised.value.details["reason"] == rules.GROUP_CODE_EXPIRED
    fresh = await groups.issue_code(GROUP)
    assert fresh is not None
    assert (await groups.bind(principal(), fresh, client_id)).status == "bound"


async def test_bound_group_cannot_be_bound_again(
    sessions: async_sessionmaker[AsyncSession], groups: TelegramGroupService
) -> None:
    client_id, _ = await bound(sessions, groups)
    assert await groups.issue_code(GROUP) is None  # /connect у привязанной группы молчит
    async with sessions() as session, session.begin():
        await session.execute(update(TelegramGroup).values(connect_code="ABC234"))
    with pytest.raises(ConflictError) as raised:
        await groups.bind(principal(), "ABC234", client_id)
    assert raised.value.details["reason"] == rules.GROUP_ALREADY_BOUND


async def test_unknown_client_is_not_found(groups: TelegramGroupService) -> None:
    code = await pending_code(groups)
    with pytest.raises(NotFoundError):
        await groups.bind(principal(), code, 987654)


async def test_pin_refused_shows_admin_required(
    sessions: async_sessionmaker[AsyncSession], groups: TelegramGroupService, bot: FakeBot
) -> None:
    bot.pin_fails = True
    client_id = await make_client(sessions)
    view = await groups.bind(principal(), await pending_code(groups), client_id)
    assert view.access == "admin_required"
    listed = await groups.groups()
    assert [g.access for g in listed] == ["admin_required"]


async def test_bot_without_admin_rights_is_shown_as_admin_required(
    groups: TelegramGroupService,
) -> None:
    await groups.bot_membership(
        GROUP, "Клиент", "supergroup", status="administrator", can_pin=False
    )
    assert (await groups.groups())[0].access == "admin_required"
    await groups.bot_membership(GROUP, "Клиент", "supergroup", status="member", can_pin=False)
    view = (await groups.groups())[0]
    assert view.access == "admin_required"
    assert view.status == "pending"


async def test_unbind_stops_recording_and_keeps_history(
    sessions: async_sessionmaker[AsyncSession], groups: TelegramGroupService
) -> None:
    await bound(sessions, groups)
    await groups.capture(GroupMessage(GROUP, 1, 55, "Азиз", None, "до отключения"))
    await groups.unbind(principal(), GROUP)
    assert await groups.capture(GroupMessage(GROUP, 2, 55, "Азиз", None, "после")) is False
    assert [m.text for m in await messages(sessions)] == ["до отключения"]
    with pytest.raises(ConflictError):
        await groups.unbind(principal(), GROUP)


async def test_rebinding_to_another_client_leaves_old_history_with_old_client(
    sessions: async_sessionmaker[AsyncSession], groups: TelegramGroupService
) -> None:
    first, _ = await bound(sessions, groups)
    await groups.capture(GroupMessage(GROUP, 1, 55, "Азиз", None, "старое"))
    await groups.unbind(principal(), GROUP)
    second = await make_client(sessions, "ООО Другой")
    code = await groups.issue_code(GROUP)
    assert code is not None
    await groups.bind(principal(), code, second)
    await groups.capture(GroupMessage(GROUP, 2, 55, "Азиз", None, "новое"))
    async with sessions() as session:
        rows = (
            await session.execute(
                select(Conversation.client_id, Message.text).join(
                    Message, Message.conversation_id == Conversation.id
                )
            )
        ).all()
    assert sorted((r.client_id, r.text) for r in rows) == sorted(
        [(first, "старое"), (second, "новое")]
    )


async def test_settings_are_stored_for_later_steps(
    sessions: async_sessionmaker[AsyncSession], groups: TelegramGroupService
) -> None:
    await bound(sessions, groups)
    view = await groups.update_settings(principal(), GROUP, topic_mode="none", language="en")
    assert (view.topic_mode, view.language) == ("none", "en")


# --- запись переписки -----------------------------------------------------------------------------


async def test_text_reply_and_sender_are_recorded(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    _client_id, _ = await bound(sessions, groups)
    dp = dispatcher(sessions, groups, spy, storage)
    await feed(
        dp,
        bot,
        message=group_message(
            "Когда будет счёт?",
            reply_to_message={
                "message_id": 9,
                "date": 1,
                "chat": {"id": GROUP, "type": "supergroup"},
            },
        ),
    )
    [message] = await messages(sessions)
    assert (message.role, message.text, message.tg_message_id) == ("lead", "Когда будет счёт?", 10)
    assert message.meta["channel"] == "group"
    assert (message.meta["author_name"], message.meta["tg_user_id"]) == ("Азиз Каримов", 55)
    assert message.meta["is_staff"] is False
    assert message.meta["reply_to_tg_message_id"] == 9
    assert spy.touched == []


async def test_edit_updates_text_with_edited_mark(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    await bound(sessions, groups)
    dp = dispatcher(sessions, groups, spy, storage)
    await feed(dp, bot, message=group_message("сумма 100"))
    await feed(dp, bot, edited_message=group_message("сумма 120", edit_date=int(time.time())))
    [message] = await messages(sessions)
    assert message.text == "сумма 120"
    assert message.meta["previous_texts"] == ["сумма 100"]
    assert "edited_at" in message.meta


async def test_file_is_stored_through_the_attachment_pipeline(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    await bound(sessions, groups)
    dp = dispatcher(sessions, groups, spy, storage)
    document = {
        "file_id": "F1",
        "file_unique_id": "u1",
        "file_name": "акт.pdf",
        "mime_type": "application/pdf",
        "file_size": 1024,
    }
    await feed(dp, bot, message=group_message(None, document=document, caption="Подпишите"))
    [message] = await messages(sessions)
    [attachment] = message.attachments
    assert message.text == "Подпишите"
    assert attachment["stored"] is True
    assert attachment["storage_key"] in storage.files


async def test_oversized_file_is_kept_as_a_reference(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    await bound(sessions, groups)
    dp = dispatcher(sessions, groups, spy, storage)
    big = {
        "file_id": "F2",
        "file_unique_id": "u2",
        "file_name": "план.dwg",
        "file_size": 21 * 1024 * 1024,
    }
    await feed(dp, bot, message=group_message(None, document=big))
    [message] = await messages(sessions)
    [attachment] = message.attachments
    assert attachment["stored"] is False
    assert attachment["too_large"] is True
    assert attachment["note"] == "файл больше 20 МБ — откройте в группе"
    assert storage.files == {}


async def test_file_that_telegram_refuses_to_give_is_still_a_record(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    await bound(sessions, groups)
    bot.download_fails = True
    dp = dispatcher(sessions, groups, spy, storage)
    doc = {"file_id": "F3", "file_unique_id": "u3", "file_name": "a.pdf", "file_size": 100}
    await feed(dp, bot, message=group_message(None, document=doc))
    [message] = await messages(sessions)
    assert message.attachments[0]["stored"] is False


async def test_staff_sender_is_recognised_without_a_new_lead(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    await bound(sessions, groups)
    account, _ = await make_user(sessions, "sales@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == account.id).values(tg_user_id=900))
    dp = dispatcher(sessions, groups, spy, storage)
    async with sessions() as session:
        leads_before = await session.scalar(select(func.count()).select_from(Lead))
    await feed(dp, bot, message=group_message("Счёт выставлен", sender=900))
    [message] = await messages(sessions)
    assert (message.role, message.sent_by_user_id, message.meta["is_staff"]) == (
        "manager",
        account.id,
        True,
    )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Lead)) == leads_before
    assert spy.touched == []


async def test_own_and_other_bot_messages_are_ignored(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    await bound(sessions, groups)
    dp = dispatcher(sessions, groups, spy, storage)
    own = group_message("Сообщения сохраняются", sender=BOT_ID)
    own["from"]["is_bot"] = True
    other = group_message("реклама", sender=888, message_id=11)
    other["from"]["is_bot"] = True
    await feed(dp, bot, message=own)
    await feed(dp, bot, message=other)
    assert await messages(sessions) == []


async def test_service_messages_without_content_are_not_recorded(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    await bound(sessions, groups)
    dp = dispatcher(sessions, groups, spy, storage)
    await feed(dp, bot, message=group_message(None, new_chat_title="Новое имя"))
    assert await messages(sessions) == []


# --- что бот в группе не делает -------------------------------------------------------------------


async def test_unbound_group_stores_nothing_but_the_record(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    dp = dispatcher(sessions, groups, spy, storage)
    await feed(dp, bot, **member_update("administrator"))  # pending
    await feed(dp, bot, message=group_message("секрет"))
    doc = {"file_id": "F9", "file_unique_id": "u9", "file_name": "x.pdf", "file_size": 10}
    await feed(dp, bot, message=group_message(None, document=doc, message_id=11))
    async with sessions() as session:
        counts = [
            await session.scalar(select(func.count()).select_from(table))
            for table in (Message, Conversation, Lead)
        ]
    assert counts == [0, 0, 0]
    assert storage.files == {}
    assert not any(name == "GetFile" for name, _ in bot.calls)


async def test_group_gets_no_ai_reply_and_no_lead_flow(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    await bound(sessions, groups)
    bot.calls.clear()  # уведомление при привязке — не ответ клиенту
    dp = dispatcher(sessions, groups, spy, storage)
    texts = ["Здравствуйте", "/start", "/human", "/docs", "/delete", "помогите"]
    for index, text in enumerate(texts):
        await feed(dp, bot, message=group_message(text, message_id=20 + index))
    assert spy.touched == []
    assert bot.sent() == []
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Lead)) == 1  # только якорный


async def test_group_flood_does_not_trigger_rate_limit_replies_or_leads(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    dp = dispatcher(sessions, groups, spy, storage)
    for index in range(60):
        await feed(dp, bot, message=group_message(f"м{index}", message_id=100 + index))
    assert bot.sent() == []
    assert spy.touched == []
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Lead)) == 0


async def test_connect_command_is_answered_to_admins_only(
    sessions: async_sessionmaker[AsyncSession],
    groups: TelegramGroupService,
    bot: FakeBot,
    spy: Spy,
    storage: Storage,
) -> None:
    dp = dispatcher(sessions, groups, spy, storage)
    await feed(dp, bot, **member_update("administrator"))
    bot.calls.clear()
    bot.member_status = "member"
    await feed(
        dp,
        bot,
        message=group_message(
            "/connect", message_id=30, entities=[{"type": "bot_command", "offset": 0, "length": 8}]
        ),
    )
    assert bot.sent() == []
    bot.member_status = "administrator"
    await feed(
        dp,
        bot,
        message=group_message(
            "/connect", message_id=31, entities=[{"type": "bot_command", "offset": 0, "length": 8}]
        ),
    )
    assert len(bot.sent()) == 1


# --- Платформа: права и маршруты ------------------------------------------------------------------


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    groups: TelegramGroupService,
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        test_client.app.state.container.__dict__["telegram_groups"] = groups  # type: ignore[attr-defined]
        yield test_client


async def test_api_bind_list_unbind_and_rights(
    sessions: async_sessionmaker[AsyncSession], groups: TelegramGroupService, client: TestClient
) -> None:
    code = await pending_code(groups)
    client_id = await make_client(sessions)
    viewer, password = await make_user(sessions, "viewer@railtech.uz", ["viewer"])
    reader = login(client, viewer.email, password)
    manager, password = await make_user(sessions, "manager@railtech.uz", ["manager"])
    writer = login(client, manager.email, password)
    url = "/api/v1/telegram-groups"
    assert client.get(url).status_code == 401
    listed = client.get(url, headers=reader).json()
    assert [(g["chat_id"], g["status"], g["code_active"]) for g in listed] == [
        (GROUP, "pending", True)
    ]
    assert "connect_code" not in listed[0]
    assert code not in str(listed)
    body = {"code": code, "client_id": client_id}
    assert client.post(f"{url}/bind", json=body, headers=reader).status_code == 403
    wrong = client.post(f"{url}/bind", json={**body, "code": "NOPE99"}, headers=writer)
    assert (wrong.status_code, wrong.json()["details"]["reason"]) == (404, rules.GROUP_CODE_INVALID)
    done = client.post(f"{url}/bind", json=body, headers=writer)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "bound"
    assert done.json()["lead_id"] is not None
    again = client.post(f"{url}/bind", json=body, headers=writer)
    assert (again.status_code, again.json()["details"]["reason"]) == (404, rules.GROUP_CODE_INVALID)
    patched = client.patch(f"{url}/{GROUP}", json={"topic_mode": "none"}, headers=writer)
    assert patched.json()["topic_mode"] == "none"
    assert client.post(f"{url}/{GROUP}/unbind", headers=reader).status_code == 403
    assert client.post(f"{url}/{GROUP}/unbind", headers=writer).status_code == 200
    assert client.get(url, headers=writer).json()[0]["status"] == "unbound"
    assert client.post(f"{url}/{GROUP}/unbind", headers=writer).status_code == 409
