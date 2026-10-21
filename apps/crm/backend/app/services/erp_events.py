"""Сервис обработки входящих событий ERP (M3-CRM-04, CONTRACTS §3, ADR-0022)."""

import hashlib
import hmac
import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import AuthError, ConflictError, Reason, ValidationFailedError
from app.integrations.erp import resolve_erp
from app.models.auth import User
from app.models.clients import Client
from app.models.deals import Deal
from app.models.integrations import ErpIncomingEvent
from app.models.leads import Lead, LeadNote, TelegramIdentity
from app.repositories import events
from app.schemas.erp_events import (
    CODE_EVENT,
    ErpEventEnvelope,
    QuoteAcceptanceCodeRequestedEvent,
    RequestCreatedEvent,
    is_known_event,
    parse_event,
    redact_secrets,
)
from app.security.secrets_store import SecretsStore
from app.services import deals as deals_service
from app.services.erp_acceptance_code import AcceptanceCodeDelivery
from app.services.erp_bot_messages import (
    client_message,
    feed_note,
    pick_language,
    staff_alert,
)
from app.services.erp_event_handlers import aware, dispatch
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)


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
    # Байты, а не строки: `compare_digest` на не-ASCII строке бросает TypeError (ответ был бы 500).
    return hmac.compare_digest(given_hex.encode("utf-8"), expected_hex.encode("utf-8"))


def verify_signature_any(
    secrets: Sequence[str], raw_body: bytes, signature_header: str | None
) -> bool:
    """Подпись верна хотя бы одним из принимаемых секретов (текущий и предыдущий, FIX-35).

    Проверяются все секреты без раннего выхода: время ответа не выдаёт, какой из них подошёл.
    """
    results = [verify_signature(secret, raw_body, signature_header) for secret in secrets]
    return any(results)


#: Неудачных обработок события до статуса `failed` (его видно в центре внешних сервисов).
MAX_ATTEMPTS = 5
#: Строка `received` старше этого не ждёт своей задачи, а потеряна: сборщик ставит её заново.
STUCK_AFTER = timedelta(seconds=60)
SWEEP_LIMIT = 100
#: Неотправленное сообщение старше этого сборщик не досылает (устаревший «счёт выставлен» вредит).
UNSENT_MAX_AGE = timedelta(hours=24)
#: События, чьё сообщение клиенту описывает ТЕКУЩЕЕ состояние (срок, статус поставки, стадия):
#: устаревшим они в бот не уходят — только в ленту. Разовые факты (КП, счёт, акт) доходят всегда.
STALE_SILENT_EVENTS = frozenset(
    {"delivery.status_changed", "delivery.eta_changed", "deal.stage_changed"}
)
RAW_PREVIEW_CHARS = 2000


def _is_fresh(deal: Deal, occurred_at: datetime) -> bool:
    """Событие применяется к зеркалу, если не старее уже применённого (порядок по `occurred_at`).

    Равное время применяется: у двух событий одного мгновения порядок прихода и есть порядок.
    """
    return deal.external_stage_at is None or aware(occurred_at) >= deal.external_stage_at


def _id_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True, slots=True)
class ParsedBody:
    """Итог разбора тела: `received` (конверт разобран), `skipped` (неизвестный тип) или
    `rejected`.
    """

    status: str
    data: dict[str, Any]
    envelope: ErpEventEnvelope | None = None
    error: str | None = None


def _raw_preview(raw_body: bytes) -> dict[str, Any]:
    return {"raw": raw_body[:RAW_PREVIEW_CHARS].decode("utf-8", "replace")}


