"""Обработка входящего сообщения лида (SPEC §3.3, §6.4, §7.1).

Порядок: лид и идентичность → сохранить сообщение → согласие → язык →
owner_mode → агент (вне транзакции) → сохранить ответ, счётчики, пробел KB →
триггеры хода (человек, стоп-слова, звонок, серия fallback, вложение) →
эскалация (SPEC §8.2) → хуки (квалификатор, уведомления). Один ход на лида
одновременно.
"""

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.dialog.graph import DialogAgent
from app.agents.dialog.state import DialogResult
from app.domain.consent import consent_required
from app.domain.dialog_policy import Action
from app.domain.language import Language, detect_language
from app.domain.stages import OwnerMode, Stage, TransitionSource
from app.domain.triggers import TriggerSignals, evaluate
from app.integrations.llm_usage import lead_scope
from app.models.leads import Conversation, Lead
from app.repositories import leads as repo
from app.schemas.settings import AppSettings
from app.security.agent_context import issue
from app.services import escalation, stages
from app.services.conversation_erasure import ErasureMixin
from app.services.conversation_support import (
    apply_counters,
    consent_prompt,
    current_lead,
    escalated,
    lang_of,
    lead_of,
    notify_owner,
    pending_question,
    report_failure,
    turn_meta,
    turn_signals,
    update_language,
    verified_client,
)
from app.services.conversation_types import (
    ActivityHook,
    AttachmentsEraser,
    EscalationHook,
    Incoming,
    Keyboard,
    Outgoing,
    Turn,
)
from app.services.kb.gaps import register_gap
from app.services.settings import SettingsService
from app.services.waiting import while_waiting

__all__ = [
    "ActivityHook",
    "ConversationService",
    "EscalationHook",
    "Incoming",
    "Outgoing",
]

logger = structlog.get_logger(__name__)


