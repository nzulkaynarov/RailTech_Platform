"""Надёжность приёма событий ERP на настоящей БД (FIX-33; I-9, I-10, I-11).

Проверки:
* Telegram уходит ПОСЛЕ коммита обработки и один раз на событие (повтор события, повторная задача
  и сборщик второго сообщения не шлют); откат обработки сообщений не оставляет;
* строка `received`, не поставленная в очередь, подбирается сборщиком; неотправленные тоже;
* потолок неудачных обработок → `failed`;
* сверка `client.erp_company_id` с конвертом: несовпадение — `rejected`, ничего не меняется;
  клиент без сопоставления (передача идёт) — событие применяется и сопоставление записывается;
* `deals.erp_deal_id` уникален; ответ передачи и `request.created` в любом порядке и параллельно
  дают одно зеркало;
* порядок по `occurred_at`: старое событие после нового стадию не откатывает (в т.ч. `eta_changed`
  после `paid`).
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.integrations.erp import HandoffResult
from app.models.clients import Client
from app.models.deals import Deal
from app.models.integrations import ErpIncomingEvent
from app.models.leads import Lead, LeadNote, TelegramIdentity
from app.repositories import events as events_repo
from app.schemas.erp_events import ErpEventEnvelope
from app.security.secrets_store import SecretsStore
from app.services.erp_events import MAX_ATTEMPTS, ErpEventsService
from app.services.erp_handoff import ErpHandoffService
from app.services.settings import SettingsService

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
ERP_COMPANY = 202
ERP_DEAL = 9001


class _NoSecrets(SecretsStore):
    def __init__(self) -> None:
        super().__init__(None, None)  # type: ignore[arg-type]

    @property
    def enabled(self) -> bool:
        return False


class SpyBot:
    """Бот, который при отправке смотрит в БД другой сессией: видна ли закоммиченная обработка."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self.sent: list[tuple[int, str]] = []
        self.status_at_send: list[str | None] = []

    async def send_message(self, chat_id: int, text: str, **_: Any) -> Any:
        async with self._sessions() as session:
            statuses = (await session.scalars(select(ErpIncomingEvent.status))).all()
        self.status_at_send.append(statuses[0] if len(statuses) == 1 else None)
        self.sent.append((chat_id, text))
        return object()


class Harness:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions
        self.bot = SpyBot(sessions)
        self.enqueued: list[str] = []
        self.enqueue_error: Exception | None = None
        self.service = ErpEventsService(
            sessions,
            SettingsService(sessions),
            _NoSecrets(),
            Settings(
                _env_file=None, app_env="test", erp_webhook_secret="x" * 40, telegram_dry_run=False
            ),
            cast(Any, self._bot),
            self._enqueue,
        )

    async def _bot(self) -> SpyBot:
        return self.bot

    async def _enqueue(self, event_id: str) -> int:
        if self.enqueue_error is not None:
            raise self.enqueue_error
        self.enqueued.append(event_id)
        return len(self.enqueued)

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

    async def store(self, event: str, client_id: int, **overrides: Any) -> str:
        """Положить принятое событие (как `receive_event` после проверки подписи)."""
        event_id = overrides.pop("event_id", str(uuid.uuid4()))
        envelope = envelope_for(event, client_id, **overrides)
        async with self.sessions() as session, session.begin():
            session.add(
                ErpIncomingEvent(
                    event_id=event_id,
                    event_type=event,
                    erp_company_id=envelope["erp_company_id"],
                    crm_client_id=client_id,
                    payload=envelope,
                    status="received",
                )
            )
        return str(event_id)

    async def row(self, event_id: str) -> ErpIncomingEvent:
        async with self.sessions() as session:
            row = await session.get(ErpIncomingEvent, event_id)
        assert row is not None
        return row

    async def deals(self) -> list[Deal]:
        async with self.sessions() as session:
            return list((await session.scalars(select(Deal).order_by(Deal.id))).all())


STAGE_PAYLOADS: dict[str, dict[str, Any]] = {
    "request.created": {"source": "crm", "erp_request_id": ERP_DEAL},
    "quote.sent": {"erp_quote_id": 4, "version": 1, "public_url": "https://erp.example.com/q/4"},
    "invoice.paid": {"erp_invoice_id": 5, "number": "INV-1", "amount": "100.00", "currency": "UZS"},
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


def envelope_for(
    event: str,
    client_id: int,
    *,
    occurred_at: datetime = T0,
    company_id: int = ERP_COMPANY,
    erp_deal_id: int = ERP_DEAL,
    title: str = "Поставка осей",
    stage: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "event": event,
        "occurred_at": occurred_at.isoformat(),
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


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession]) -> Harness:
    return Harness(sessions)