def _parse_body(raw_body: bytes, event_type: str) -> ParsedBody:
    """Тело события → итог разбора для журнала; секреты в `data` вырезаны (код акцепта).

    Конверт (`envelope`) разобран по исходному телу и несёт код в `SecretStr`; `data` — то, что
    пишется в журнал: код заменён на `[redacted]`, а тело, которое не разобралось (сломанный
    JSON, не по схеме), у события с кодом не сохраняется даже кусками.
    """
    parsed = _parse_body_raw(raw_body, event_type)
    secret_event = event_type == CODE_EVENT or parsed.data.get("event") == CODE_EVENT
    if not secret_event:
        return parsed
    unreadable = "raw" in parsed.data and "event" not in parsed.data
    data = (
        {"raw": "[withheld: body of a secret event]"}
        if unreadable
        else redact_secrets(parsed.data, event_type)
    )
    return ParsedBody(parsed.status, data, parsed.envelope, parsed.error)


def _parse_body_raw(raw_body: bytes, event_type: str) -> ParsedBody:
    """Тело события → итог разбора для журнала.

    Читатель терпимый (FIX-35): тело, которое мы принять не можем, не даёт 4xx — ретраи ERP
    (до 24 ч) ничего бы не изменили. Сломанный JSON, не по схеме или расхождение с заголовком —
    `rejected`; **неизвестный тип события** (новое событие более новой ERP) — `skipped`: принято,
    записано, не обрабатывается, красным в центре внешних сервисов не горит. Известный тип
    разбирается дискриминированной моделью по `event`.
    """
    try:
        data = json.loads(raw_body)
    except ValueError:
        return ParsedBody("rejected", _raw_preview(raw_body), error="invalid JSON")
    if not isinstance(data, dict):
        return ParsedBody("rejected", _raw_preview(raw_body), error="not an object")
    if "\\u0000" in json.dumps(data):  # JSONB не хранит NUL
        return ParsedBody("rejected", {"raw": "contains NUL"}, error="NUL in body")
    name = data.get("event")
    if isinstance(name, str) and name != event_type:
        return ParsedBody(
            "rejected", data, error=f"event type header mismatch: {event_type} != {name}"
        )
    if isinstance(name, str) and not is_known_event(name):
        return ParsedBody("skipped", data, error=f"unknown event type: {name}"[:500])
    try:
        envelope = parse_event(data)
    except ValidationError as exc:
        errors = exc.errors()
        detail = (
            f"{'.'.join(str(p) for p in errors[0]['loc'])}: {errors[0]['msg']}" if errors else ""
        )
        return ParsedBody("rejected", data, error=f"invalid event envelope: {detail}"[:500])
    return ParsedBody("received", data, envelope=envelope)