class ConversationService(ErasureMixin):
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        agent: DialogAgent,
        agent_key: bytes,
        on_activity: ActivityHook | None = None,
        on_escalation: EscalationHook | None = None,
        erase_attachments: AttachmentsEraser | None = None,
        on_lead_message: ActivityHook | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._agent = agent
        self._agent_key = agent_key
        self._on_activity = on_activity
        self._on_escalation = on_escalation
        self._erase_attachments = erase_attachments
        self._on_lead_message = on_lead_message
        self._locks: dict[int, asyncio.Lock] = {}

    async def handle_message(self, inc: Incoming) -> list[Outgoing]:
        cfg = await self._settings.get()
        early, turn, escalated = await self._receive(inc, cfg)
        await notify_owner(self._on_lead_message, early, turn)  # Q-010: личка менеджеру
        if turn is None:
            if escalated is not None:
                await self._fire(*escalated)
            elif early:
                await self._fire(lead_of(early), None)
            return early
        return early + await self._answer(turn, cfg)

    async def _answer(self, turn: Turn, cfg: AppSettings) -> list[Outgoing]:
        lock = self._locks.setdefault(turn.lead_id, asyncio.Lock())
        async with lock:
            result = await self._run_agent(turn, cfg)
            outgoing, escalation = await self._persist(turn, result, cfg)
        # Квалификатор — только для потенциальных клиентов (у клиента стадия customer).
        await self._fire(
            turn.lead_id if turn.mode == "prospect" else None, escalation, turn.lead_id
        )
        return outgoing

    async def start(self, inc: Incoming) -> list[Outgoing]:
        """/start: приветствие; до согласия — ещё и текст согласия с кнопкой."""
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead, conversation, _ = await self._ensure_lead(session, inc)
            if consent_required(
                lead.consent_given_at, lead.consent_version, cfg.texts.consent_version
            ):
                return await consent_prompt(session, conversation, lead, cfg, is_new=True)
            text = cfg.texts.greeting.get(lang_of(lead), company=cfg.company.name)
            await repo.add_message(session, conversation_id=conversation.id, role="bot", text=text)
        return [Outgoing(text)]

    async def help(self, tg_user_id: int) -> list[Outgoing]:
        cfg = await self._settings.get()
        language = await self.language_of(tg_user_id)
        return [Outgoing(cfg.texts.help.get(language, company=cfg.company.name))]

    async def unsupported(self, tg_user_id: int) -> list[Outgoing]:
        """Стикер, опрос и т. п.: состояние не меняется, просим написать текстом."""
        cfg = await self._settings.get()
        return [Outgoing(cfg.texts.unsupported_message.get(await self.language_of(tg_user_id)))]

    async def language_of(self, tg_user_id: int) -> Language:
        async with self._sessions() as session:
            lead, _ = await current_lead(session, tg_user_id)
        return lang_of(lead) if lead else "ru"

    async def language_prompt(self, tg_user_id: int) -> list[Outgoing]:
        cfg = await self._settings.get()
        language = await self.language_of(tg_user_id)
        return [Outgoing(cfg.texts.language_prompt.get(language), keyboard="language")]

    async def accept_consent(self, tg_user_id: int) -> list[Outgoing]:
        """Согласие получено; вопрос, заданный до согласия, получает ответ сразу (аудит P-13)."""
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead, conversation = await current_lead(session, tg_user_id)
            if lead is None or conversation is None:
                return []
            lead.consent_given_at = datetime.now(UTC)
            lead.consent_version = cfg.texts.consent_version
            question = await pending_question(session, conversation.id)
            texts = cfg.texts
            text = (texts.consent_accepted_pending if question else texts.consent_accepted).get(
                lang_of(lead)
            )
            message = await repo.add_message(
                session, conversation_id=conversation.id, role="bot", text=text
            )
            turn = None
            if question and lead.owner_mode == OwnerMode.BOT:
                client_id = await verified_client(session, tg_user_id)
                turn = Turn(
                    lead.id,
                    lang_of(lead),
                    lead.stage,
                    lead.owner_mode,
                    question,
                    False,
                    client_id=client_id,
                )
        accepted = [Outgoing(text, message_id=message.id)]
        return accepted + (await self._answer(turn, cfg) if turn else [])

    async def decline_consent(self, tg_user_id: int) -> list[Outgoing]:
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead, conversation = await current_lead(session, tg_user_id)
            language = lang_of(lead) if lead else "ru"
            text = cfg.texts.consent_declined.get(language)
            if conversation is not None:
                await repo.add_message(
                    session, conversation_id=conversation.id, role="bot", text=text
                )
        return [Outgoing(text)]

    async def set_language(self, tg_user_id: int, language: Language) -> list[Outgoing]:
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead, _ = await current_lead(session, tg_user_id)
            if lead is None:
                return [Outgoing(cfg.texts.language_set.get(language))]
            lead.language, lead.language_confirmed, lead.language_candidate = language, True, None
        return [Outgoing(cfg.texts.language_set.get(language))]

    async def _receive(
        self, inc: Incoming, cfg: AppSettings
    ) -> tuple[list[Outgoing], Turn | None, tuple[int, int] | None]:
        """Сообщение лида до хода агента: (ответ без модели, ход агента, (лид, эскалация))."""
        async with self._sessions() as session, session.begin():
            lead, conversation, is_new = await self._ensure_lead(session, inc)
            now = datetime.now(UTC)
            await repo.add_message(
                session,
                conversation_id=conversation.id,
                role="lead",
                text=inc.text,
                tg_message_id=inc.message_id,
                attachments=inc.attachments,
            )
            lead.last_lead_msg_at = now
            if lead.stage in (Stage.UNRESPONSIVE, Stage.LOST):
                await stages.transition(
                    session, lead, Stage.ENGAGED, TransitionSource.SYSTEM, reason="lead wrote again"
                )
            update_language(lead, inc.text)
            if consent_required(
                lead.consent_given_at, lead.consent_version, cfg.texts.consent_version
            ):
                return await consent_prompt(session, conversation, lead, cfg, is_new), None, None
            if lead.owner_mode == OwnerMode.PAUSED:
                waiting = await while_waiting(
                    session,
                    conversation,
                    lead,
                    text=inc.text,
                    human_requested=inc.human_requested,
                    language=lang_of(lead),
                    cfg=cfg,
                    now=now,
                )
                out = (
                    [Outgoing(waiting.text, message_id=waiting.message_id, lead_id=lead.id)]
                    if waiting.text
                    else []
                )
                return out, None, escalated(lead.id, waiting.escalation_id)
            if inc.attachments and not inc.text.strip():
                text = cfg.texts.attachment_received.get(lang_of(lead))
                message = await repo.add_message(
                    session, conversation_id=conversation.id, role="bot", text=text
                )
                hits = evaluate(TriggerSignals(attachment_received=True), cfg.escalation.triggers())
                applied = await escalation.apply(session, lead, hits, cfg, now)
                out = [Outgoing(text, message_id=message.id, lead_id=lead.id)]
                return out, None, escalated(lead.id, applied.escalation_id if applied else None)
            turn = Turn(
                lead.id,
                lang_of(lead),
                lead.stage,
                lead.owner_mode,
                inc.text,
                inc.human_requested,
                bool(inc.attachments),
                await verified_client(session, inc.tg_user_id),
            )
        return [], turn, None

    async def _ensure_lead(
        self, session: AsyncSession, inc: Incoming
    ) -> tuple[Lead, Conversation, bool]:
        identity = await repo.get_identity(session, inc.tg_user_id)
        lead = (
            await repo.get_lead(session, identity.lead_id)
            if identity and identity.lead_id
            else None
        )
        conversation = await repo.open_conversation(session, lead.id) if lead else None
        if lead is not None and conversation is not None and lead.erased_at is None:
            return lead, conversation, False
        language = (
            inc.language_code
            if inc.language_code in ("ru", "uz", "en")
            else detect_language(inc.text)
        )
        lead, _, conversation = await repo.create_lead_with_identity(
            session,
            tg_user_id=inc.tg_user_id,
            username=inc.username,
            first_name=inc.first_name,
            chat_id=inc.chat_id,
            language=language,
            identity=identity,
        )
        logger.info("lead_created", lead_id=lead.id)
        return lead, conversation, True

    async def _run_agent(self, turn: Turn, cfg: AppSettings) -> DialogResult | None:
        token = issue(
            self._agent_key,
            lead_id=turn.lead_id,
            mode=turn.mode,
            language=turn.language,
            client_id=turn.client_id,
        )
        try:
            with lead_scope(turn.lead_id):
                return await self._agent.run(
                    lead_id=turn.lead_id,
                    text=turn.text,
                    language=turn.language,
                    context_token=token,
                    settings=cfg,
                    human_requested=turn.human,
                    stage=turn.stage,
                    mode=turn.mode,
                )
        except Exception:
            logger.exception("dialog_agent_failed", lead_id=turn.lead_id)
            return None

    async def _persist(
        self, turn: Turn, result: DialogResult | None, cfg: AppSettings
    ) -> tuple[list[Outgoing], int | None]:
        async with self._sessions() as session, session.begin():
            lead = await repo.get_lead(session, turn.lead_id, for_update=True)
            conversation = await repo.open_conversation(session, turn.lead_id)
            if lead is None or conversation is None:
                return [], None
            if result is None:
                text = cfg.texts.service_unavailable.get(turn.language)
                await repo.add_message(
                    session,
                    conversation_id=conversation.id,
                    role="system",
                    text=text,
                    meta={"error": "agent_unavailable"},
                )
                failure = await report_failure(
                    session, lead, cfg, TriggerSignals(agent_unavailable=True)
                )
                return [Outgoing(text)], failure
            apply_counters(lead, result)
            if result.action == Action.FALLBACK:
                await register_gap(
                    session,
                    question=turn.text,
                    language=turn.language,
                    best_score=result.best_score,
                    lead_id=lead.id,
                )
            now = datetime.now(UTC)
            hits = evaluate(turn_signals(turn, result, lead), cfg.escalation.triggers())
            applied = await escalation.apply(
                session, lead, hits, cfg, now, reason_text=f"dialog: {result.reason}"
            )
            notice = applied.plan.lead_text if applied else None
            fallback = result.action == Action.FALLBACK
            # «Могу передать, если хотите» и сразу «Передаю…» — противоречие: оставляем второе.
            replies = [result.reply] if result.reply and not (fallback and notice) else []
            offer: Keyboard | None = "handoff_offer" if fallback and not notice else None
            if notice is not None and result.action != Action.HANDOFF:
                notice_text = cfg.lead_notice(notice, turn.language)
                replies.append(notice_text)
            outgoing: list[Outgoing] = []
            for index, text in enumerate(replies):
                message = await repo.add_message(
                    session,
                    conversation_id=conversation.id,
                    role="bot",
                    text=text,
                    meta=turn_meta(result) if index == 0 else {"notice": notice},
                )
                document = result.document if index == 0 else None
                outgoing.append(
                    Outgoing(
                        text,
                        keyboard=offer if index == 0 else None,
                        message_id=message.id,
                        document=document,
                        language=turn.language,
                        lead_id=turn.lead_id,
                    )
                )
            if replies:
                lead.last_bot_msg_at = now
        return outgoing, applied.escalation_id if applied else None

    async def report_delivery_failure(self, lead_id: int) -> None:
        """Бот не смог отправить файл клиенту — команда узнаёт через info-эскалацию."""
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead = await repo.get_lead(session, lead_id, for_update=True)
            signals = TriggerSignals(delivery_failed=True)
            escalation_id = await report_failure(session, lead, cfg, signals) if lead else None
        await self._fire(None, escalation_id, lead_id)

    async def _fire(
        self, lead_id: int | None, escalation_id: int | None, escalated_lead: int | None = None
    ) -> None:
        target = escalated_lead or lead_id
        try:
            if escalation_id is not None and target is not None and self._on_escalation is not None:
                await self._on_escalation(target, escalation_id)
            if lead_id is not None and self._on_activity is not None:
                await self._on_activity(lead_id)
        except Exception:
            logger.exception("conversation_hooks_failed", lead_id=lead_id)