# --- Telegram после коммита и один раз -----------------------------------------------------------


async def test_telegram_goes_after_the_commit_and_only_once_per_event(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    event_id = await harness.store("quote.sent", client_id)

    assert await harness.service.process_event(event_id) is True

    assert [chat for chat, _ in harness.bot.sent] == [777]
    assert harness.bot.status_at_send == ["processed"], (
        "в момент отправки обработка уже закоммичена"
    )
    row = await harness.row(event_id)
    assert row.notified_at is not None

    # Повтор той же задачи, повторный приём события, сборщик и прямой вызов — второго сообщения нет.
    assert await harness.service.process_event(event_id) is True
    assert await harness.service.deliver_notifications(event_id) == 0
    await harness.service.sweep()
    assert len(harness.bot.sent) == 1


async def test_a_rolled_back_processing_sends_nothing_and_the_retry_sends_once(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id, _ = await harness.seed_client()
    event_id = await harness.store("quote.sent", client_id)
    real_publish = events_repo.publish
    calls = 0

    async def flaky_publish(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("db hiccup inside the transaction")
        await real_publish(*args, **kwargs)

    monkeypatch.setattr(events_repo, "publish", flaky_publish)

    with pytest.raises(RuntimeError):
        await harness.service.process_event(event_id)
    row = await harness.row(event_id)
    assert (row.status, row.attempts) == ("received", 1)
    assert "db hiccup" in (row.error or "")
    assert harness.bot.sent == [], "из откатившейся транзакции сообщение не уходит"
    async with harness.sessions() as session:
        assert (await session.scalars(select(LeadNote))).all() == []

    assert await harness.service.process_event(event_id) is True  # повтор задачи Procrastinate
    assert len(harness.bot.sent) == 1


async def test_a_poison_event_becomes_failed_after_the_attempt_ceiling(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id, _ = await harness.seed_client()
    event_id = await harness.store("quote.sent", client_id)

    async def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("always broken")

    monkeypatch.setattr(events_repo, "publish", broken)
    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(RuntimeError):
            await harness.service.process_event(event_id)

    row = await harness.row(event_id)
    assert (row.status, row.attempts) == ("failed", MAX_ATTEMPTS)
    await harness.service.sweep()
    assert harness.enqueued == [], "failed сборщик больше не ставит"


# --- Сборщик --------------------------------------------------------------------------------------


async def _age(harness: Harness, event_id: str, **delta: float) -> None:
    async with harness.sessions() as session, session.begin():
        await session.execute(
            update(ErpIncomingEvent)
            .where(ErpIncomingEvent.event_id == event_id)
            .values(
                received_at=datetime.now(UTC) - timedelta(**delta),
                processed_at=datetime.now(UTC) - timedelta(**delta),
            )
        )


async def test_a_received_row_that_never_reached_the_queue_is_picked_up(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    stuck = await harness.store("quote.sent", client_id)
    fresh = await harness.store("invoice.paid", client_id)
    await _age(harness, stuck, minutes=5)

    assert await harness.service.sweep() == 1

    assert harness.enqueued == [stuck], "свежая строка ещё ждёт свою задачу, зависшая — нет"
    assert fresh not in harness.enqueued


async def test_receive_with_a_dead_queue_stores_the_event_and_the_sweeper_recovers_it(
    harness: Harness,
) -> None:
    """Сквозной путь I-10: постановка упала → ответ 200 → строка осталась → сборщик → обработано."""
    import hashlib
    import hmac
    import json

    client_id, _ = await harness.seed_client()
    secret = "x" * 40
    raw = json.dumps(envelope_for("quote.sent", client_id)).encode()
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    event_id = str(uuid.uuid4())
    harness.enqueue_error = OSError("procrastinate down")

    assert await harness.service.receive_event(event_id, "quote.sent", signature, raw) == (
        False,
        "stored",
    )
    assert (await harness.row(event_id)).status == "received"

    harness.enqueue_error = None
    await _age(harness, event_id, minutes=5)
    assert await harness.service.sweep() == 1
    assert harness.enqueued == [event_id]
    assert await harness.service.process_event(event_id) is True
    assert (await harness.row(event_id)).status == "processed"
    assert len(harness.bot.sent) == 1


async def test_messages_left_unsent_after_a_crash_are_sent_by_the_sweeper_once(
    harness: Harness,
) -> None:
    """Воркер упал между коммитом обработки и отправкой: `notified_at` пуст, сообщение живо."""
    client_id, _ = await harness.seed_client()
    event_id = await harness.store("quote.sent", client_id)

    async def crash(_: str) -> int:
        return 0  # «процесс умер» до отправки

    with patch.object(harness.service, "deliver_notifications", crash):
        assert await harness.service.process_event(event_id) is True
    assert harness.bot.sent == []

    await _age(harness, event_id, minutes=5)
    assert await harness.service.sweep() == 1
    assert await harness.service.sweep() == 0
    assert len(harness.bot.sent) == 1


# --- Сверка компании ------------------------------------------------------------------------------


async def test_a_mismatching_company_is_rejected_recorded_and_changes_nothing(
    harness: Harness,
) -> None:
    client_id, _ = await harness.seed_client(erp_company_id=ERP_COMPANY)
    event_id = await harness.store("quote.sent", client_id, company_id=999)

    assert await harness.service.process_event(event_id) is False

    row = await harness.row(event_id)
    assert row.status == "rejected"
    assert "company mismatch" in (row.error or "")
    assert row.outbox is None
    assert await harness.deals() == []
    assert harness.bot.sent == []
    async with harness.sessions() as session:
        client = await session.get(Client, client_id)
        assert client is not None
        assert client.erp_company_id == ERP_COMPANY
        assert (await session.scalars(select(LeadNote))).all() == []
    # Повтор задачи отклонённое не воскрешает.
    assert await harness.service.process_event(event_id) is False
    assert (await harness.row(event_id)).status == "rejected"


async def test_a_client_without_a_mapping_yet_accepts_the_event_and_records_the_mapping(
    harness: Harness,
) -> None:
    """Передача ещё идёт (ответ ERP не записан): событие не отклоняется, сопоставление — из него."""
    client_id, _ = await harness.seed_client(erp_company_id=None)
    event_id = await harness.store("quote.sent", client_id)

    assert await harness.service.process_event(event_id) is True

    async with harness.sessions() as session:
        client = await session.get(Client, client_id)
        assert client is not None
        assert client.erp_company_id == ERP_COMPANY
    assert (await harness.row(event_id)).status == "processed"


# --- Уникальный erp_deal_id и одно зеркало --------------------------------------------------------


async def test_erp_deal_id_is_unique_in_the_database(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    async with harness.sessions() as session, session.begin():
        session.add(Deal(client_id=client_id, title="A", erp_deal_id=1))
        session.add(Deal(client_id=client_id, title="local 1"))  # NULL не конфликтует
        session.add(Deal(client_id=client_id, title="local 2"))
    with pytest.raises(IntegrityError):
        async with harness.sessions() as session, session.begin():
            session.add(Deal(client_id=client_id, title="B", erp_deal_id=1))


def _erp_answering(deal_id: int) -> Any:
    class Erp:
        async def handoff_client(self, payload: Any, *, idempotency_key: str | None = None) -> Any:
            return HandoffResult(
                erp_company_id=ERP_COMPANY,
                erp_request_id=deal_id,
                invite_sent_via=[],
                cabinet_url="https://cabinet.internal/x",
            )

    return Erp()


async def _prepare_handoff(harness: Harness, client_id: int, lead_id: int) -> None:
    async with harness.sessions() as session, session.begin():
        client = await session.get(Client, client_id)
        lead = await session.get(Lead, lead_id)
        assert client is not None
        assert lead is not None
        lead.consent_given_at = T0
        lead.consent_version = "v1"
        client.erp_handoff_status, client.erp_handoff_request = "pending", True
        client.erp_company_id = None


async def _handoff(harness: Harness, client_id: int, lead_id: int, deal_id: int = ERP_DEAL) -> str:
    await _prepare_handoff(harness, client_id, lead_id)
    service = ErpHandoffService(harness.sessions, _erp_answering(deal_id))
    return await service.run(client_id, lead_id, None)


async def test_event_before_the_handoff_answer_converges_to_one_mirror(harness: Harness) -> None:
    """FIX-31 → FIX-33: `request.created` приходит раньше, чем задача запишет `erp_deal_id`."""
    client_id, lead_id = await harness.seed_client(erp_company_id=None)
    async with harness.sessions() as session, session.begin():
        session.add(Deal(client_id=client_id, lead_id=lead_id, title="Локальная", stage="open"))
    event_id = await harness.store("request.created", client_id)

    assert await harness.service.process_event(event_id) is True
    assert await _handoff(harness, client_id, lead_id) == "done"

    (deal,) = await harness.deals()
    assert (deal.erp_deal_id, deal.lead_id, deal.client_id) == (ERP_DEAL, lead_id, client_id)
    assert deal.external_stage == "request"
    assert deal.title == "Поставка осей", "заявка ERP заняла сделку лида, а не завела вторую"


async def test_handoff_answer_before_the_event_converges_to_the_same_mirror(
    harness: Harness,
) -> None:
    client_id, lead_id = await harness.seed_client(erp_company_id=None)
    assert await _handoff(harness, client_id, lead_id) == "done"
    event_id = await harness.store("request.created", client_id)

    assert await harness.service.process_event(event_id) is True

    (deal,) = await harness.deals()
    assert (deal.erp_deal_id, deal.lead_id) == (ERP_DEAL, lead_id)


async def test_event_and_handoff_racing_in_parallel_leave_exactly_one_mirror(
    harness: Harness,
) -> None:
    for round_no in range(5):
        client_id, lead_id = await harness.seed_client(erp_company_id=None, tg_user_id=None)
        deal_id = ERP_DEAL + round_no
        async with harness.sessions() as session, session.begin():
            session.add(Deal(client_id=client_id, lead_id=lead_id, title="Локальная"))
        event_id = await harness.store(
            "request.created",
            client_id,
            erp_deal_id=deal_id,
            payload={"source": "crm", "erp_request_id": deal_id},
        )
        await _prepare_handoff(harness, client_id, lead_id)

        results = await asyncio.gather(
            harness.service.process_event(event_id),
            ErpHandoffService(harness.sessions, _erp_answering(deal_id)).run(
                client_id, lead_id, None
            ),
            return_exceptions=True,
        )

        assert list(results) == [True, "done"], results
        async with harness.sessions() as session:
            mirrors = (await session.scalars(select(Deal).where(Deal.erp_deal_id == deal_id))).all()
            local = (await session.scalars(select(Deal).where(Deal.lead_id == lead_id))).all()
        assert len(mirrors) == 1, f"round {round_no}: {len(mirrors)} mirrors"
        assert len(local) == 1, f"round {round_no}: the lead's deal was duplicated"


# --- Порядок по occurred_at -----------------------------------------------------------------------


async def _stage(harness: Harness) -> tuple[str | None, datetime | None, str]:
    (deal,) = await harness.deals()
    return deal.external_stage, deal.external_stage_at, deal.title


async def test_eta_changed_that_arrives_after_paid_does_not_roll_the_stage_back(
    harness: Harness,
) -> None:
    client_id, _ = await harness.seed_client()
    eta = await harness.store(
        "delivery.eta_changed", client_id, occurred_at=T0, title="Старое название"
    )
    paid = await harness.store(
        "invoice.paid", client_id, occurred_at=T0 + timedelta(hours=2), title="Новое название"
    )

    await harness.service.process_event(paid)  # пришло первым, хотя произошло позже
    await harness.service.process_event(eta)

    assert await _stage(harness) == ("paid", T0 + timedelta(hours=2), "Новое название")
    assert (await harness.row(eta)).status == "processed", (
        "событие записано и в ленте, зеркало не тронуто"
    )
    async with harness.sessions() as session:
        assert len((await session.scalars(select(LeadNote))).all()) == 2


async def test_a_newer_event_after_an_older_one_moves_the_stage_forward(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    first = await harness.store("quote.sent", client_id, occurred_at=T0)
    second = await harness.store("invoice.paid", client_id, occurred_at=T0 + timedelta(hours=1))

    await harness.service.process_event(first)
    await harness.service.process_event(second)

    stage, at, _ = await _stage(harness)
    assert (stage, at) == ("paid", T0 + timedelta(hours=1))


async def test_events_of_the_same_instant_apply_in_arrival_order(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    first = await harness.store("quote.sent", client_id, occurred_at=T0)
    second = await harness.store("invoice.paid", client_id, occurred_at=T0)

    await harness.service.process_event(first)
    await harness.service.process_event(second)

    assert (await _stage(harness))[0] == "paid"


async def test_a_stale_outcome_event_does_not_close_the_deal_again(harness: Harness) -> None:
    """`deal.won` старше уже применённого события: стадия сделки и `closed_at` не трогаются."""
    client_id, _ = await harness.seed_client()
    newer = await harness.store("invoice.paid", client_id, occurred_at=T0 + timedelta(hours=3))
    stale_won = await harness.store("deal.won", client_id, occurred_at=T0)

    await harness.service.process_event(newer)
    await harness.service.process_event(stale_won)

    (deal,) = await harness.deals()
    assert (deal.stage, deal.closed_at, deal.external_stage) == ("open", None, "paid")


async def test_the_envelope_schema_still_accepts_what_the_tests_send(harness: Harness) -> None:
    """Страховка тестового помощника: его конверты обязаны проходить настоящую схему."""
    for event in STAGES:
        ErpEventEnvelope.model_validate(envelope_for(event, 1))