def _body_hash(raw_body: bytes, parsed: ParsedBody, event_type: str) -> str:
    """sha256 тела для защиты от повтора. У события с кодом — хеш тела БЕЗ кода (то, что пишется
    в журнал после `redact_secrets`): иначе код из 4–12 цифр подбирался бы по хешу из журнала.
    Повтор того же тела по-прежнему ловится.
    """
    if CODE_EVENT in (event_type, parsed.data.get("event")):
        canonical = json.dumps(parsed.data, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(canonical).hexdigest()
    return hashlib.sha256(raw_body).hexdigest()


class ErpEventsService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings_service: SettingsService,
        secrets_store: SecretsStore,
        config: Settings,
        bot_provider: Callable[[], Awaitable[Bot | None]],
        enqueue_task: Callable[[str], Awaitable[int | None]] | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings_service = settings_service
        self._secrets_store = secrets_store
        self._config = config
        self._bot_provider = bot_provider
        self._enqueue_task = enqueue_task
        self._acceptance_code = AcceptanceCodeDelivery(
            sessions, settings_service, bot_provider, config
        )

    async def get_webhook_secrets(self) -> tuple[str, ...]:
        """Секреты, которыми принимается подпись: текущий и предыдущий («Подключения» → ERP, иначе
        env).
        """
        resolution = await resolve_erp(self._secrets_store, self._config, self._settings_service)
        return resolution.webhook_secrets

    async def receive_event(
        self,
        event_id: str | None,
        event_type: str | None,
        signature: str | None,
        raw_body: bytes,
    ) -> tuple[bool, str]:
        """Приём вебхука: подпись → заголовки → разбор тела → идемпотентная фиксация → очередь.

        Подпись проверяется по сырому телу ДО любого разбора (FIX-33): неподписанный запрос не
        заставляет CRM разбирать JSON и не узнаёт, что именно в теле не так. Дальше:
        постоянный отказ по телу (неизвестный тип, чужой формат) — строка `rejected` и 200;
        сбой постановки в очередь строку не теряет и ответ не ломает — её подберёт `sweep`.

        Возвращает: (is_duplicate, status_str). Ошибки: 409 (секрет не настроен), 401 (подпись),
        422 (заголовки при верной подписи).
        """
        secrets = await self.get_webhook_secrets()
        if not secrets:
            logger.warning("erp_webhook_secret_missing", event_id=event_id)
            raise ConflictError(
                "erp webhook secret is not configured", reason=Reason.ERP_NOT_CONFIGURED
            )

        if not verify_signature_any(secrets, raw_body, signature):
            logger.warning("erp_webhook_invalid_signature", event_id=event_id)
            raise AuthError("invalid webhook signature")

        try:
            event_id = str(uuid.UUID(event_id or ""))
        except ValueError:
            raise ValidationFailedError("invalid X-Event-Id UUID", field="X-Event-Id") from None
        if not event_type:
            raise ValidationFailedError("missing X-Event-Type", field="X-Event-Type")

        parsed = _parse_body(raw_body, event_type)
        envelope, data = parsed.envelope, parsed.data
        body_hash = _body_hash(raw_body, parsed, event_type)
        status, error = parsed.status, parsed.error
        # Код акцепта не ждёт очереди: задача и `outbox` хранили бы его в БД. Строка журнала
        # сразу «обработана» (код вырезан), доставка — ниже, из памяти этого запроса.
        code_event = envelope if isinstance(envelope, QuoteAcceptanceCodeRequestedEvent) else None
        if code_event is not None:
            status = "processed"
        now = datetime.now(UTC)
        incoming = ErpIncomingEvent(
            event_id=event_id,
            event_type=event_type[:64],
            erp_company_id=envelope.erp_company_id
            if envelope
            else _id_or_none(data.get("erp_company_id")),
            crm_client_id=envelope.crm_client_id
            if envelope
            else _id_or_none(data.get("crm_client_id")),
            payload=data,
            status=status,
            error=error,
            processed_at=None if status == "received" else now,
            notified_at=now if code_event is not None else None,
            body_sha256=body_hash,
        )
        try:
            async with self._sessions() as session, session.begin():
                if await session.get(ErpIncomingEvent, event_id) is not None:
                    logger.info("erp_webhook_duplicate", event_id=event_id, event_type=event_type)
                    return True, "duplicate"
                # Подпись не покрывает X-Event-Id и X-Timestamp: перехваченное тело можно прислать
                # под новым id. Тело, чей sha256 уже принят под другим id, — повтор: 200 и
                # `rejected`, без обработки.
                original = await session.scalar(
                    select(ErpIncomingEvent.event_id)
                    .where(ErpIncomingEvent.body_sha256 == body_hash)
                    .limit(1)
                )
                if original is not None:
                    incoming.status, status = "rejected", "rejected"
                    incoming.error = error = f"replayed body: already received as event {original}"
                    incoming.processed_at = datetime.now(UTC)
                    incoming.notified_at = None
                    code_event = None  # повтор тела: код не отправляется
                session.add(incoming)
        except IntegrityError:  # тот же event_id вставил параллельный запрос
            return True, "duplicate"

        if code_event is not None:
            return False, await self._acceptance_code.deliver(event_id, code_event)
        if status != "received":
            logger.warning(
                "erp_webhook_not_processed", event_id=event_id, status=status, reason=error
            )
            return False, status
        return False, await self._enqueue(event_id)

    async def _enqueue(self, event_id: str) -> str:
        """Поставить обработку; сбой очереди событие не теряет — его подберёт `sweep`."""
        if self._enqueue_task is None:
            return "stored"
        try:
            await self._enqueue_task(event_id)
        except Exception:
            logger.exception("erp_webhook_enqueue_failed", event_id=event_id)
            return "stored"
        logger.info("erp_webhook_enqueued", event_id=event_id)
        return "enqueued"

    async def sweep(self, limit: int = SWEEP_LIMIT) -> int:
        """Подобрать события, которые никто не обрабатывает (периодическая задача, раз в минуту).

        * `received` старше `STUCK_AFTER`: постановка в очередь не удалась или задача потеряна;
        * `processed`, но сообщения в Telegram так и не захвачены (воркер упал между коммитом и
          отправкой, либо бота не было). Старше `UNSENT_MAX_AGE` сообщение уже не имеет смысла.
        Возвращает число поставленных событий и отправленных сообщений.
        """
        horizon = datetime.now(UTC) - STUCK_AFTER
        async with self._sessions() as session:
            stuck = list(
                await session.scalars(
                    select(ErpIncomingEvent.event_id)
                    .where(
                        ErpIncomingEvent.status == "received",
                        ErpIncomingEvent.received_at < horizon,
                    )
                    .order_by(ErpIncomingEvent.received_at)
                    .limit(limit)
                )
            )
            unsent = list(
                await session.scalars(
                    select(ErpIncomingEvent.event_id)
                    .where(
                        ErpIncomingEvent.status == "processed",
                        ErpIncomingEvent.outbox.is_not(None),
                        ErpIncomingEvent.notified_at.is_(None),
                        ErpIncomingEvent.processed_at < horizon,
                        ErpIncomingEvent.processed_at > datetime.now(UTC) - UNSENT_MAX_AGE,
                    )
                    .order_by(ErpIncomingEvent.processed_at)
                    .limit(limit)
                )
            )
        for event_id in stuck:
            await self._enqueue(event_id)
        sent = 0
        for event_id in unsent:
            sent += await self.deliver_notifications(event_id)
        if stuck or sent:
            logger.warning("erp_events_swept", requeued=len(stuck), notified=sent)
        return len(stuck) + sent

    async def process_event(self, event_id: str) -> bool:
        """Обработка события: зеркало, документы, лента — в транзакции; Telegram — после коммита."""
        try:
            applied = await self._apply(event_id)
        except Exception as exc:
            await self._note_failure(event_id, exc)
            raise
        if applied:
            await self.deliver_notifications(event_id)
        return applied

    async def _note_failure(self, event_id: str, exc: Exception) -> None:
        """Неудачная обработка: счётчик и ошибка; на потолке — `failed`, не крутить вечно."""
        try:
            async with self._sessions() as session, session.begin():
                row = await session.get(ErpIncomingEvent, event_id, with_for_update=True)
                if row is None or row.status == "processed":
                    return
                row.attempts = (row.attempts or 0) + 1
                row.error = f"{type(exc).__name__}: {exc}"[:500]
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = "failed"
        except Exception:
            logger.exception("erp_event_failure_note_failed", event_id=event_id)

    async def _apply(self, event_id: str) -> bool:
        async with self._sessions() as session, session.begin():
            event_row = await session.get(ErpIncomingEvent, event_id, with_for_update=True)
            if event_row is None:
                logger.warning("erp_event_not_found_for_processing", event_id=event_id)
                return False

            if event_row.status == "processed":
                logger.info("erp_event_already_processed", event_id=event_id)
                return True
            if event_row.status in ("rejected", "skipped"):
                return False
            if event_row.event_type == CODE_EVENT:
                return False  # код вырезан из журнала и доставляется при приёме, не из очереди

            envelope = parse_event(event_row.payload)
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
                # Передача ещё идёт (ответ ERP не записан): сопоставление берём из подписанного
                # события — `crm_client_id` в нём ERP взяла из сопоставления, созданного нашей же
                # передачей. Ждать нельзя: при сбое передачи событие зависло бы навсегда.
                client.erp_company_id = envelope.erp_company_id
            elif client.erp_company_id != envelope.erp_company_id:
                event_row.status = "rejected"
                event_row.processed_at = datetime.now(UTC)
                event_row.error = (
                    f"company mismatch: client #{client.id} is erp company "
                    f"#{client.erp_company_id}, event carries #{envelope.erp_company_id}"
                )
                logger.warning("erp_event_company_mismatch", event_id=event_id, client_id=client.id)
                return False

            lead = await session.scalar(
                select(Lead).where(Lead.client_id == client.id).order_by(Lead.id.desc()).limit(1)
            )

            deal: Deal | None = None
            fresh = True
            if envelope.deal is not None:
                deal, created = await self._mirror(session, client, lead, envelope)
                fresh = created or _is_fresh(deal, envelope.occurred_at)
                if fresh:
                    deal.external_stage = envelope.deal.stage
                    deal.external_stage_at = aware(envelope.occurred_at)
                    deal.title = envelope.deal.title
                    if envelope.deal.amount is not None:
                        deal.amount = Decimal(envelope.deal.amount)
                    deal.currency = envelope.deal.currency
                    if deal.client_id is None:
                        deal.client_id = client.id
                else:
                    logger.info(
                        "erp_event_stale",
                        event_id=event_id,
                        event_type=envelope.event,
                        occurred_at=envelope.occurred_at.isoformat(),
                    )
                event_row.deal_id = deal.id

            # Устаревшее событие стадию, название и сумму зеркала не меняет (они возвращаются после
            # обработчика), но итог сделки (`won`/`lost`) применяется, а в ленту событие пишется.
            mirror = (deal.external_stage, deal.title, deal.amount, deal.currency) if deal else None
            note_text = await dispatch(session, envelope, client, deal)
            if deal is not None and not fresh and mirror is not None:
                deal.external_stage, deal.title, deal.amount, deal.currency = mirror
            cfg = await self._settings_service.get()
            deal_title = envelope.deal.title if envelope.deal else (deal.title if deal else "—")
            body = envelope.payload.model_dump(mode="json", by_alias=True)
            bot_msg = client_message(
                envelope.event,
                body,
                deal_title=deal_title,
                texts=cfg.texts,
                language=pick_language(lead.language if lead else None),
                cabinet_url=cfg.company.cabinet_url,
            )
            if note_text is None:
                # Приёмка и замечания по строкам поставки: текст ленты — из настроек (FIX-37).
                note_text = feed_note(
                    envelope.event,
                    body,
                    contact_name=envelope.actor.name,
                    deal_title=deal_title,
                    texts=cfg.texts,
                )
            staff_alert_text = staff_alert(
                envelope.event,
                body,
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

            # Сообщения не отправляются внутри транзакции: откат или повтор задачи не должен
            # задваивать их. Они записываются в строку события и уходят после коммита
            # (`deliver_notifications`).
            outbox: list[dict[str, Any]] = []
            if bot_msg and not (not fresh and envelope.event in STALE_SILENT_EVENTS):
                outbox.append(
                    {
                        "kind": "client",
                        "client_id": client.id,
                        "text": bot_msg.text,
                        "buttons": [list(button) for button in bot_msg.buttons],
                    }
                )
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
                    outbox.append(
                        {"kind": "staff", "user_id": target_user_id, "text": staff_alert_text}
                    )
            event_row.outbox = outbox or None

            event_row.status = "processed"
            event_row.processed_at = datetime.now(UTC)
            event_row.error = None

        return True

    async def _mirror(
        self,
        session: AsyncSession,
        client: Client,
        lead: Lead | None,
        envelope: ErpEventEnvelope,
    ) -> tuple[Deal, bool]:
        """Зеркало сделки ERP: найти по `erp_deal_id`, иначе занять сделку лида или создать.

        Уникальный `deals.erp_deal_id` — последний рубеж: если параллельно то же зеркало создала
        передача клиента (`erp_handoff._mirror_request`), вставка в savepoint упадёт, и мы берём
        созданное — зеркало остаётся одно, каким бы порядком ни пришли ответ ERP и событие.
        Возвращает (сделка, создана ли новая).
        """
        if envelope.deal is None:
            raise ValueError("event has no deal")
        erp_deal_id = envelope.deal.erp_deal_id
        found = await self._find_mirror(session, erp_deal_id)
        if found is not None:
            return found, False

        # Заявка передачи (`source=crm`) — уже существующая сделка лида: второй не заводим.
        adopt: Deal | None = None
        if (
            lead is not None
            and isinstance(envelope, RequestCreatedEvent)
            and envelope.payload.source == "crm"
        ):
            adopt = await deals_service.open_deal(session, lead.id)
            if adopt is not None and adopt.erp_deal_id is not None:
                adopt = None
        try:
            async with session.begin_nested():
                if adopt is not None:
                    adopt.erp_deal_id = erp_deal_id
                    deal = adopt
                    created = False
                else:
                    deal = Deal(
                        client_id=client.id,
                        lead_id=lead.id if lead else None,
                        title=envelope.deal.title,
                        amount=_deal_amount(envelope.deal.amount),
                        currency=envelope.deal.currency,
                        stage="open",
                        external_stage=envelope.deal.stage,
                        erp_deal_id=erp_deal_id,
                    )
                    session.add(deal)
                    created = True
                await session.flush()
        except IntegrityError:
            existing = await self._find_mirror(session, erp_deal_id)
            if existing is None:
                raise
            return existing, False
        return deal, created

    @staticmethod
    async def _find_mirror(session: AsyncSession, erp_deal_id: int) -> Deal | None:
        return await session.scalar(
            select(Deal).where(Deal.erp_deal_id == erp_deal_id).limit(1).with_for_update()
        )

    async def deliver_notifications(self, event_id: str) -> int:
        """Отправить сообщения события в Telegram — после коммита обработки и не больше одного раза.

        Строка события захватывается под блокировкой: `notified_at` ставится ДО отправки, поэтому
        повтор события, повторная задача и сборщик второго сообщения не пошлют (ключ — событие).
        Цена — при падении воркера между захватом и отправкой сообщение теряется (а не дублируется).
        Возвращает число отправленных сообщений.
        """
        async with self._sessions() as session, session.begin():
            row = await session.get(ErpIncomingEvent, event_id, with_for_update=True)
            if row is None or not row.outbox or row.notified_at is not None:
                return 0
            bot = await self._bot_provider()
            if bot is None or self._config.telegram_dry_run:
                # Бота нет или он выключен: сообщения не захватываются и не теряются — их отправит
                # сборщик, когда бот появится (старше суток — не досылается, см. `sweep`).
                return 0
            row.notified_at = datetime.now(UTC)
            sends: list[tuple[int, str, InlineKeyboardMarkup | None]] = []
            for item in row.outbox:
                if item.get("kind") == "client":
                    markup = _markup(item.get("buttons") or [])
                    tg_ids = (
                        await session.scalars(
                            select(TelegramIdentity.tg_user_id).where(
                                TelegramIdentity.client_id == item["client_id"],
                                TelegramIdentity.is_blocked.is_(False),
                            )
                        )
                    ).all()
                    sends += [(tg_id, item["text"], markup) for tg_id in tg_ids]
                elif item.get("kind") == "staff":
                    tg_user_id = await session.scalar(
                        select(User.tg_user_id).where(
                            User.id == item["user_id"], User.is_active.is_(True)
                        )
                    )
                    if tg_user_id:
                        sends.append((tg_user_id, item["text"], None))

        sent = 0
        for chat_id, text, markup in sends:
            try:
                await bot.send_message(
                    chat_id=chat_id, text=text, reply_markup=markup, request_timeout=10
                )
                sent += 1
            except (TelegramAPIError, OSError, ValueError) as exc:
                logger.warning(
                    "erp_event_telegram_failed",
                    event_id=event_id,
                    tg_user_id=chat_id,
                    error=str(exc),
                )
        return sent


def _markup(buttons: list[list[str]]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, url=url)] for label, url in buttons]
    )
