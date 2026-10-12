"""«Проверить бота»: админ пишет боту из CRM без Telegram (аудит 2026-10-12 §3 п. 10).

Ход идёт через тот же `ConversationService.handle_message`, что и в Telegram (агент, MCP,
триггеры, эскалация), но у сервиса песочницы нет хуков: квалификатор не ставится в очередь,
пост в канал и уведомления менеджеров не уходят. Лид песочницы — `source='sandbox'`, согласие
дано автоматически, язык выбирает админ. Вызовы моделей учитываются в «Расходах» как `test`.
Передача менеджеру не остаётся в CRM: она показывается в ответе и сразу снимается.
"""

from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.language import Language
from app.domain.sandbox import SANDBOX_SOURCE, chunk_ids, decision_of, sandbox_identity
from app.domain.stages import OwnerMode
from app.integrations.llm_usage import kind_scope
from app.models.kb import KbChunk, KbDocument
from app.models.leads import Lead, Message
from app.models.qualification import Escalation
from app.repositories import leads as repo
from app.schemas.sandbox import SandboxReply, SandboxTurnOut, SandboxWhy
from app.schemas.settings import AppSettings
from app.services.conversation import ConversationService, Incoming, Outgoing
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)


class ConversationFactory(Protocol):
    """Ленивый диалоговый контур (`app/bot/setup.py SandboxConversation`)."""

    def __call__(self) -> Awaitable[ConversationService]: ...

    async def aclose(self) -> None: ...


OPEN = ("open", "snoozed")


class SandboxService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        conversation: ConversationFactory,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._conversation = conversation

    async def message(self, user_id: int, text: str, language: Language) -> SandboxTurnOut:
        cfg = await self._settings.get()
        tg_user_id = sandbox_identity(user_id)
        lead_id = await self._prepare(tg_user_id, language, cfg)
        conversation = await self._conversation()
        with kind_scope("test"):
            out = await conversation.handle_message(
                Incoming(
                    tg_user_id=tg_user_id, chat_id=tg_user_id, text=text, language_code=language
                )
            )
        async with self._sessions() as session, session.begin():
            metas = await _metas(session, out)
            triggers, priority = await _withdraw_handoff(session, lead_id)
            documents = await _documents(session, chunk_ids(metas))
        first = metas[0] if metas else {}
        why = SandboxWhy(
            decision=decision_of(metas, bool(triggers)),
            reason=first.get("reason") or None,
            best_score=first.get("best_score"),
            documents=documents,
            triggers=triggers,
            priority=priority,
        )
        logger.info("sandbox_turn", lead_id=lead_id, decision=why.decision)
        return SandboxTurnOut(replies=[_reply(o, cfg, language) for o in out], why=why)

    async def aclose(self) -> None:
        await self._conversation.aclose()

    async def reset(self, user_id: int) -> None:
        """«Начать заново»: лид песочницы удаляется целиком (переписка, стадии, передачи)."""
        async with self._sessions() as session, session.begin():
            identity = await repo.get_identity(session, sandbox_identity(user_id))
            if identity is None or identity.lead_id is None:
                return
            await session.execute(
                delete(Lead).where(Lead.id == identity.lead_id, Lead.source == SANDBOX_SOURCE)
            )

    async def _prepare(self, tg_user_id: int, language: Language, cfg: AppSettings) -> int:
        """Лид песочницы: создать при первом сообщении, согласие и язык — как выбрал админ."""
        async with self._sessions() as session, session.begin():
            identity = await repo.get_identity(session, tg_user_id)
            lead = (
                await repo.get_lead(session, identity.lead_id, for_update=True)
                if identity and identity.lead_id
                else None
            )
            if lead is None or lead.erased_at is not None or lead.source != SANDBOX_SOURCE:
                lead, _, _ = await repo.create_lead_with_identity(
                    session,
                    tg_user_id=tg_user_id,
                    username=None,
                    first_name=SANDBOX_SOURCE,
                    chat_id=tg_user_id,
                    language=language,
                    identity=identity,
                )
                lead.source = SANDBOX_SOURCE
            lead.consent_given_at = lead.consent_given_at or datetime.now(UTC)
            lead.consent_version = cfg.texts.consent_version
            lead.language, lead.language_confirmed, lead.language_candidate = language, True, None
            await session.flush()
            return lead.id


def _reply(out: Outgoing, cfg: AppSettings, language: Language) -> SandboxReply:
    texts = cfg.texts
    labels: dict[str, list[str]] = {
        "handoff_offer": [
            texts.handoff_offer_yes.get(language),
            texts.handoff_offer_no.get(language),
        ],
        "consent": [texts.consent_button.get(language), texts.consent_decline_button.get(language)],
        "erase_confirm": [texts.erase_button.get(language), texts.cancel_button.get(language)],
        "language": ["Русский", "Oʻzbekcha", "English"],
    }
    buttons = labels.get(out.keyboard, []) if out.keyboard else []
    if out.document:
        buttons = [*buttons, str(out.document.get("title") or out.document.get("name") or "")]
    return SandboxReply(text=out.text, buttons=[b for b in buttons if b])


async def _metas(session: AsyncSession, out: list[Outgoing]) -> list[dict[str, Any]]:
    ids = [o.message_id for o in out if o.message_id is not None]
    if not ids:
        return []
    rows = await session.execute(select(Message.id, Message.meta).where(Message.id.in_(ids)))
    by_id = {row_id: meta or {} for row_id, meta in rows}
    return [by_id[i] for i in ids if i in by_id]


async def _withdraw_handoff(session: AsyncSession, lead_id: int) -> tuple[list[str], str | None]:
    """Передача из песочницы: причины — в ответ админу; в CRM её нет, лид снова у бота."""
    escalation = await session.scalar(
        select(Escalation).where(Escalation.lead_id == lead_id, Escalation.status.in_(OPEN))
    )
    if escalation is None:
        return [], None
    triggers, priority = list(escalation.reason_codes), escalation.priority
    await session.execute(delete(Escalation).where(Escalation.lead_id == lead_id))
    lead = await repo.get_lead(session, lead_id, for_update=True)
    if lead is not None:
        lead.owner_mode = OwnerMode.BOT
    return triggers, priority


async def _documents(session: AsyncSession, chunks: list[int]) -> list[str]:
    if not chunks:
        return []
    rows = await session.execute(
        select(KbDocument.title)
        .join(KbChunk, KbChunk.document_id == KbDocument.id)
        .where(KbChunk.id.in_(chunks))
        .distinct()
    )
    return [title for (title,) in rows]
