"""Ход диалога целиком: Postgres, kb-mcp и crm-mcp по HTTP, модель — записанные ответы."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

import pytest
from pydantic import AnyHttpUrl
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.dialog.graph import DialogAgent
from app.agents.llm import ToolCall
from app.agents.mcp_client import McpToolClient
from app.config import Settings
from app.container import Container
from app.mcp import crm_server, kb_server
from app.mcp.common import build_app
from app.models.kb import KbGap
from app.models.leads import Lead, Message, TelegramIdentity
from app.models.qualification import Escalation, StageTransition
from app.repositories.leads import ERASED_TEXT
from app.services.conversation import ConversationService, Incoming
from app.services.settings import SettingsService
from tests.fakes import FakeEmbedder
from tests.integration.kb_seed import hash_threshold, seed_kb
from tests.integration.servers import free_port, running
from tests.unit.agents.fakes import ReplayModel, reply

pytestmark = pytest.mark.integration

USER = 7001


@dataclass
class Stack:
    service: ConversationService
    model: ReplayModel
    sessions: async_sessionmaker[AsyncSession]
    hooks: list[tuple[str, int]] = field(default_factory=list)
    erased_keys: list[str] = field(default_factory=list)


@pytest.fixture
async def stack(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> AsyncIterator[Stack]:
    await seed_kb(sessions)
    await hash_threshold(sessions)
    container = Container(live_settings)
    container.__dict__["session_factory"] = sessions
    container.__dict__["embedder"] = FakeEmbedder()
    async with AsyncExitStack() as stack:
        urls = {}
        for name, module in (("kb", kb_server), ("crm", crm_server)):
            port = free_port()
            app = build_app(module.create_server(container), f"{name}-mcp", port)
            urls[name] = await stack.enter_async_context(running(app, port))
        config = live_settings.model_copy(
            update={"kb_mcp_url": AnyHttpUrl(urls["kb"]), "crm_mcp_url": AnyHttpUrl(urls["crm"])}
        )
        model = ReplayModel()
        result = Stack(service=None, model=model, sessions=sessions)  # type: ignore[arg-type]

        async def on_activity(lead_id: int) -> None:
            result.hooks.append(("activity", lead_id))

        async def on_escalation(lead_id: int, escalation_id: int) -> None:
            result.hooks.append(("escalation", lead_id))

        async def erase_attachments(keys: list[str]) -> None:
            result.erased_keys.extend(keys)

        result.service = ConversationService(
            sessions,
            SettingsService(sessions, ttl_s=0),
            DialogAgent(McpToolClient(config), model),
            config.agent_context_key_bytes,
            on_activity=on_activity,
            on_escalation=on_escalation,
            erase_attachments=erase_attachments,
        )
        yield result


def msg(text: str, **extra: object) -> Incoming:
    return Incoming(tg_user_id=USER, chat_id=USER, text=text, first_name="Азиз", **extra)  # type: ignore[arg-type]


async def lead_row(sessions: async_sessionmaker[AsyncSession]) -> Lead:
    async with sessions() as session:
        return (await session.scalars(select(Lead))).one()


async def only_escalation(sessions: async_sessionmaker[AsyncSession]) -> Escalation:
    async with sessions() as session:
        return (await session.scalars(select(Escalation))).one()


async def consented(stack: Stack) -> None:
    await stack.service.start(msg("/start", language_code="ru"))
    await stack.service.accept_consent(USER)


async def test_first_message_asks_consent_and_does_not_answer(stack: Stack) -> None:
    out = await stack.service.handle_message(msg("Сколько стоит касса?", language_code="ru"))
    assert [o.keyboard for o in out] == [None, "consent"]
    assert stack.model.requests == []
    async with stack.sessions() as session:
        roles = (await session.scalars(select(Message.role).order_by(Message.id))).all()
    assert roles == ["lead", "bot", "bot"]


async def test_question_asked_before_consent_is_answered_right_after(stack: Stack) -> None:
    await stack.service.handle_message(
        msg("Что входит в тариф Старт для кассы RT-POS?", language_code="ru")
    )
    stack.model.responses.append(reply("Тариф Старт включает одну кассу и облачный учёт."))
    out = await stack.service.accept_consent(USER)
    assert [o.text for o in out] == [
        "Спасибо! Отвечаю на ваш вопрос.",
        "Тариф Старт включает одну кассу и облачный учёт.",
    ]


async def test_greeting_before_consent_is_not_treated_as_a_question(stack: Stack) -> None:
    await stack.service.handle_message(msg("Hi", language_code="en"))
    out = await stack.service.accept_consent(USER)
    assert len(out) == 1
    assert "question" in out[0].text.lower()  # «Please ask your question», а не «Answering…»
    assert stack.model.requests == []


async def test_declined_consent_is_explained_and_nothing_is_answered(stack: Stack) -> None:
    await stack.service.handle_message(msg("Сколько стоит касса?", language_code="ru"))
    out = await stack.service.decline_consent(USER)
    assert "/start" in out[0].text
    assert stack.model.requests == []
    assert (await lead_row(stack.sessions)).consent_given_at is None


async def test_answers_from_kb_after_consent(stack: Stack) -> None:
    await consented(stack)
    stack.model.responses.append(reply("Тариф Старт включает одну кассу и облачный учёт."))
    out = await stack.service.handle_message(msg("Что входит в тариф Старт для кассы RT-POS?"))
    assert out[-1].text.startswith("Тариф Старт")
    system = stack.model.requests[0][0]["content"]
    assert "Тариф Старт" in system
    assert "<fragment" in system
    async with stack.sessions() as session:
        bot = (await session.scalars(select(Message).order_by(Message.id.desc()))).first()
    assert bot is not None
    assert bot.meta["action"] == "answer"
    assert bot.meta["kb_hits"]


async def test_out_of_kb_question_falls_back_and_registers_gap(stack: Stack) -> None:
    await consented(stack)
    out = await stack.service.handle_message(msg("Какая завтра погода в Париже?"))
    assert stack.model.requests == []
    assert out[-1].text
    assert out[-1].keyboard == "handoff_offer"  # передачу решает лид кнопкой (аудит P-09)
    lead = await lead_row(stack.sessions)
    assert lead.consecutive_fallbacks == 1
    assert ("activity", lead.id) in stack.hooks
    async with stack.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(KbGap)) == 1
        assert await session.scalar(select(func.count()).select_from(Escalation)) == 0


async def test_second_fallback_in_a_row_escalates(stack: Stack) -> None:
    await consented(stack)
    await stack.service.handle_message(msg("Какая завтра погода в Париже?"))
    out = await stack.service.handle_message(msg("А курс доллара на завтра?"))
    escalation = await only_escalation(stack.sessions)
    assert (escalation.reason_codes, escalation.priority) == (["kb_gap_streak"], "warm")
    # Без «могу передать, если хотите» перед «Передаю…» и без кнопок.
    assert len(out) == 1
    assert out[0].keyboard is None
    lead = await lead_row(stack.sessions)
    assert (lead.stage, lead.owner_mode) == ("handoff", "paused")


async def test_attachment_without_text_escalates_with_info_priority(stack: Stack) -> None:
    await consented(stack)
    file = {"kind": "file", "name": "tz.pdf", "mime": "application/pdf", "size": 10}
    out = await stack.service.handle_message(msg("", attachments=[file]))
    assert len(out) == 1
    escalation = await only_escalation(stack.sessions)
    assert escalation.priority == "info"


async def test_human_request_hands_off_and_pauses_bot(stack: Stack) -> None:
    await consented(stack)
    await stack.service.handle_message(msg("/human", human_requested=True))
    lead = await lead_row(stack.sessions)
    assert (lead.owner_mode, lead.stage) == ("paused", "handoff")
    assert ("escalation", lead.id) in stack.hooks
    escalation = await only_escalation(stack.sessions)
    assert (escalation.reason_codes, escalation.priority) == (["human_requested"], "hot")
    async with stack.sessions() as session:
        transition = (await session.scalars(select(StageTransition))).one()
    assert transition.to_stage == "handoff"

    out = await stack.service.handle_message(msg("Ау, есть кто?"))
    assert out == []
    assert stack.model.requests == []


async def test_callback_tool_records_signal(stack: Stack) -> None:
    await consented(stack)
    call = ToolCall(id="c1", name="request_callback", arguments={"preferred_time": "завтра 10:00"})
    stack.model.responses += [reply("", call), reply("Хорошо, менеджер свяжется с вами завтра.")]
    # Фейковые векторы дают низкое сходство для смешанной фразы — снижаем порог.
    await SettingsService(stack.sessions).update("kb", {"min_score": 0.3, "top_k": 6}, None)
    out = await stack.service.handle_message(msg("Тариф Старт для кассы RT-POS, позвоните завтра"))
    assert out[0].text.startswith("Хорошо")
    lead = await lead_row(stack.sessions)
    assert lead.qualification["signals"]["requested_contact"] is True
    assert lead.qualification["callback"]["preferred_time"] == "завтра 10:00"
    escalation = await only_escalation(stack.sessions)
    assert escalation.reason_codes == ["callback_requested"]
    assert lead.owner_mode == "paused"
    assert len(out) == 2  # ответ модели + уведомление о передаче менеджеру


async def test_delete_asks_for_confirmation_first(stack: Stack) -> None:
    await consented(stack)
    out = await stack.service.erase_prompt(USER)
    assert [o.keyboard for o in out] == ["erase_confirm"]
    assert (await lead_row(stack.sessions)).erased_at is None


async def test_delete_erases_messages_and_unlinks_identity(stack: Stack) -> None:
    await consented(stack)
    await stack.service.handle_message(
        msg("", attachments=[{"kind": "file", "storage_key": "tg/1/2/voice.ogg", "stored": True}])
    )
    stack.hooks.clear()
    async with stack.sessions() as session, session.begin():
        identity = (await session.scalars(select(TelegramIdentity))).one()
        identity.phone_e164 = "+998901234567"  # Q-020: номер из кнопки «Поделиться номером»
    await stack.service.erase(USER)
    async with stack.sessions() as session:
        phones = (await session.scalars(select(TelegramIdentity.phone_e164))).all()
    assert phones == [None]  # /delete стирает и номер
    async with stack.sessions() as session:
        escalation = (await session.scalars(select(Escalation))).one()
    assert (escalation.status, escalation.outcome) == ("closed", "erased")
    assert stack.erased_keys == ["tg/1/2/voice.ogg"]
    assert ("escalation", escalation.lead_id) in stack.hooks
    lead = await lead_row(stack.sessions)
    assert lead.erased_at is not None
    assert lead.display_name == ""
    async with stack.sessions() as session:
        texts = set((await session.scalars(select(Message.text))).all())
    assert texts == {ERASED_TEXT}
    out = await stack.service.handle_message(msg("Снова здравствуйте"))
    assert out[-1].keyboard == "consent"


async def test_agent_failure_is_reported_to_the_team_without_silencing_the_bot(
    stack: Stack,
) -> None:
    await consented(stack)
    # Модель «упала»: записанных ответов нет.
    out = await stack.service.handle_message(msg("Что входит в тариф Старт для кассы RT-POS?"))
    assert "менеджер его увидит" in out[-1].text
    escalation = await only_escalation(stack.sessions)
    assert (escalation.reason_codes, escalation.priority) == (["agent_unavailable"], "info")
    assert (await lead_row(stack.sessions)).owner_mode == "bot"
    assert ("escalation", escalation.lead_id) in stack.hooks
    assert out[-1].keyboard == "handoff_offer"


async def test_second_agent_failure_in_a_row_hands_off_without_repeating_the_apology(
    stack: Stack,
) -> None:
    await consented(stack)
    first = await stack.service.handle_message(msg("Что входит в тариф Старт для кассы RT-POS?"))
    second = await stack.service.handle_message(msg("А для двух касс?"))
    assert second[-1].text != first[-1].text
    assert "менеджер его увидит" not in second[-1].text
    escalation = await only_escalation(stack.sessions)
    assert escalation.priority == "warm"
    assert (await lead_row(stack.sessions)).owner_mode == "paused"
