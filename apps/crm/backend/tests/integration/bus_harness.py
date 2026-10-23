"""Стенд шины CRM для integration-тестов: настоящие БД и `CrmBus`, подставной Telegram.

`Harness` собирает то же, что `Container.bus`, но с подставными бот-провайдером и очередью:
приём (`receive`) идёт через библиотечный приёмник с подписью пары `erp → crm`, обработка —
`process` (= задача `rt_bus.process_inbox`), сообщения Telegram — после коммита, как в проде.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from rt_bus.receiver import ReceiveResult
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import runtime
from app.bus.erp_event import ErpEvent
from app.bus.notices import ErpEventNotices
from app.bus.runtime import CrmBus, build_bus
from app.bus.secrets import derive_pair_secret
from app.config import Settings
from app.models.clients import Client
from app.models.deals import Deal
from app.models.integrations import ErpEventNotice
from app.models.leads import Lead, TelegramIdentity
from app.services.erp_acceptance_code import AcceptanceCodeDelivery
from app.services.erp_events import ErpEventsService
from app.services.settings import SettingsService
from tests.bus_events import WEBHOOK_SECRET, envelope_for, signed_request

ERP_COMPANY = 202
ERP_DEAL = 9001
INBOX = "SELECT status, attempts, error FROM rt_bus_inbox WHERE event_id = :id"


T0 = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
TYPE_PREFIX = "uz.railtech.erp."

STAGE_PAYLOADS: dict[str, dict[str, Any]] = {
    "request.created": {"source": "crm", "erp_request_id": ERP_DEAL},
    "quote.sent": {"erp_quote_id": 4, "version": 1, "public_url": "https://erp.example.com/q/4"},
    "invoice.paid": {
        "erp_invoice_id": 5,
        "number": "INV-1",
        "amount": "100.00",
        "currency": "UZS",
        "due_date": "2026-10-30",
    },
    "delivery.eta_changed": {"line_summary": "Оси", "eta": "2026-11-01", "status": "in_transit"},
    "delivery.status_changed": {"line_summary": "Оси", "status": "shipped"},
    "deal.won": {"amount": "100.00", "currency": "UZS"},
}
STAGES = {
    "request.created": "request",
    "quote.sent": "quote_sent",
    "invoice.paid": "paid",
    "delivery.eta_changed": "fulfilment",
    "delivery.status_changed": "fulfilment",
    "deal.won": "contract",
}


def event_type_of(event: str) -> str:
    """`quote.sent` → `uz.railtech.erp.quote.sent.v1`."""
    return f"{TYPE_PREFIX}{event}.v1"


def data_for(
    event: str,
    client_id: int,
    *,
    company_id: int = ERP_COMPANY,
    erp_deal_id: int = ERP_DEAL,
    title: str = "Поставка осей",
    stage: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Поле `data` события ERP (контракт `events/erp/<тип>.v1.json`) с минимальным телом."""
    return {
        "erp_company_id": company_id,
        "crm_client_id": client_id,
        "deal": {
            "erp_deal_id": erp_deal_id,
            "number": f"D-{erp_deal_id}",
            "title": title,
            "stage": stage or STAGES[event],
            "amount": "100.00",
            "currency": "UZS",
        },
        "actor": {"type": "system"},
        "payload": payload if payload is not None else STAGE_PAYLOADS[event],
    }


class FakeContainer:
    """Минимум контейнера для обработчиков шины и публикаций: сервис событий ERP и шина."""

    def __init__(self, service: ErpEventsService, bus: CrmBus) -> None:
        self.erp_events_service = service
        self.bus = bus


