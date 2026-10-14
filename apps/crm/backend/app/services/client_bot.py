"""Интерфейс клиентского бота по статусу (Q-011, Q-020): меню, документы, запросы, номер.

Клиент определяется только подтверждённой привязкой Telegram (`verified_client`):
`client_id` никогда не берётся из текста или кнопки пользователя (SPEC §1.5, §11).
Документы — те же правила, что у docs-mcp: только видимые клиенту, доступ в журнал.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.bot_menu import MenuVariant, menu_variant, should_ask_phone
from app.domain.consent import consent_required
from app.domain.handoff_gate import needs_phone_first
from app.domain.language import detect_language, mismatch_offer
from app.domain.triggers import TriggerSignals, evaluate
from app.models.clients import Document, ServiceRequest
from app.models.qualification import Escalation
from app.repositories import documents as docs_repo
from app.repositories import leads as repo
from app.schemas.settings import Language
from app.services import escalation
from app.services.conversation_support import current_lead, lang_of, verified_client
from app.services.conversation_types import EscalationHook, Outgoing
from app.services.documents import LINK_TTL_S
from app.services.lead_merge import merge_by_phone
from app.services.lead_parts import ACTIVE_ESCALATION
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

Presign = Callable[[str, int], Awaitable[str]]
DOCS_LIMIT = 10
PHONE_ASKED = "phone_asked_at"
# Лид просил менеджера без номера: передадим, как только поделится номером (2026-10-12).
HANDOFF_PENDING = "handoff_pending_phone_at"
LANGUAGE_MISMATCH = "language_mismatch_streak"
LANGUAGE_OFFERED = "language_offered_at"


@dataclass(frozen=True, slots=True)
class ChatStatus:
    variant: MenuVariant
    language: Language
    lead_id: int | None
    client_id: int | None
    ask_phone: bool


class ClientBotService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        presign: Presign | None = None,
        on_escalation: EscalationHook | None = None,
        on_card_changed: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._presign = presign
        self._on_escalation = on_escalation
        # Перерисовать карточку передачи в канале (номер появился после передачи по решению кода).
        self._on_card_changed = on_card_changed

    async def status(self, tg_user_id: int) -> ChatStatus:
        cfg = await self._settings.get()
        async with self._sessions() as session:
            identity = await repo.get_identity(session, tg_user_id)
            lead = (
                await repo.get_lead(session, identity.lead_id)
                if identity and identity.lead_id
                else None
            )
            client_id = await verified_client(session, tg_user_id)
        live = lead if lead is not None and lead.erased_at is None else None
        ask = should_ask_phone(
            enabled=cfg.bot.ask_phone,
            already_asked=bool(live and (live.qualification or {}).get(PHONE_ASKED)),
            has_phone=bool(identity and identity.phone_e164),
            is_client=client_id is not None,
            stage=live.stage if live else None,
            owner_mode=live.owner_mode if live else None,
        )
        return ChatStatus(
            variant=menu_variant(
                is_client=client_id is not None, owner_mode=live.owner_mode if live else None
            ),
            language=lang_of(live) if live else "ru",
            lead_id=live.id if live else None,
            client_id=client_id,
            ask_phone=ask,
        )

    async def mark_phone_asked(self, tg_user_id: int) -> None:
        """Флаг «уже спрашивали» — в `leads.qualification`: квалификатор его не затирает."""
        async with self._sessions() as session, session.begin():
            lead, _ = await current_lead(session, tg_user_id)
            if lead is not None:
                stored = dict(lead.qualification or {})
                stored[PHONE_ASKED] = datetime.now(UTC).isoformat()
                lead.qualification = stored

    async def hold_handoff_for_phone(self, tg_user_id: int) -> Language | None:
        """Просьба лида позвать менеджера: нужен ли сначала номер (`needs_phone_first`).

        Да — помечает ожидание в `leads.qualification` (и «номер уже спрашивали», чтобы
        middleware не спросил второй раз тем же ходом) и возвращает язык ответа; None —
        передавать как обычно.
        """
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            identity = await repo.get_identity(session, tg_user_id)
            lead, _ = await current_lead(session, tg_user_id)
            live = lead if lead is not None and lead.erased_at is None else None
            client_id = await verified_client(session, tg_user_id)
            hold = live is not None and needs_phone_first(
                required=cfg.escalation.require_phone_for_human_request,
                source="lead",
                has_phone=bool(identity and identity.phone_e164),
                is_client=client_id is not None,
                owner_mode=live.owner_mode,
                consent_given=not consent_required(
                    live.consent_given_at, live.consent_version, cfg.texts.consent_version
                ),
            )
            if live is None or not hold:
                return None
            now = datetime.now(UTC).isoformat()
            stored = dict(live.qualification or {})
            stored[HANDOFF_PENDING] = now
            stored.setdefault(PHONE_ASKED, now)
            live.qualification = stored
            logger.info("handoff_waits_for_phone", lead_id=live.id)
            return lang_of(live)

    async def take_pending_handoff(self, tg_user_id: int) -> bool:
        """Снять пометку «ждём номер для передачи»; True — она стояла."""
        async with self._sessions() as session, session.begin():
            lead, _ = await current_lead(session, tg_user_id)
            stored = dict(lead.qualification or {}) if lead is not None else {}
            if lead is None or stored.pop(HANDOFF_PENDING, None) is None:
                return False
            lead.qualification = stored
            return True

    async def language_offer(self, tg_user_id: int, text: str) -> Language | None:
        """Язык зафиксирован, а два сообщения подряд — на другом: предложить кнопки один раз.

        Серия и флаг — в `leads.qualification` (как флаг номера): квалификатор их не затирает.
        """
        if not text.strip():
            return None
        async with self._sessions() as session, session.begin():
            lead, _ = await current_lead(session, tg_user_id)
            if lead is None or not lead.language_confirmed:
                return None
            fixed = lang_of(lead)
            detected = detect_language(text, default=fixed)
            stored = dict(lead.qualification or {})
            streak, offer = mismatch_offer(
                fixed,
                detected,
                int(stored.get(LANGUAGE_MISMATCH, 0)),
                bool(stored.get(LANGUAGE_OFFERED)),
            )
            if streak != stored.get(LANGUAGE_MISMATCH, 0) or offer:
                stored[LANGUAGE_MISMATCH] = streak
                if offer:
                    stored[LANGUAGE_OFFERED] = datetime.now(UTC).isoformat()
                lead.qualification = stored
        return detected if offer else None

    async def save_phone(self, tg_user_id: int, phone_e164: str) -> None:
        """Номер — в идентичность; если у лида уже открыта передача, её карточка в канале
        перерисовывается, чтобы менеджер увидел номер, а не «Номер: не указан».

        Такой номер уже есть у лида с сайта/звонка/почты — карточки склеиваются в одну
        (`services/lead_merge.py`, M3-CRM-05): история и Telegram остаются, источник — первый.
        """
        escalations: list[int] = []
        async with self._sessions() as session, session.begin():
            identity = await repo.get_identity(session, tg_user_id)
            if identity is not None:
                identity.phone_e164 = phone_e164
                merged = await merge_by_phone(session, identity, phone_e164)
                lead_id = merged.survivor_id if merged else identity.lead_id
                if merged is not None:
                    escalations = list(merged.escalation_ids)
                elif lead_id is not None:
                    escalations = await self._latest_active_escalation(session, lead_id)
        logger.info("lead_phone_saved", tg_user_id=tg_user_id)
        for escalation_id in escalations:
            await self._refresh_card(escalation_id)

    @staticmethod
    async def _latest_active_escalation(session: AsyncSession, lead_id: int) -> list[int]:
        escalation_id = await session.scalar(
            select(Escalation.id)
            .where(Escalation.lead_id == lead_id, Escalation.status.in_(ACTIVE_ESCALATION))
            .order_by(Escalation.id.desc())
            .limit(1)
        )
        return [escalation_id] if escalation_id is not None else []

    async def _refresh_card(self, escalation_id: int) -> None:
        if self._on_card_changed is None:
            return
        try:
            await self._on_card_changed(escalation_id)
        except Exception:  # noqa: BLE001 — номер сохранён; карточка обновится со следующим событием
            logger.warning("phone_card_refresh_failed", escalation_id=escalation_id)

    async def documents(self, tg_user_id: int) -> list[tuple[int, str]] | None:
        """До 10 документов клиента, новые первыми; None — собеседник не клиент."""
        async with self._sessions() as session:
            client_id = await verified_client(session, tg_user_id)
            if client_id is None:
                return None
            stmt = (
                docs_repo.visible_for_client(client_id)
                .order_by(Document.doc_date.desc().nulls_last(), Document.id.desc())
                .limit(DOCS_LIMIT)
            )
            rows = (await session.scalars(stmt)).all()
        return [(row.id, _label(row)) for row in rows]

    async def document(self, tg_user_id: int, document_id: int) -> Outgoing | None:
        """Ссылка на файл для отправки ботом (как `deliver_document`); чужой документ — None."""
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            client_id = await verified_client(session, tg_user_id)
            lead, _ = await current_lead(session, tg_user_id)
            if client_id is None or lead is None or self._presign is None:
                return None
            row = await docs_repo.get_for_client(session, client_id, document_id)
            if row is None or row.storage_key is None:
                return None
            await docs_repo.log_access(session, row.id, "bot", lead.id, tg_user_id)
            key, title, filename, language = row.storage_key, row.title, row.filename, lang_of(lead)
        url = await self._presign(key, LINK_TTL_S)
        link: dict[str, Any] = {"document_id": document_id, "filename": filename, "url": url}
        text = cfg.texts.document_sent.get(language, title=title)
        return Outgoing(text, language=language, lead_id=lead.id, document=link)

    async def create_request(self, tg_user_id: int, summary: str) -> str | None:
        """Сервисный запрос клиента (Q-017) + info-эскалация команде; None — не клиент."""
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            client_id = await verified_client(session, tg_user_id)
            lead, conversation = await current_lead(session, tg_user_id)
            if client_id is None or lead is None:
                return None
            row = ServiceRequest(client_id=client_id, lead_id=lead.id, summary=summary[:2000])
            session.add(row)
            await session.flush()
            text = cfg.texts.request_created.get(lang_of(lead), number=str(row.id))
            if conversation is not None:
                await repo.add_message(
                    session, conversation_id=conversation.id, role="lead", text=summary
                )
                await repo.add_message(
                    session, conversation_id=conversation.id, role="bot", text=text
                )
            signals = TriggerSignals(customer_mode=True, intent="service")
            hits = evaluate(signals, cfg.escalation.triggers())
            applied = await escalation.apply(session, lead, hits, cfg, datetime.now(UTC))
            lead_id = lead.id
        if applied is not None and self._on_escalation is not None:
            try:
                await self._on_escalation(lead_id, applied.escalation_id)
            except Exception:
                logger.exception("service_request_notify_failed", lead_id=lead_id)
        return text

    async def request_status(self, tg_user_id: int) -> str | None:
        """Открытый запрос клиента словами; None — не клиент."""
        cfg = await self._settings.get()
        async with self._sessions() as session:
            client_id = await verified_client(session, tg_user_id)
            lead, _ = await current_lead(session, tg_user_id)
            if client_id is None:
                return None
            row = await session.scalar(
                select(ServiceRequest)
                .where(ServiceRequest.client_id == client_id, ServiceRequest.status == "open")
                .order_by(ServiceRequest.id.desc())
                .limit(1)
            )
        language = lang_of(lead) if lead else "ru"
        if row is None:
            return cfg.texts.request_status_none.get(language)
        return cfg.texts.request_status_open.get(
            language,
            number=str(row.id),
            date=f"{row.created_at:%d.%m.%Y}",
            summary=row.summary[:300],
        )


def _label(row: Document) -> str:
    when = f" · {row.doc_date:%d.%m.%Y}" if row.doc_date else ""
    number = f" №{row.number}" if row.number else ""
    return f"{row.title}{number}{when}"[:64]
