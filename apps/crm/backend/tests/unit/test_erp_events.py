"""Unit-тесты приёмника и обработчика событий ERP (M3-CRM-04, CONTRACTS §3, ADR-0022).

Проверка подписи HMAC-SHA256, валидация конверта, идемпотентность по X-Event-Id,
обработка исходов сделок (won/lost), индекс документов, заметки и уведомления.
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import errors
from app.api.deps import get_container
from app.api.v1.integrations import router as integrations_router
from app.config import Settings
from app.domain.errors import AuthError, ConflictError, Reason
from app.models.auth import User
from app.models.clients import Client, Document
from app.models.deals import Deal
from app.models.integrations import ErpIncomingEvent
from app.models.leads import Lead, LeadNote, TelegramIdentity
from app.schemas.erp_events import ErpEventEnvelope
from app.security.secrets_store import ERP_WEBHOOK_SECRET, SecretsStore
from app.services.erp_events import ErpEventsService, verify_signature

SECRET = "erp-webhook-secret-xyz-42"


def _sign(secret: str, body: bytes) -> str:
    hex_digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={hex_digest}"


def _sample_envelope(
    event: str = "deal.stage_changed",
    client_id: int = 101,
    company_id: int = 202,
    deal_stage: str = "quoting",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if payload is None:
        payload = {"from": "request", "to": deal_stage, "reason": "КП готовится"}
    return {
        "version": 1,
        "event": event,
        "occurred_at": datetime.now(UTC).isoformat(),
        "erp_company_id": company_id,
        "crm_client_id": client_id,
        "deal": {
            "erp_deal_id": 9001,
            "number": "DL-9001",
            "title": "Поставка осей РУ1Ш",
            "stage": deal_stage,
            "amount": "15000000.00",
            "currency": "UZS",
        },
        "actor": {"type": "system", "name": "ERP Auto"},
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# 1. Проверка HMAC-SHA256 подписи
# ---------------------------------------------------------------------------


def test_verify_signature_valid() -> None:
    body = b'{"hello": "world"}'
    sig = _sign(SECRET, body)
    assert verify_signature(SECRET, body, sig) is True


def test_verify_signature_tampered_body() -> None:
    body = b'{"hello": "world"}'
    sig = _sign(SECRET, body)
    assert verify_signature(SECRET, b'{"hello": "tampered"}', sig) is False


def test_verify_signature_wrong_secret() -> None:
    body = b'{"hello": "world"}'
    sig = _sign(SECRET, body)
    assert verify_signature("wrong-secret", body, sig) is False


@pytest.mark.parametrize(
    ("sec", "head"),
    [
        ("", "sha256=abcdef"),
        (SECRET, None),
        (SECRET, ""),
        (SECRET, "md5=abcdef"),
        (SECRET, "invalid_prefix_abcdef"),
    ],
)
def test_verify_signature_invalid_formats(sec: str, head: str | None) -> None:
    assert verify_signature(sec, b"test", head) is False


# ---------------------------------------------------------------------------
# 2. Схемы событий (19 типов)
# ---------------------------------------------------------------------------


def test_envelope_schema_validation() -> None:
    data = _sample_envelope()
    envelope = ErpEventEnvelope.model_validate(data)
    assert envelope.version == 1
    assert envelope.event == "deal.stage_changed"
    assert envelope.deal is not None
    assert envelope.deal.erp_deal_id == 9001
    assert envelope.actor.type == "system"


@pytest.mark.parametrize(
    ("event", "payload_dict"),
    [
        ("request.created", {"source": "cabinet", "erp_request_id": 1, "summary": "Тест"}),
        ("deal.stage_changed", {"from": "request", "to": "quoting"}),
        ("quote.sent", {"erp_quote_id": 2, "version": 1, "public_url": "https://erp/q/2"}),
        ("quote.viewed", {"erp_quote_id": 2, "version": 1}),
        ("quote.accepted", {"erp_quote_id": 2, "version": 1}),
        ("quote.rejected", {"erp_quote_id": 2, "version": 1, "reason": "Дорого"}),
        ("contract.signed", {"erp_contract_id": 3, "number": "C-01", "by": "both"}),
        (
            "invoice.issued",
            {
                "erp_invoice_id": 4,
                "number": "INV-01",
                "amount": "1000.00",
                "currency": "UZS",
                "due_date": "2026-10-30",
            },
        ),
        (
            "invoice.paid",
            {
                "erp_invoice_id": 4,
                "number": "INV-01",
                "amount": "1000.00",
                "currency": "UZS",
                "due_date": "2026-10-30",
            },
        ),
        (
            "invoice.overdue",
            {
                "erp_invoice_id": 4,
                "number": "INV-01",
                "amount": "1000.00",
                "currency": "UZS",
                "due_date": "2026-10-30",
            },
        ),
        ("delivery.status_changed", {"line_summary": "Колеса", "status": "shipped"}),
        ("delivery.eta_changed", {"line_summary": "Колеса", "status": "in_transit"}),
        ("act.issued", {"erp_act_id": 5, "number": "ACT-01"}),
        ("act.accepted", {"erp_act_id": 5, "number": "ACT-01"}),
        ("act.returned", {"erp_act_id": 5, "number": "ACT-01", "reason": "Брак"}),
        ("deal.won", {"amount": "15000000.00", "currency": "UZS"}),
        ("deal.lost", {"amount": "15000000.00", "currency": "UZS", "lost_reason": "Конкурент"}),
        ("document.created", {"erp_document_id": 6, "kind": "invoice", "number": "INV-01"}),
        ("invite.sent", {"channels": ["telegram"]}),
    ],
)
def test_all_19_events_parse(event: str, payload_dict: dict[str, Any]) -> None:
    env_data = _sample_envelope(event=event, payload=payload_dict)
    envelope = ErpEventEnvelope.model_validate(env_data)
    assert envelope.event == event


# ---------------------------------------------------------------------------
# 3. Сервис ErpEventsService (приём вебхука и идемпотентность)
# ---------------------------------------------------------------------------


class _DummyStore(SecretsStore):
    def __init__(self, webhook_secret: str | None = None) -> None:
        super().__init__(None, None)  # type: ignore[arg-type]
        self._secret = webhook_secret

    @property
    def enabled(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        if key == ERP_WEBHOOK_SECRET:
            return self._secret
        return None


class _DummySettingsService:
    async def get(self) -> Any:
        return SimpleNamespace(integrations=SimpleNamespace(erp_base_url="https://erp.internal"))


class _MockSession:
    def __init__(self, existing_events: dict[str, ErpIncomingEvent] | None = None) -> None:
        self.events = existing_events if existing_events is not None else {}
        self.added: list[Any] = []

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def get(self, model: type[Any], pk: Any, **_: Any) -> Any:
        if model is ErpIncomingEvent:
            return self.events.get(str(pk))
        return None

    def add(self, instance: Any) -> None:
        self.added.append(instance)
        if isinstance(instance, ErpIncomingEvent):
            self.events[instance.event_id] = instance


def _mock_session_factory(session: Any) -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[Any]:
        yield session

    return factory


async def _no_bot() -> None:
    return None


@pytest.mark.asyncio
async def test_receive_event_secret_missing() -> None:
    store = _DummyStore(None)
    config = Settings(erp_webhook_secret="")
    session = _MockSession()
    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService(),  # type: ignore[arg-type]
        store,
        config,
        _no_bot,
    )

    envelope = ErpEventEnvelope.model_validate(_sample_envelope())
    with pytest.raises(ConflictError) as exc_info:
        await service.receive_event("e-1", envelope.event, None, b"{}", envelope)
    assert exc_info.value.details["reason"] == Reason.ERP_NOT_CONFIGURED.value


@pytest.mark.asyncio
async def test_receive_event_invalid_signature() -> None:
    store = _DummyStore(SECRET)
    config = Settings(erp_webhook_secret=SECRET)
    session = _MockSession()
    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService(),  # type: ignore[arg-type]
        store,
        config,
        _no_bot,
    )

    envelope = ErpEventEnvelope.model_validate(_sample_envelope())
    with pytest.raises(AuthError):
        await service.receive_event("e-1", envelope.event, "sha256=bad", b"{}", envelope)


@pytest.mark.asyncio
async def test_receive_event_new_and_duplicate() -> None:
    store = _DummyStore(SECRET)
    config = Settings(erp_webhook_secret=SECRET)
    session = _MockSession()
    enqueued: list[str] = []

    async def fake_enqueue(eid: str) -> int:
        enqueued.append(eid)
        return 1

    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService(),  # type: ignore[arg-type]
        store,
        config,
        _no_bot,
        enqueue_task=fake_enqueue,
    )

    raw_body = json.dumps(_sample_envelope()).encode("utf-8")
    sig = _sign(SECRET, raw_body)
    envelope = ErpEventEnvelope.model_validate(json.loads(raw_body))

    # Первый вызов — создание и постановка в очередь
    dup, status = await service.receive_event("evt-100", envelope.event, sig, raw_body, envelope)
    assert dup is False
    assert status == "enqueued"
    assert enqueued == ["evt-100"]
    assert "evt-100" in session.events
    assert session.events["evt-100"].status == "received"

    # Второй вызов с тем же event_id — возврат duplicate без повторной очереди
    dup2, status2 = await service.receive_event("evt-100", envelope.event, sig, raw_body, envelope)
    assert dup2 is True
    assert status2 == "duplicate"
    assert len(enqueued) == 1


# ---------------------------------------------------------------------------
# 4. API Эндпоинт POST /api/v1/integrations/erp/events
# ---------------------------------------------------------------------------


class _FakeEventsService:
    def __init__(self, secret: str | None = SECRET) -> None:
        self.secret = secret
        self.received: dict[str, dict[str, Any]] = {}

    async def get_webhook_secret(self) -> str:
        return self.secret or ""

    async def receive_event(
        self,
        event_id: str,
        event_type: str,
        signature: str | None,
        raw_body: bytes,
        envelope: ErpEventEnvelope,
    ) -> tuple[bool, str]:
        if not self.secret:
            raise ConflictError(
                "erp webhook secret is not configured", reason=Reason.ERP_NOT_CONFIGURED
            )
        if not verify_signature(self.secret, raw_body, signature):
            raise AuthError("invalid webhook signature")
        if event_id in self.received:
            return True, "duplicate"
        self.received[event_id] = envelope.model_dump()
        return False, "enqueued"


@pytest.fixture
def api_client() -> Iterator[tuple[TestClient, _FakeEventsService]]:
    app = FastAPI()
    errors.install(app)
    app.include_router(integrations_router)
    fake_svc = _FakeEventsService(SECRET)
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(erp_events_service=fake_svc)
    with TestClient(app) as test_client:
        yield test_client, fake_svc


def test_api_missing_headers(api_client: tuple[TestClient, _FakeEventsService]) -> None:
    client, _ = api_client
    res = client.post("/api/v1/integrations/erp/events", content=b"{}")
    assert res.status_code == 422


def test_api_invalid_event_id_not_uuid(api_client: tuple[TestClient, _FakeEventsService]) -> None:
    client, _ = api_client
    res = client.post(
        "/api/v1/integrations/erp/events",
        headers={
            "X-Event-Id": "not-a-uuid",
            "X-Event-Type": "deal.stage_changed",
            "X-Timestamp": "2026-10-16T12:00:00Z",
        },
        content=b"{}",
    )
    assert res.status_code == 422
    assert res.json()["details"]["field"] == "X-Event-Id"


def test_api_mismatched_event_type(api_client: tuple[TestClient, _FakeEventsService]) -> None:
    client, _ = api_client
    envelope_data = _sample_envelope(event="deal.stage_changed")
    raw = json.dumps(envelope_data).encode("utf-8")
    eid = str(uuid.uuid4())
    sig = _sign(SECRET, raw)
    res = client.post(
        "/api/v1/integrations/erp/events",
        headers={
            "X-Event-Id": eid,
            "X-Event-Type": "quote.sent",  # не совпадает с deal.stage_changed
            "X-Timestamp": "2026-10-16T12:00:00Z",
            "X-Signature": sig,
        },
        content=raw,
    )
    assert res.status_code == 422
    assert res.json()["details"]["field"] == "X-Event-Type"


def test_api_invalid_signature(api_client: tuple[TestClient, _FakeEventsService]) -> None:
    client, _ = api_client
    envelope_data = _sample_envelope(event="deal.stage_changed")
    raw = json.dumps(envelope_data).encode("utf-8")
    eid = str(uuid.uuid4())
    res = client.post(
        "/api/v1/integrations/erp/events",
        headers={
            "X-Event-Id": eid,
            "X-Event-Type": "deal.stage_changed",
            "X-Timestamp": "2026-10-16T12:00:00Z",
            "X-Signature": "sha256=wrong",
        },
        content=raw,
    )
    assert res.status_code == 401


def test_api_success_and_idempotency(api_client: tuple[TestClient, _FakeEventsService]) -> None:
    client, fake_svc = api_client
    envelope_data = _sample_envelope(event="deal.stage_changed")
    raw = json.dumps(envelope_data).encode("utf-8")
    eid = str(uuid.uuid4())
    sig = _sign(SECRET, raw)

    headers = {
        "X-Event-Id": eid,
        "X-Event-Type": "deal.stage_changed",
        "X-Timestamp": "2026-10-16T12:00:00Z",
        "X-Signature": sig,
    }

    # Первый запрос -> duplicate: false
    res = client.post("/api/v1/integrations/erp/events", headers=headers, content=raw)
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "duplicate": False}
    assert eid in fake_svc.received

    # Повторный запрос -> duplicate: true
    res2 = client.post("/api/v1/integrations/erp/events", headers=headers, content=raw)
    assert res2.status_code == 200
    assert res2.json() == {"status": "ok", "duplicate": True}


# ---------------------------------------------------------------------------
# 5. Обработка событий в процессе (process_event)
# ---------------------------------------------------------------------------


class _StatefulSession:
    def __init__(
        self,
        events: dict[str, ErpIncomingEvent],
        clients: dict[int, Client],
        leads: dict[int, Lead],
        deals: dict[int, Deal],
        identities: list[TelegramIdentity],
        users: dict[int, User],
    ) -> None:
        self.events = events
        self.clients = clients
        self.leads = leads
        self.deals = deals
        self.identities = identities
        self.users = users
        self.added: list[Any] = []
        self._next_id = 5000

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def flush(self) -> None:
        for item in self.added:
            if getattr(item, "id", None) is None:
                self._next_id += 1
                item.id = self._next_id

    async def execute(self, stmt: Any) -> Any:
        return object()

    async def get(self, model: type[Any], pk: Any, **_: Any) -> Any:
        if model is ErpIncomingEvent:
            return self.events.get(str(pk))
        if model is Client:
            return self.clients.get(int(pk))
        if model is Lead:
            return self.leads.get(int(pk))
        if model is Deal:
            return self.deals.get(int(pk))
        if model is User:
            return self.users.get(int(pk))
        return None

    async def scalar(self, stmt: Any) -> Any:
        # Эмуляция поиска по stmt
        sql_str = str(stmt).lower()
        if "from deals" in sql_str:
            for d in self.deals.values():
                return d
            return None
        if "from leads" in sql_str:
            for lead_obj in self.leads.values():
                return lead_obj
            return None
        return None

    async def scalars(self, stmt: Any) -> Any:
        sql_str = str(stmt).lower()
        if "from telegram_identities" in sql_str:
            result = [i.tg_user_id for i in self.identities if not i.is_blocked]
            return SimpleNamespace(all=lambda: result)
        return SimpleNamespace(all=lambda: [])

    def add(self, instance: Any) -> None:
        self.added.append(instance)
        if isinstance(instance, Deal):
            if instance.id is None:
                self._next_id += 1
                instance.id = self._next_id
            self.deals[instance.id] = instance
        elif isinstance(instance, ErpIncomingEvent):
            self.events[instance.event_id] = instance


class _FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []

    async def send_message(
        self, chat_id: int, text: str, reply_markup: Any = None, **kwargs: Any
    ) -> Any:
        self.sent_messages.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return object()


@pytest.mark.asyncio
async def test_process_event_deal_lifecycle() -> None:
    client = Client(id=101, name="ООО Тест", inn="1234567890", erp_company_id=202)
    lead = Lead(id=501, client_id=101, display_name="Лид на колеса")
    deal = Deal(
        id=701,
        client_id=101,
        lead_id=501,
        erp_deal_id=9001,
        title="Поставка осей",
        amount=Decimal("15000000.00"),
        currency="UZS",
        stage="open",
        external_stage="quoting",
    )
    tg_identity = TelegramIdentity(
        id=1, tg_user_id=777, client_id=101, lead_id=501, is_blocked=False
    )
    user = User(id=1, email="manager@railtech.uz", full_name="Менеджер")

    env_data = _sample_envelope(event="deal.won", client_id=101, company_id=202, deal_stage="won")
    env_data["payload"] = {"amount": "15000000.00", "currency": "UZS"}
    incoming_row = ErpIncomingEvent(
        event_id="evt-won-1",
        event_type="deal.won",
        erp_company_id=202,
        crm_client_id=101,
        payload=env_data,
        status="received",
    )

    events_map = {"evt-won-1": incoming_row}
    clients_map = {101: client}
    leads_map = {501: lead}
    deals_map = {701: deal}
    session = _StatefulSession(
        events_map, clients_map, leads_map, deals_map, [tg_identity], {1: user}
    )

    bot = _FakeBot()

    async def get_bot() -> Any:
        return bot

    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService(),  # type: ignore[arg-type]
        _DummyStore(SECRET),
        Settings(erp_webhook_secret=SECRET),
        get_bot,
    )

    res = await service.process_event("evt-won-1")
    assert res is True
    assert incoming_row.status == "processed"
    assert incoming_row.processed_at is not None

    # Проверяем обновление стадии сделки через plan_erp_outcome
    assert deal.stage == "won"
    assert deal.external_stage == "won"
    assert deal.closed_at is not None

    # Проверяем добавление заметки в ленту
    notes = [item for item in session.added if isinstance(item, LeadNote)]
    assert len(notes) == 1
    assert "выиграна" in notes[0].text or "won" in notes[0].text.lower()
    assert notes[0].visible_to_bot is False

    # Для deal.won сообщение клиенту не отправляется (только лента и статус сделки)
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_process_event_telegram_notification_on_quote_sent() -> None:
    client = Client(id=101, name="ООО Тест", inn="1234567890", erp_company_id=202)
    lead = Lead(id=501, client_id=101, display_name="Лид")
    deal = Deal(id=701, client_id=101, lead_id=501, erp_deal_id=9001, title="Оси")
    tg_identity = TelegramIdentity(
        id=1, tg_user_id=777, client_id=101, lead_id=501, is_blocked=False
    )

    quote_payload = {
        "erp_quote_id": 42,
        "version": 1,
        "public_url": "https://cabinet.railtech.uz/quotes/42",
        "total": "15000000.00",
        "currency": "UZS",
    }
    env_data = _sample_envelope(
        event="quote.sent",
        client_id=101,
        company_id=202,
        deal_stage="quote_sent",
        payload=quote_payload,
    )
    incoming_row = ErpIncomingEvent(
        event_id="evt-quote-1",
        event_type="quote.sent",
        erp_company_id=202,
        crm_client_id=101,
        payload=env_data,
        status="received",
    )

    events_map = {"evt-quote-1": incoming_row}
    session = _StatefulSession(
        events_map, {101: client}, {501: lead}, {701: deal}, [tg_identity], {}
    )

    bot = _FakeBot()

    async def get_bot() -> Any:
        return bot

    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService(),  # type: ignore[arg-type]
        _DummyStore(SECRET),
        Settings(erp_webhook_secret=SECRET),
        get_bot,
    )

    res = await service.process_event("evt-quote-1")
    assert res is True
    assert incoming_row.status == "processed"
    assert deal.external_stage == "quote_sent"

    # Проверяем отправку сообщения клиенту в Telegram с кнопкой ссылки на КП
    assert len(bot.sent_messages) == 1
    assert bot.sent_messages[0]["chat_id"] == 777
    assert "коммерческое предложение" in bot.sent_messages[0]["text"]
    assert bot.sent_messages[0]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_process_event_document_created() -> None:
    client = Client(id=101, name="ООО Тест", erp_company_id=202)
    lead = Lead(id=501, client_id=101, display_name="Лид")
    deal = Deal(id=701, client_id=101, lead_id=501, erp_deal_id=9001)

    doc_payload = {"erp_document_id": 88, "kind": "invoice", "number": "INV-2026-001"}
    env_data = _sample_envelope(
        event="document.created",
        client_id=101,
        company_id=202,
        deal_stage="invoiced",
        payload=doc_payload,
    )
    incoming_row = ErpIncomingEvent(
        event_id="evt-doc-1",
        event_type="document.created",
        erp_company_id=202,
        crm_client_id=101,
        payload=env_data,
        status="received",
    )

    events_map = {"evt-doc-1": incoming_row}
    session = _StatefulSession(events_map, {101: client}, {501: lead}, {701: deal}, [], {})

    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService(),  # type: ignore[arg-type]
        _DummyStore(SECRET),
        Settings(erp_webhook_secret=SECRET),
        _no_bot,
    )

    res = await service.process_event("evt-doc-1")
    assert res is True
    assert incoming_row.status == "processed"

    # Проверяем добавление Document в индекс
    docs = [item for item in session.added if isinstance(item, Document)]
    assert len(docs) == 1
    assert docs[0].client_id == 101
    assert docs[0].type == "invoice"
    assert docs[0].extract_status == "skipped"
    assert "INV-2026-001" in docs[0].title


@pytest.mark.asyncio
async def test_process_event_client_not_found() -> None:
    env_data = _sample_envelope(client_id=99999)  # несуществующий клиент
    incoming_row = ErpIncomingEvent(
        event_id="evt-missing-client",
        event_type="deal.stage_changed",
        erp_company_id=202,
        crm_client_id=99999,
        payload=env_data,
        status="received",
    )

    session = _StatefulSession({"evt-missing-client": incoming_row}, {}, {}, {}, [], {})
    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService(),  # type: ignore[arg-type]
        _DummyStore(SECRET),
        Settings(erp_webhook_secret=SECRET),
        _no_bot,
    )

    res = await service.process_event("evt-missing-client")
    assert res is False
    assert incoming_row.status == "failed"
    assert "not found" in (incoming_row.error or "")


@pytest.mark.asyncio
async def test_process_event_already_processed() -> None:
    incoming_row = ErpIncomingEvent(
        event_id="evt-done",
        event_type="deal.stage_changed",
        erp_company_id=202,
        crm_client_id=101,
        payload=_sample_envelope(),
        status="processed",
    )
    session = _StatefulSession({"evt-done": incoming_row}, {}, {}, {}, [], {})
    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService(),  # type: ignore[arg-type]
        _DummyStore(SECRET),
        Settings(erp_webhook_secret=SECRET),
        _no_bot,
    )

    res = await service.process_event("evt-done")
    assert res is True
