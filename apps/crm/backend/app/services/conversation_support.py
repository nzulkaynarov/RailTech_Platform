"""Помощники диалогового потока без собственного состояния (SPEC §3.3, §6.4)."""

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dialog.state import DialogResult
from app.domain.dialog_policy import Action, is_smalltalk
from app.domain.language import Language, detect_language, next_language
from app.domain.stages import OwnerMode
from app.domain.triggers import TriggerSignals, evaluate
from app.models.clients import Client
from app.models.leads import Conversation, Lead, Message
from app.repositories import leads as repo
from app.schemas.settings import AppSettings
from app.services import escalation
from app.services.conversation_types import ActivityHook, Outgoing, Turn

logger = structlog.get_logger(__name__)


def apply_counters(lead: Lead, result: DialogResult) -> None:
    if result.action == Action.FALLBACK:
        lead.consecutive_fallbacks += 1
    elif result.action == Action.ANSWER:
        lead.consecutive_fallbacks = 0


def turn_signals(turn: Turn, result: DialogResult, lead: Lead) -> TriggerSignals:
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


async def verified_client(session: AsyncSession, tg_user_id: int) -> int | None:
    """Активный клиент, к которому менеджер подтвердил привязку этого Telegram (SPEC §5.2).

    Деактивированный клиент документов больше не получает: бот говорит с ним как с лидом.
    """
    identity = await repo.get_identity(session, tg_user_id)
    if identity is None or identity.client_id is None or identity.verified_at is None:
        return None
    client = await session.get(Client, identity.client_id)
    return client.id if client is not None and client.is_active else None


def escalated(lead_id: int, escalation_id: int | None) -> tuple[int, int] | None:
    return (lead_id, escalation_id) if escalation_id is not None else None


def lead_of(outgoing: list[Outgoing]) -> int | None:
    return next((o.lead_id for o in outgoing if o.lead_id is not None), None)


def owner_notice_target(early: list[Outgoing], turn: Turn | None) -> int | None:
    """Лид, о сообщении которого, возможно, надо написать менеджеру: ход в режиме «человек»
    или ответ без модели (вложение и т. п.); окончательно решает задача по данным лида."""
    if turn is None:
        return lead_of(early)
    return turn.lead_id if turn.owner_mode == OwnerMode.HUMAN else None


async def notify_owner(hook: ActivityHook | None, early: list[Outgoing], turn: Turn | None) -> None:
    """Хук «сообщение лида» после коммита (Q-010); ошибка очереди не ломает ответ клиенту."""
    lead_id = owner_notice_target(early, turn)
    if hook is None or lead_id is None:
        return
    try:
        await hook(lead_id)
    except Exception:
        logger.exception("conversation_hook_failed", lead_id=lead_id)


async def consent_prompt(
    session: AsyncSession, conversation: Conversation, lead: Lead, cfg: AppSettings, is_new: bool
) -> list[Outgoing]:
    """Первый контакт — выбор языка (Q-022), согласие — после него на выбранном языке."""
    language = lang_of(lead)
    texts = cfg.texts
    out: list[Outgoing] = []
    if is_new:
        first = texts.language_first
        picker = "\n".join((first.uz, first.ru, first.en))
        out.append(Outgoing(picker, keyboard="language", language=language))
    else:
        out.append(
            Outgoing(texts.consent_required.get(language), keyboard="consent", language=language)
        )
    for item in out:
        await repo.add_message(session, conversation_id=conversation.id, role="bot", text=item.text)
    return out


async def consent_offer(
    session: AsyncSession, conversation: Conversation, lead: Lead, cfg: AppSettings
) -> list[Outgoing]:
    """Язык выбран кнопкой, согласия ещё нет: приветствие и согласие на этом языке."""
    language = lang_of(lead)
    texts = cfg.texts
    out = [
        Outgoing(texts.greeting.get(language, company=cfg.company.name), language=language),
        Outgoing(texts.consent.get(language), keyboard="consent", language=language),
    ]
    for item in out:
        await repo.add_message(session, conversation_id=conversation.id, role="bot", text=item.text)
    return out


async def current_lead(
    session: AsyncSession, tg_user_id: int
) -> tuple[Lead | None, Conversation | None]:
    identity = await repo.get_identity(session, tg_user_id)
    if identity is None or identity.lead_id is None:
        return None, None
    lead = await repo.get_lead(session, identity.lead_id, for_update=True)
    conversation = await repo.open_conversation(session, identity.lead_id) if lead else None
    return lead, conversation


def update_language(lead: Lead, text: str) -> None:
    if not text.strip():
        return
    detected = detect_language(text, default=lang_of(lead))
    language, confirmed, new_candidate = next_language(
        lang_of(lead), lead.language_confirmed, as_language(lead.language_candidate), detected
    )
    lead.language, lead.language_confirmed, lead.language_candidate = (
        language,
        confirmed,
        new_candidate,
    )


_LANGUAGES: dict[str, Language] = {"ru": "ru", "uz": "uz", "en": "en"}


def as_language(value: str | None) -> Language | None:
    return _LANGUAGES.get(value or "")


def lang_of(lead: Lead) -> Language:
    return as_language(lead.language) or "ru"


def turn_meta(result: DialogResult) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "action": result.action.value,
        "reason": result.reason,
        "kb_hits": result.kb_hits,
        "best_score": result.best_score,
        "trace_id": result.trace_id,
        "prompt_version": result.prompt_version,
        "mode": result.mode,
        "price_quoted": result.price_quoted,
    }
    if result.llm:
        meta.update(result.llm)
    return meta


async def pending_question(session: AsyncSession, conversation_id: int) -> str | None:
    """Последнее сообщение лида до согласия, если это вопрос, а не команда."""
    text = await session.scalar(
        select(Message.text)
        .where(Message.conversation_id == conversation_id, Message.role == "lead")
        .order_by(Message.id.desc())
        .limit(1)
    )
    # Приветствие и «спасибо» — не вопрос: иначе «Отвечаю на ваш вопрос» на «Hi».
    if not text or not text.strip() or text.strip().startswith("/") or is_smalltalk(text):
        return None
    return text.strip()


async def report_failure(
    session: AsyncSession, lead: Lead, cfg: AppSettings, signals: TriggerSignals
) -> int | None:
    """Сбой, о котором лиду сказали «коллеги увидят»: info-эскалация (бот не замолкает)."""
    hits = evaluate(signals, cfg.escalation.triggers())
    applied = await escalation.apply(session, lead, hits, cfg, datetime.now(UTC))
    return applied.escalation_id if applied else None
