"""/delete (SPEC §6.4, аудит P-10): подтверждение, обезличивание, чистка чекпоинтов и вложений."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.language import Language
from app.domain.triggers import TriggerSignals
from app.repositories import leads as repo
from app.services.conversation_support import current_lead, lang_of, report_failure
from app.services.conversation_types import AttachmentsEraser, Outgoing
from app.services.settings import SettingsService

if TYPE_CHECKING:
    from app.agents.dialog.graph import DialogAgent

logger = structlog.get_logger(__name__)


class ErasureMixin:
    """Часть `ConversationService`: удаление переписки по запросу лида."""

    _sessions: async_sessionmaker[AsyncSession]
    _settings: SettingsService
    _agent: "DialogAgent"
    _erase_attachments: AttachmentsEraser | None

    async def language_of(self, tg_user_id: int) -> Language:
        raise NotImplementedError

    async def _fire(
        self, lead_id: int | None, escalation_id: int | None, escalated_lead: int | None = None
    ) -> None:
        raise NotImplementedError

    async def erase_prompt(self, tg_user_id: int) -> list[Outgoing]:
        """/delete необратим — сначала подтверждение кнопкой."""
        cfg = await self._settings.get()
        language = await self.language_of(tg_user_id)
        text = cfg.texts.erase_confirm.get(language)
        return [Outgoing(text, keyboard="erase_confirm", language=language)]

    async def erase_cancelled(self, tg_user_id: int) -> list[Outgoing]:
        cfg = await self._settings.get()
        return [Outgoing(cfg.texts.erase_cancelled.get(await self.language_of(tg_user_id)))]

    async def erase(self, tg_user_id: int) -> list[Outgoing]:
        """Обезличивание (SPEC §6.4): тексты, эскалации, чекпоинты агента, вложения в S3."""
        cfg = await self._settings.get()
        keys: list[str] = []
        closed: list[int] = []
        async with self._sessions() as session, session.begin():
            lead, _ = await current_lead(session, tg_user_id)
            language = lang_of(lead) if lead else "ru"
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


class DeliveryFailureMixin:
    """Часть `ConversationService`: файл не доставлен клиенту → info-эскалация для команды."""

    _sessions: async_sessionmaker[AsyncSession]
    _settings: SettingsService

    async def _fire(
        self, lead_id: int | None, escalation_id: int | None, escalated_lead: int | None = None
    ) -> None:
        raise NotImplementedError

    async def report_delivery_failure(self, lead_id: int) -> None:
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead = await repo.get_lead(session, lead_id, for_update=True)
            signals = TriggerSignals(delivery_failed=True)
            escalation_id = await report_failure(session, lead, cfg, signals) if lead else None
        await self._fire(None, escalation_id, lead_id)