class SpyBot:
    """Бот, который при отправке смотрит в БД другой сессией: закоммичена ли обработка события."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self.sent: list[tuple[int, str]] = []
        self.markups: list[Any] = []
        self.inbox_status_at_send: list[str | None] = []
        self.fail_with: Exception | None = None

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> Any:
        if self.fail_with is not None:
            raise self.fail_with
        async with self._sessions() as session:
            statuses = (
                (await session.execute(sql_text("SELECT status FROM rt_bus_inbox"))).scalars().all()
            )
        self.inbox_status_at_send.append(statuses[0] if len(statuses) == 1 else None)
        self.sent.append((chat_id, text))
        self.markups.append(kwargs.get("reply_markup"))
        return object()


class Harness:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, telegram_dry_run: bool = False
    ) -> None:
        self.sessions = sessions
        self.bot = SpyBot(sessions)
        self.bot_available = True
        self.enqueued: list[str] = []
        self.enqueue_error: Exception | None = None
        self.config = Settings(_env_file=None, app_env="test", telegram_dry_run=telegram_dry_run)
        settings_service = SettingsService(sessions)
        self.notices = ErpEventNotices(sessions, cast(Any, self._bot), self.config)
        self.service = ErpEventsService(
            settings_service,
            self.notices,
            AcceptanceCodeDelivery(sessions, settings_service, cast(Any, self._bot), self.config),
        )
        self.bus: CrmBus = build_bus(
            sessions,
            None,
            after_processed=self.notices.deliver,
            enqueue=self._enqueue,
        )
        self.bus.secret_cache.set_webhook_secrets([WEBHOOK_SECRET])
        from app.bus import handlers  # noqa: F401 — регистрирует обработчики

        runtime.install(cast(Any, FakeContainer(self.service, self.bus)))

    def close(self) -> None:
        runtime.install(None)

    async def _bot(self) -> SpyBot | None:
        return self.bot if self.bot_available else None

    async def _enqueue(self, event_id: str) -> None:
        if self.enqueue_error is not None:
            raise self.enqueue_error
        self.enqueued.append(event_id)

    # --- приём и обработка --------------------------------------------------------------------

    @staticmethod
    def secret(publisher: str = "erp", subscriber: str = "crm") -> str:
        return derive_pair_secret(WEBHOOK_SECRET, publisher, subscriber)

    async def post(
        self, envelope: dict[str, Any], *, secret: str | None = None, now: datetime | None = None
    ) -> ReceiveResult:
        headers, body = signed_request(envelope, secret or self.secret(), now=now)
        return await self.bus.receive(headers, body)

    async def receive(self, event_type: str, data: dict[str, Any], **kwargs: Any) -> str:
        """Принять событие ERP через приёмник шины; возвращает id события."""
        envelope = envelope_for(event_type, data, **kwargs)
        result = await self.post(envelope)
        assert result.status_code == 200, result.body
        assert result.body["status"] == "received", result.body
        return str(envelope["id"])

    async def store(
        self, event: str, client_id: int, *, occurred_at: datetime = T0, **overrides: Any
    ) -> str:
        """Принять событие ERP по короткому имени (`quote.sent`) с минимальным телом."""
        event_id = overrides.pop("event_id", None)
        data = data_for(event, client_id, **overrides)
        return await self.receive(event_type_of(event), data, time=occurred_at, event_id=event_id)

    async def process(self, event_id: str) -> str | None:
        """Задача очереди `rt_bus.process_inbox`: обработчики в транзакции, затем Telegram."""
        return await self.bus.process_inbox(event_id)

    async def inbox(self, event_id: str) -> dict[str, Any]:
        async with self.sessions() as session:
            row = (
                (await session.execute(sql_text(INBOX), {"id": uuid.UUID(event_id)}))
                .mappings()
                .first()
            )
        assert row is not None
        return dict(row)

    async def notice(self, event_id: str) -> ErpEventNotice | None:
        async with self.sessions() as session:
            return await session.get(ErpEventNotice, uuid.UUID(event_id))

    # --- данные -------------------------------------------------------------------------------

    async def seed_client(
        self, *, erp_company_id: int | None = ERP_COMPANY, tg_user_id: int | None = 777
    ) -> tuple[int, int]:
        """Клиент с лидом и Telegram-аккаунтом; возвращает (client_id, lead_id)."""
        async with self.sessions() as session, session.begin():
            client = Client(name="ООО Порядок", erp_company_id=erp_company_id)
            session.add(client)
            await session.flush()
            lead = Lead(
                display_name="Порядок",
                stage="customer",
                owner_mode="bot",
                client_id=client.id,
                language="ru",
            )
            session.add(lead)
            await session.flush()
            if tg_user_id is not None:
                session.add(
                    TelegramIdentity(
                        tg_user_id=tg_user_id,
                        client_id=client.id,
                        lead_id=lead.id,
                        tg_first_name="A",
                    )
                )
            return client.id, lead.id

    async def deals(self) -> list[Deal]:
        async with self.sessions() as session:
            return list((await session.scalars(select(Deal).order_by(Deal.id))).all())

    def parsed(self, event_type: str, data: dict[str, Any]) -> ErpEvent:
        """Событие в виде `ErpEvent` — для прямых вызовов `dispatch`."""
        from rt_bus import Event

        from app.bus.erp_event import parse_erp_event

        return parse_erp_event(Event.from_dict(envelope_for(event_type, data)))
