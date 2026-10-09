"""Обработка входящего сообщения лида (SPEC §3.3, §6.4, §7.1).

Порядок: лид и идентичность → сохранить сообщение → согласие → язык →
owner_mode → агент (вне транзакции) → сохранить ответ, счётчики, пробел KB →
триггеры хода (человек, стоп-слова, звонок, серия fallback, вложение) →
эскалация (SPEC §8.2) → хуки (квалификатор, уведомления). Один ход на лида
одновременно.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.dialog.graph import DialogAgent
from app.agents.dialog.state import DialogResult
from app.domain.consent import consent_required
from app.domain.dialog_policy import Action
from app.domain.language import Language, detect_language, next_language
from app.domain.stages import OwnerMode, Stage, TransitionSource
from app.domain.triggers import TriggerSignals, evaluate
from app.models.clients import Client
from app.models.leads import Conversation, Lead
from app.repositories import leads as repo
from app.schemas.settings import AppSettings
from app.security.agent_context import issue
from app.services import escalation, stages
from app.services.kb.gaps import register_gap
from app.services.settings import SettingsService
from app.services.waiting import while_waiting

logger = structlog.get_logger(__name__)

Keyboard = Literal["consent", "language", "erase_confirm"]
ActivityHook = Callable[[int], Awaitable[None]]
EscalationHook = Callable[[int, int], Awaitable[None]]
AttachmentsEraser = Callable[[list[str]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Incoming:
    tg_user_id: int
    chat_id: int
    text: str
    username: str | None = None
    first_name: str | None = None
    language_code: str | None = None
    message_id: int | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    human_requested: bool = False


@dataclass(frozen=True, slots=True)
class Outgoing:
    text: str
    keyboard: Keyboard | None = None
    message_id: int | None = None
    language: Language = "ru"
    lead_id: int | None = None
    document: dict[str, Any] | None = None


@dataclass
class _Turn:
    lead_id: int
    language: Language
    stage: str
    owner_mode: str
    text: str
    human: bool
    attachment: bool = False
    client_id: int | None = None

    @property
    def mode(self) -> Literal["prospect", "customer"]:
        return "customer" if self.client_id is not None else "prospect"


class ConversationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        agent: DialogAgent,
        agent_key: bytes,
        on_activity: ActivityHook | None = None,
        on_escalation: EscalationHook | None = None,
        erase_attachments: AttachmentsEraser | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._agent = agent
        self._agent_key = agent_key
        self._on_activity = on_activity
        self._on_escalation = on_escalation
        self._erase_attachments = erase_attachments
        self._locks: dict[int, asyncio.Lock] = {}

    async def handle_message(self, inc: Incoming) -> list[Outgoing]:
        cfg = await self._settings.get()
        early, turn, escalated = await self._receive(inc, cfg)
        if turn is None:
            if escalated is not None:
                await self._fire(*escalated)
            elif early:
                await self._fire(_lead_of(early), None)
            return early
        lock = self._locks.setdefault(turn.lead_id, asyncio.Lock())
        async with lock:
            result = await self._run_agent(turn, cfg)
            outgoing, escalation = await self._persist(turn, result, cfg)
        # Квалификатор — только для потенциальных клиентов (у клиента стадия customer).
        await self._fire(
            turn.lead_id if turn.mode == "prospect" else None, escalation, turn.lead_id
        )
        return early + outgoing

    async def start(self, inc: Incoming) -> list[Outgoing]:
        """/start: приветствие; до согласия — ещё и текст согласия с кнопкой."""
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead, conversation, _ = await self._ensure_lead(session, inc)
            if consent_required(
                lead.consent_given_at, lead.consent_version, cfg.texts.consent_version
            ):
                return await _consent_prompt(session, conversation, lead, cfg, is_new=True)
            text = cfg.texts.greeting.get(_lang(lead), company=cfg.company.name)
            await repo.add_message(session, conversation_id=conversation.id, role="bot", text=text)
        return [Outgoing(text)]

    async def help(self, tg_user_id: int) -> list[Outgoing]:
        cfg = await self._settings.get()
        language = await self._language(tg_user_id)
        return [Outgoing(cfg.texts.help.get(language, company=cfg.company.name))]

    async def unsupported(self, tg_user_id: int) -> list[Outgoing]:
        """Стикер, опрос и т. п.: состояние не меняется, просим написать текстом."""
        cfg = await self._settings.get()
        return [Outgoing(cfg.texts.unsupported_message.get(await self._language(tg_user_id)))]

    async def _language(self, tg_user_id: int) -> Language:
        async with self._sessions() as session:
            lead, _ = await _current_lead(session, tg_user_id)
        return _lang(lead) if lead else "ru"

    async def language_prompt(self, tg_user_id: int) -> list[Outgoing]:
        cfg = await self._settings.get()
        language = await self._language(tg_user_id)
        return [Outgoing(cfg.texts.language_prompt.get(language), keyboard="language")]

    async def accept_consent(self, tg_user_id: int) -> list[Outgoing]:
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead, conversation = await _current_lead(session, tg_user_id)
            if lead is None or conversation is None:
                return []
            lead.consent_given_at = datetime.now(UTC)
            lead.consent_version = cfg.texts.consent_version
            text = cfg.texts.consent_accepted.get(_lang(lead))
            message = await repo.add_message(
                session, conversation_id=conversation.id, role="bot", text=text
            )
        return [Outgoing(text, message_id=message.id)]

    async def set_language(self, tg_user_id: int, language: Language) -> list[Outgoing]:
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead, _ = await _current_lead(session, tg_user_id)
            if lead is None:
                return [Outgoing(cfg.texts.language_set.get(language))]
            lead.language, lead.language_confirmed, lead.language_candidate = language, True, None
        return [Outgoing(cfg.texts.language_set.get(language))]

    async def erase_prompt(self, tg_user_id: int) -> list[Outgoing]:
        """/delete необратим — сначала подтверждение кнопкой."""
        cfg = await self._settings.get()
        language = await self._language(tg_user_id)
        text = cfg.texts.erase_confirm.get(language)
        return [Outgoing(text, keyboard="erase_confirm", language=language)]

    async def erase_cancelled(self, tg_user_id: int) -> list[Outgoing]:
        cfg = await self._settings.get()
        return [Outgoing(cfg.texts.erase_cancelled.get(await self._language(tg_user_id)))]

    async def erase(self, tg_user_id: int) -> list[Outgoing]:
        """Обезличивание (SPEC §6.4): тексты, эскалации, чекпоинты агента, вложения в S3."""
        cfg = await self._settings.get()
        keys: list[str] = []
        closed: list[int] = []
        async with self._sessions() as session, session.begin():
            lead, _ = await _current_lead(session, tg_user_id)
            language = _lang(lead) if lead else "ru"
            lead_id = lead.id if lead else None
            if lead is not None:
                now = datetime.now(UTC)
                keys = await repo.attachment_keys(session, lead.id)
                closed = await repo.close_escalations(session, lead.id, now)
                count = await repo.erase_lead(session, lead, now)
                logger.info("lead_erased", lead_id=lead.id, messages=count, files=len(keys))
        if lead_id is not None:
            await self._forget(lead_id, keys, closed)
        return [Outgoing(cfg.texts.erased.get(language))]

    async def _forget(self, lead_id: int, keys: list[str], escalations: list[int]) -> None:
        try:
            await self._agent.forget(lead_id)
            if keys and self._erase_attachments is not None:
                await self._erase_attachments(keys)
        except Exception:
            logger.exception("lead_erase_cleanup_failed", lead_id=lead_id)
        for escalation_id in escalations:
            await self._fire(None, escalation_id, escalated_lead=lead_id)

    async def _receive(
        self, inc: Incoming, cfg: AppSettings
    ) -> tuple[list[Outgoing], _Turn | None, tuple[int, int] | None]:
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
            _update_language(lead, inc.text)
            if consent_required(
                lead.consent_given_at, lead.consent_version, cfg.texts.consent_version
            ):
                return await _consent_prompt(session, conversation, lead, cfg, is_new), None, None
            if lead.owner_mode == OwnerMode.PAUSED:
                waiting = await while_waiting(
                    session,
                    conversation,
                    lead,
                    text=inc.text,
                    human_requested=inc.human_requested,
                    language=_lang(lead),
                    cfg=cfg,
                    now=now,
                )
                out = (
                    [Outgoing(waiting.text, message_id=waiting.message_id, lead_id=lead.id)]
                    if waiting.text
                    else []
                )
                return out, None, _escalated(lead.id, waiting.escalation_id)
            if inc.attachments and not inc.text.strip():
                text = cfg.texts.attachment_received.get(_lang(lead))
                message = await repo.add_message(
                    session, conversation_id=conversation.id, role="bot", text=text
                )
                hits = evaluate(TriggerSignals(attachment_received=True), cfg.escalation.triggers())
                applied = await escalation.apply(session, lead, hits, cfg, now)
                out = [Outgoing(text, message_id=message.id, lead_id=lead.id)]
                return out, None, _escalated(lead.id, applied.escalation_id if applied else None)
            turn = _Turn(
                lead.id,
                _lang(lead),
                lead.stage,
                lead.owner_mode,
                inc.text,
                inc.human_requested,
                bool(inc.attachments),
                await _verified_client(session, inc.tg_user_id),
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

    async def _run_agent(self, turn: _Turn, cfg: AppSettings) -> DialogResult | None:
        token = issue(
            self._agent_key,
            lead_id=turn.lead_id,
            mode=turn.mode,
            language=turn.language,
            client_id=turn.client_id,
        )
        try:
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
        self, turn: _Turn, result: DialogResult | None, cfg: AppSettings
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
                return [Outgoing(text)], None
            _apply_counters(lead, result)
            if result.action == Action.FALLBACK:
                await register_gap(
                    session,
                    question=turn.text,
                    language=turn.language,
                    best_score=result.best_score,
                    lead_id=lead.id,
                )
            now = datetime.now(UTC)
            replies = [result.reply] if result.reply else []
            hits = evaluate(_turn_signals(turn, result, lead), cfg.escalation.triggers())
            applied = await escalation.apply(
                session, lead, hits, cfg, now, reason_text=f"dialog: {result.reason}"
            )
            notice = applied.plan.lead_text if applied else None
            if notice is not None and result.action != Action.HANDOFF:
                notice_text = getattr(cfg.texts, notice).get(turn.language)
                replies.append(notice_text)
            outgoing: list[Outgoing] = []
            for index, text in enumerate(replies):
                message = await repo.add_message(
                    session,
                    conversation_id=conversation.id,
                    role="bot",
                    text=text,
                    meta=_meta(result) if index == 0 else {"notice": notice},
                )
                document = result.document if index == 0 else None
                outgoing.append(
                    Outgoing(text, message_id=message.id, document=document, language=turn.language)
                )
            if replies:
                lead.last_bot_msg_at = now
        return outgoing, applied.escalation_id if applied else None

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


def _apply_counters(lead: Lead, result: DialogResult) -> None:
    if result.action == Action.FALLBACK:
        lead.consecutive_fallbacks += 1
    elif result.action == Action.ANSWER:
        lead.consecutive_fallbacks = 0


def _turn_signals(turn: _Turn, result: DialogResult, lead: Lead) -> TriggerSignals:
    """Триггеры, которые код видит сразу в ходе; остальные — квалификатор."""
    handoff = result.action == Action.HANDOFF
    return TriggerSignals(
        human_requested=handoff and result.reason == "human_requested",
        stop_word_hit=handoff and result.reason == "stop_word",
        callback_requested=result.callback_requested,
        consecutive_fallbacks=lead.consecutive_fallbacks if result.action == Action.FALLBACK else 0,
        attachment_received=turn.attachment,
        customer_mode=turn.mode == "customer",
        document_not_found=result.reason == "document_not_found",
        intent="service" if result.service_request else None,
    )


async def _verified_client(session: AsyncSession, tg_user_id: int) -> int | None:
    """Активный клиент, к которому менеджер подтвердил привязку этого Telegram (SPEC §5.2).

    Деактивированный клиент документов больше не получает: бот говорит с ним как с лидом.
    """
    identity = await repo.get_identity(session, tg_user_id)
    if identity is None or identity.client_id is None or identity.verified_at is None:
        return None
    client = await session.get(Client, identity.client_id)
    return client.id if client is not None and client.is_active else None


def _escalated(lead_id: int, escalation_id: int | None) -> tuple[int, int] | None:
    return (lead_id, escalation_id) if escalation_id is not None else None


def _lead_of(outgoing: list[Outgoing]) -> int | None:
    return next((o.lead_id for o in outgoing if o.lead_id is not None), None)


async def _consent_prompt(
    session: AsyncSession, conversation: Conversation, lead: Lead, cfg: AppSettings, is_new: bool
) -> list[Outgoing]:
    language = _lang(lead)
    texts = cfg.texts
    out: list[Outgoing] = []
    if is_new:
        out.append(Outgoing(texts.greeting.get(language, company=cfg.company.name)))
        out.append(Outgoing(texts.consent.get(language), keyboard="consent", language=language))
    else:
        out.append(
            Outgoing(texts.consent_required.get(language), keyboard="consent", language=language)
        )
    for item in out:
        await repo.add_message(session, conversation_id=conversation.id, role="bot", text=item.text)
    return out


async def _current_lead(
    session: AsyncSession, tg_user_id: int
) -> tuple[Lead | None, Conversation | None]:
    identity = await repo.get_identity(session, tg_user_id)
    if identity is None or identity.lead_id is None:
        return None, None
    lead = await repo.get_lead(session, identity.lead_id, for_update=True)
    conversation = await repo.open_conversation(session, identity.lead_id) if lead else None
    return lead, conversation


def _update_language(lead: Lead, text: str) -> None:
    if not text.strip():
        return
    detected = detect_language(text, default=_lang(lead))
    language, confirmed, new_candidate = next_language(
        _lang(lead), lead.language_confirmed, _as_language(lead.language_candidate), detected
    )
    lead.language, lead.language_confirmed, lead.language_candidate = (
        language,
        confirmed,
        new_candidate,
    )


_LANGUAGES: dict[str, Language] = {"ru": "ru", "uz": "uz", "en": "en"}


def _as_language(value: str | None) -> Language | None:
    return _LANGUAGES.get(value or "")


def _lang(lead: Lead) -> Language:
    return _as_language(lead.language) or "ru"


def _meta(result: DialogResult) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "action": result.action.value,
        "reason": result.reason,
        "kb_hits": result.kb_hits,
        "best_score": result.best_score,
        "trace_id": result.trace_id,
        "prompt_version": result.prompt_version,
        "mode": result.mode,
    }
    if result.llm:
        meta.update(result.llm)
    return meta
