"""Сервис обработки входящих событий ERP (M3-CRM-04, CONTRACTS §3, ADR-0022)."""

import hashlib
import hmac
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.deals import DealStage, plan_erp_outcome
from app.domain.errors import AuthError, ConflictError, Reason
from app.integrations.erp import resolve_erp
from app.models.auth import User
from app.models.clients import Client, Document
from app.models.deals import Deal
from app.models.integrations import ErpIncomingEvent
from app.models.leads import Lead, LeadNote, TelegramIdentity
from app.repositories import events
from app.schemas.erp_events import ErpEventEnvelope
from app.security.secrets_store import SecretsStore
from app.services.erp_bot_messages import (
    BotMessage,
    client_message,
    feed_note,
    pick_language,
    staff_alert,
)
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

DOC_KIND_MAP: dict[str, str] = {
    "quote": "proposal",
    "contract": "contract",
    "invoice": "invoice",
    "act": "act",
    "waybill": "other",
    "receipt": "other",
    "other": "other",
}


def _deal_amount(amount: str | None) -> Decimal | None:
    """Сумма сделки из события: None — КП клиенту ещё не отправлялось (контракт событий, FIX-29)."""
    return Decimal(amount) if amount is not None else None


def verify_signature(secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    """Проверка HMAC-SHA256 подписи вебхука: X-Signature: sha256=<hex>."""
    if not secret or not signature_header:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    given_hex = signature_header[len(prefix) :].strip()
    expected_hex = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(given_hex, expected_hex)


class ErpEventsService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings_service: SettingsService,
        secrets_store: SecretsStore,
        config: Settings,
        bot_provider: Callable[[], Awaitable[Bot | None]],
        enqueue_task: Callable[[str], Awaitable[int]] | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings_service = settings_service
        self._secrets_store = secrets_store
        self._config = config
        self._bot_provider = bot_provider
        self._enqueue_task = enqueue_task

    async def get_webhook_secret(self) -> str:
        """Получение секрета подписи вебхуков ERP из хранилища секретов или env."""
        resolution = await resolve_erp(self._secrets_store, self._config, self._settings_service)
        return resolution.webhook_secret

    async def receive_event(
        self,
        event_id: str,
        event_type: str,
        signature: str | None,
        raw_body: bytes,
        envelope: ErpEventEnvelope,
    ) -> tuple[bool, str]:
        """Приём вебхука: проверка подписи, идемпотентная фиксация и постановка в очередь.

        Возвращает: (is_duplicate, status_str).
        Ошибки: 409 (секрет не настроен), 401 (неверная подпись).
        """
        secret = await self.get_webhook_secret()
        if not secret:
            logger.warning("erp_webhook_secret_missing", event_id=event_id)
            raise ConflictError(
                "erp webhook secret is not configured", reason=Reason.ERP_NOT_CONFIGURED
            )

        if not verify_signature(secret, raw_body, signature):
            logger.warning("erp_webhook_invalid_signature", event_id=event_id)
            raise AuthError("invalid webhook signature")

        async with self._sessions() as session, session.begin():
            existing = await session.get(ErpIncomingEvent, event_id)
            if existing is not None:
                logger.info("erp_webhook_duplicate", event_id=event_id, event_type=event_type)
                return True, "duplicate"

            incoming = ErpIncomingEvent(
                event_id=event_id,
                event_type=event_type,
                erp_company_id=envelope.erp_company_id,
                crm_client_id=envelope.crm_client_id,
                payload=envelope.model_dump(mode="json"),
                status="received",
            )
            session.add(incoming)

        if self._enqueue_task is not None:
            await self._enqueue_task(event_id)
            logger.info("erp_webhook_enqueued", event_id=event_id, event_type=event_type)

        return False, "enqueued"

    async def process_event(self, event_id: str) -> bool:
        """Асинхронная обработка события ERP: зеркало сделки, документы, лента и бот."""
        async with self._sessions() as session, session.begin():
            event_row = await session.get(ErpIncomingEvent, event_id, with_for_update=True)
            if event_row is None:
                logger.warning("erp_event_not_found_for_processing", event_id=event_id)
                return False

            if event_row.status == "processed":
                logger.info("erp_event_already_processed", event_id=event_id)
                return True

            envelope = ErpEventEnvelope.model_validate(event_row.payload)
            client = await session.get(Client, envelope.crm_client_id)
            if client is None:
                event_row.status = "failed"
                event_row.error = f"Client #{envelope.crm_client_id} not found"
                logger.warning(
                    "erp_event_client_not_found",
                    event_id=event_id,
                    client_id=envelope.crm_client_id,
                )
                return False

            if client.erp_company_id is None:
                client.erp_company_id = envelope.erp_company_id

            lead = await session.scalar(
                select(Lead).where(Lead.client_id == client.id).order_by(Lead.id.desc()).limit(1)
            )

            deal: Deal | None = None
            if envelope.deal is not None:
                deal = await session.scalar(
                    select(Deal)
                    .where(Deal.erp_deal_id == envelope.deal.erp_deal_id)
                    .limit(1)
                    .with_for_update()
                )
                if deal is None:
                    deal = Deal(
                        client_id=client.id,
                        lead_id=lead.id if lead else None,
                        title=envelope.deal.title,
                        amount=_deal_amount(envelope.deal.amount),
                        currency=envelope.deal.currency,
                        stage="open",
                        external_stage=envelope.deal.stage,
                        erp_deal_id=envelope.deal.erp_deal_id,
                    )
                    session.add(deal)
                    await session.flush()
                else:
                    deal.external_stage = envelope.deal.stage
                    deal.title = envelope.deal.title
                    if envelope.deal.amount is not None:
                        deal.amount = Decimal(envelope.deal.amount)
                    deal.currency = envelope.deal.currency
                    if deal.client_id is None:
                        deal.client_id = client.id

                event_row.deal_id = deal.id

            note_text = await self._dispatch_event(session, envelope, client, deal)
            cfg = await self._settings_service.get()
            deal_title = envelope.deal.title if envelope.deal else (deal.title if deal else "—")
            bot_msg = client_message(
                envelope.event,
                envelope.payload,
                deal_title=deal_title,
                texts=cfg.texts,
                language=pick_language(lead.language if lead else None),
                cabinet_url=cfg.company.cabinet_url,
            )
            if note_text is None:
                # Приёмка и замечания по строкам поставки: текст ленты — из настроек (FIX-37).
                note_text = feed_note(
                    envelope.event,
                    envelope.payload,
                    contact_name=envelope.actor.name,
                    deal_title=deal_title,
                    texts=cfg.texts,
                )
            staff_alert_text = staff_alert(
                envelope.event,
                envelope.payload,
                client_name=client.name,
                deal_title=deal_title,
                texts=cfg.texts,
            )

            if lead is not None and note_text:
                note_row = LeadNote(
                    lead_id=lead.id,
                    user_id=None,
                    text=note_text,
                    visible_to_bot=False,
                )
                session.add(note_row)
                lead.notes_count = (lead.notes_count or 0) + 1
                await events.publish(session, "lead.updated", lead_id=lead.id)

            if bot_msg:
                await self._send_to_client_telegram(session, client.id, bot_msg)

            if staff_alert_text:
                target_user_id = (
                    deal.owner_user_id
                    if deal and deal.owner_user_id
                    else client.owner_user_id
                    if client.owner_user_id
                    else lead.assigned_user_id
                    if lead and lead.assigned_user_id
                    else None
                )
                if target_user_id:
                    await self._send_to_staff(session, target_user_id, staff_alert_text)

            event_row.status = "processed"
            event_row.processed_at = datetime.now(UTC)
            event_row.error = None

        return True

    async def _dispatch_event(
        self,
        session: AsyncSession,
        env: ErpEventEnvelope,
        client: Client,
        deal: Deal | None,
    ) -> str | None:
        """Меняет зеркало сделки и возвращает текст заметки в ленту лида (если она нужна).

        Тексты клиенту и сотруднику строит `services/erp_bot_messages.py` из `settings.texts`.
        """
        ev = env.event
        p = env.payload
        deal_title = env.deal.title if env.deal else (deal.title if deal else "Сделка")

        if ev == "request.created":
            src = p.get("source", "erp")
            req_id = p.get("erp_request_id")
            note = f"В бэк-офисе создана заявка #{req_id or '—'} (источник: {src})."
            return note

        if ev == "deal.stage_changed":
            to_st = p.get("to", env.deal.stage if env.deal else "")
            from_st = p.get("from", "")
            reason = p.get("reason")
            if deal:
                deal.external_stage = to_st
            note = f"Стадия сделки в бэк-офисе: {from_st} → {to_st}"
            if reason:
                note += f" ({reason})"
            return note

        if ev == "deal.won":
            amt = p.get("amount", env.deal.amount if env.deal else "") or ""
            curr = p.get("currency", env.deal.currency if env.deal else "")
            if deal:
                current_st = (
                    DealStage(deal.stage)
                    if deal.stage in ("open", "won", "lost")
                    else DealStage.OPEN
                )
                plan = plan_erp_outcome("deal.won", current_st, None)
                deal.stage = plan.stage.value
                deal.closed_at = env.occurred_at
                deal.external_stage = "won"
                if amt:
                    deal.amount = Decimal(amt)
                if curr:
                    deal.currency = curr
            note = f"Сделка «{deal_title}» успешно закрыта (won) на сумму {amt} {curr}."
            return note

        if ev == "deal.lost":
            reason = p.get("lost_reason")
            if deal:
                current_st = (
                    DealStage(deal.stage)
                    if deal.stage in ("open", "won", "lost")
                    else DealStage.OPEN
                )
                plan = plan_erp_outcome("deal.lost", current_st, reason)
                deal.stage = plan.stage.value
                deal.lost_reason = plan.lost_reason
                deal.closed_at = env.occurred_at
                deal.external_stage = "lost"
            r_str = reason or "не указана"
            note = f"Сделка «{deal_title}» закрыта отказом (lost). Причина: {r_str}."
            return note

        if ev == "quote.sent":
            if deal:
                deal.external_stage = "quote_sent"
            q_id = p.get("erp_quote_id")
            ver = p.get("version")
            pub_url = p.get("public_url", "")
            tot = p.get("total")
            curr = p.get("currency")
            note_parts = [f"Клиенту отправлено КП #{q_id} v{ver}"]
            if tot and curr:
                note_parts.append(f"на сумму {tot} {curr}")
            if pub_url:
                note_parts.append(f"Ссылка: {pub_url}")
            note = ". ".join(note_parts) + "."
            return note

        if ev == "quote.viewed":
            q_id = p.get("erp_quote_id")
            ver = p.get("version")
            note = f"Клиент открыл КП #{q_id} v{ver}."
            return note

        if ev == "quote.accepted":
            if deal:
                deal.external_stage = "accepted"
            q_id = p.get("erp_quote_id")
            ver = p.get("version")
            note = f"Клиент акцептовал КП #{q_id} v{ver}."
            return note

        if ev == "quote.rejected":
            q_id = p.get("erp_quote_id")
            ver = p.get("version")
            reason = p.get("reason")
            r_suff = f". Причина: {reason}." if reason else "."
            note = f"КП #{q_id} v{ver} отклонено клиентом{r_suff}"
            return note

        if ev == "contract.signed":
            if deal:
                deal.external_stage = "contract"
            num = p.get("number", "")
            by = p.get("by", "")
            note = f"Договор {num} подписан ({by})."
            return note

        if ev == "invoice.issued":
            if deal:
                deal.external_stage = "invoiced"
            num = p.get("number", "")
            amt = p.get("amount", "")
            curr = p.get("currency", "")
            due = p.get("due_date", "")
            note = f"Выставлен счёт {num} на сумму {amt} {curr} со сроком оплаты до {due}."
            return note

        if ev == "invoice.paid":
            if deal:
                deal.external_stage = "paid"
            num = p.get("number", "")
            amt = p.get("amount", "")
            curr = p.get("currency", "")
            note = f"Счёт {num} на сумму {amt} {curr} оплачен."
            return note

        if ev == "invoice.overdue":
            num = p.get("number", "")
            due = p.get("due_date", "")
            note = f"Счёт {num} просрочен (срок оплаты был {due})."
            return note

        if ev == "delivery.status_changed":
            if deal:
                deal.external_stage = "fulfilment"
            summary = p.get("line_summary", "")
            st = p.get("status", "")
            eta = p.get("eta")
            note = f"Статус поставки ({summary}): {st}" + (f", ожидается {eta}" if eta else "")
            return note

        if ev == "delivery.eta_changed":
            summary = p.get("line_summary", "")
            eta = p.get("eta")
            prev_eta = p.get("previous_eta")
            note = f"Изменилась дата поставки ({summary}): {prev_eta or '—'} → {eta}."
            return note

        if ev == "act.issued":
            if deal:
                deal.external_stage = "closing"
            num = p.get("number", "")
            note = f"Сформирован акт {num}."
            return note

        if ev == "act.accepted":
            num = p.get("number", "")
            note = f"Акт {num} принят клиентом."
            return note

        if ev == "act.returned":
            num = p.get("number", "")
            reason = p.get("reason", "")
            note = f"Акт {num} возвращён клиентом с замечаниями: {reason}."
            return note

        if ev == "document.created":
            kind = p.get("kind", "other")
            num = p.get("number", "")
            title = p.get("title") or f"{kind} {num}"
            doc_type = DOC_KIND_MAP.get(kind, "other")
            doc_row = Document(
                client_id=client.id,
                type=doc_type,
                title=title,
                number=num or None,
                doc_date=env.occurred_at.date(),
                storage_key=None,
                filename=f"{kind}_{num}.pdf",
                mime="application/pdf",
                size_bytes=0,
                extract_status="skipped",
                is_visible_to_client=True,
            )
            session.add(doc_row)
            note = f"В бэк-офисе создан документ: {title} ({num})."
            return note

        if ev in ("delivery.line_accepted", "delivery.line_disputed"):
            # Стадию сделки задаёт DealRef события (выше, как у любого события со сделкой).
            # Запись в ленту и сообщение ответственному строятся в `process_event` из
            # `settings.texts`, клиенту бот молчит.
            return None

        if ev == "invite.sent":
            channels = ", ".join(p.get("channels", []))
            note = f"Контакту отправлено приглашение в кабинет через каналы: {channels}."
            return note

        return None

    async def _send_to_client_telegram(
        self,
        session: AsyncSession,
        client_id: int,
        message: BotMessage,
    ) -> None:
        """Отправка сообщения в Telegram всем привязанным аккаунтам клиента."""
        bot = await self._bot_provider()
        if bot is None or self._config.telegram_dry_run:
            return

        tg_ids = (
            await session.scalars(
                select(TelegramIdentity.tg_user_id).where(
                    TelegramIdentity.client_id == client_id,
                    TelegramIdentity.is_blocked.is_(False),
                )
            )
        ).all()

        reply_markup: InlineKeyboardMarkup | None = None
        if message.buttons:
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=label, url=url)] for label, url in message.buttons
                ]
            )

        for tg_id in tg_ids:
            try:
                await bot.send_message(
                    chat_id=tg_id,
                    text=message.text,
                    reply_markup=reply_markup,
                    request_timeout=10,
                )
            except (TelegramAPIError, OSError, ValueError) as exc:
                logger.warning(
                    "client_telegram_notify_failed",
                    client_id=client_id,
                    tg_user_id=tg_id,
                    error=str(exc),
                )

    async def _send_to_staff(
        self,
        session: AsyncSession,
        user_id: int,
        text: str,
    ) -> None:
        """Отправка уведомления сотруднику в личный Telegram."""
        bot = await self._bot_provider()
        if bot is None or self._config.telegram_dry_run:
            return

        tg_user_id = await session.scalar(
            select(User.tg_user_id).where(User.id == user_id, User.is_active.is_(True))
        )
        if tg_user_id:
            try:
                await bot.send_message(
                    chat_id=tg_user_id,
                    text=text,
                    request_timeout=10,
                )
            except (TelegramAPIError, OSError, ValueError) as exc:
                logger.warning(
                    "staff_notify_failed",
                    user_id=user_id,
                    tg_user_id=tg_user_id,
                    error=str(exc),
                )
