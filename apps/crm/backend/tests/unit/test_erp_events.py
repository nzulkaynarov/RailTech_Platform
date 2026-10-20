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
from pydantic import ValidationError

from app.api import errors
from app.api.deps import get_container
from app.api.v1.integrations import router as integrations_router
from app.config import Settings
from app.domain.errors import AuthError, ConflictError, Reason, ValidationFailedError
from app.models.auth import User
from app.models.clients import Client, Document
from app.models.deals import Deal
from app.models.integrations import ErpIncomingEvent
from app.models.leads import Lead, LeadNote, TelegramIdentity
from app.schemas.erp_events import parse_event
from app.schemas.settings import AppSettings, CompanySettings, IntegrationsSettings
from app.security.secrets_store import (
    ERP_WEBHOOK_SECRET,
    ERP_WEBHOOK_SECRET_PREVIOUS,
    SecretsStore,
)
from app.services.erp_events import ErpEventsService, verify_signature, verify_signature_any

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
    envelope = parse_event(data)
    assert envelope.version == 1
    assert envelope.event == "deal.stage_changed"
    assert envelope.deal is not None
    assert envelope.deal.erp_deal_id == 9001
    assert envelope.actor.type == "system"


def test_envelope_accepts_deal_without_sent_quote() -> None:
    """FIX-29: `deal.amount` = null, пока КП клиенту не отправлялось (черновик не утекает в CRM)."""
    data = _sample_envelope()
    data["deal"]["amount"] = None
    envelope = parse_event(data)
    assert envelope.deal is not None
    assert envelope.deal.amount is None


def test_deal_amount_helper_keeps_none() -> None:
    from app.services.erp_events import _deal_amount

    assert _deal_amount(None) is None
    assert _deal_amount("15000000.00") == Decimal("15000000.00")


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
        (
            "delivery.line_accepted",
            {
                "line_no": 1,
                "title": "Колёса",
                "status": "accepted",
                "decided_at": "2026-10-20T10:00:00+05:00",
            },
        ),
        (
            "delivery.line_disputed",
            {
                "line_no": 2,
                "title": "Оси",
                "status": "disputed",
                "remark": "Брак",
                "decided_at": "2026-10-20T10:00:00+05:00",
            },
        ),
    ],
)
def test_all_events_parse(event: str, payload_dict: dict[str, Any]) -> None:
    env_data = _sample_envelope(event=event, payload=payload_dict)
    if event.startswith("delivery.line_"):
        env_data["actor"] = {"type": "client", "name": "Азамат Каримов"}
    envelope = parse_event(env_data)
    assert envelope.event == event


# ---------------------------------------------------------------------------
# 3. Сервис ErpEventsService (приём вебхука и идемпотентность)
# ---------------------------------------------------------------------------


class _DummyStore(SecretsStore):
    def __init__(self, webhook_secret: str | None = None, previous: str | None = None) -> None:
        super().__init__(None, None)  # type: ignore[arg-type]
        self._secret = webhook_secret
        self._previous = previous

    @property
    def enabled(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        if key == ERP_WEBHOOK_SECRET:
            return self._secret
        if key == ERP_WEBHOOK_SECRET_PREVIOUS:
            return self._previous
        return None


class _DummySettingsService:
    def __init__(self, cabinet_url: str = "") -> None:
        self._cabinet_url = cabinet_url

    async def get(self) -> AppSettings:
        return AppSettings(
            integrations=IntegrationsSettings(erp_base_url="https://erp.internal"),
            company=CompanySettings(cabinet_url=self._cabinet_url),
        )


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

    async def scalar(self, statement: Any) -> Any:
        """Событие с тем же `body_sha256` (поиск повтора тела): хеш — из параметров запроса."""
        wanted = statement.compile().params.get("body_sha256_1")
        for event in self.events.values():
            if event.body_sha256 is not None and event.body_sha256 == wanted:
                return event.event_id
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


def _receiver(
    secret: str | None = SECRET,
    session: _MockSession | None = None,
    enqueued: list[str] | None = None,
    enqueue_error: Exception | None = None,
) -> tuple[ErpEventsService, _MockSession]:
    session = session if session is not None else _MockSession()

    async def enqueue(event_id: str) -> int:
        if enqueue_error is not None:
            raise enqueue_error
        if enqueued is not None:
            enqueued.append(event_id)
        return 1

    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService(),  # type: ignore[arg-type]
        _DummyStore(secret),
        Settings(erp_webhook_secret=secret or ""),
        _no_bot,
        enqueue_task=enqueue,
    )
    return service, session


def _signed(body: dict[str, Any] | bytes) -> tuple[bytes, str]:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    return raw, _sign(SECRET, raw)


@pytest.mark.asyncio
async def test_receive_event_secret_missing() -> None:
    service, _ = _receiver(secret=None)
    with pytest.raises(ConflictError) as exc_info:
        await service.receive_event(str(uuid.uuid4()), "deal.stage_changed", None, b"{}")
    assert exc_info.value.details["reason"] == Reason.ERP_NOT_CONFIGURED.value


@pytest.mark.asyncio
async def test_signature_is_checked_before_the_body_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIX-33: неподписанный запрос не заставляет CRM разбирать тело и ничего не записывает."""

    def boom(*_: Any, **__: Any) -> Any:
        raise AssertionError("body parsed before the signature was verified")

    monkeypatch.setattr("app.services.erp_events._parse_body", boom)
    service, session = _receiver()

    for body in (b"{}", b"not json at all", json.dumps(_sample_envelope()).encode()):
        with pytest.raises(AuthError):
            await service.receive_event(str(uuid.uuid4()), "deal.stage_changed", "sha256=bad", body)
        with pytest.raises(AuthError):
            await service.receive_event(str(uuid.uuid4()), "deal.stage_changed", None, body)
    assert session.events == {}


@pytest.mark.asyncio
async def test_receive_event_new_and_duplicate() -> None:
    enqueued: list[str] = []
    service, session = _receiver(enqueued=enqueued)
    event_id = str(uuid.uuid4())
    raw, sig = _signed(_sample_envelope())

    # Первый вызов — создание и постановка в очередь
    assert await service.receive_event(event_id, "deal.stage_changed", sig, raw) == (
        False,
        "enqueued",
    )
    assert enqueued == [event_id]
    assert session.events[event_id].status == "received"

    # Второй вызов с тем же event_id — duplicate без повторной очереди
    assert await service.receive_event(event_id, "deal.stage_changed", sig, raw) == (
        True,
        "duplicate",
    )
    assert len(enqueued) == 1


@pytest.mark.asyncio
async def test_a_failed_enqueue_keeps_the_row_and_still_answers_200() -> None:
    """FIX-33 (I-10): сбой очереди не теряет событие; строка `received` ждёт сборщика."""
    service, session = _receiver(enqueue_error=OSError("queue down"))
    event_id = str(uuid.uuid4())
    raw, sig = _signed(_sample_envelope())

    assert await service.receive_event(event_id, "deal.stage_changed", sig, raw) == (
        False,
        "stored",
    )
    assert session.events[event_id].status == "received"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "header", "reason"),
    [
        (b"this is not json", "deal.stage_changed", "invalid JSON"),
        (json.dumps([1, 2]).encode(), "deal.stage_changed", "not an object"),
        (json.dumps(_sample_envelope()).encode(), "quote.sent", "header mismatch"),
        (
            json.dumps({**_sample_envelope(), "version": 2}).encode(),
            "deal.stage_changed",
            "invalid event envelope",
        ),
        (
            json.dumps(
                {**_sample_envelope(), "payload": {"from": "request", "to": "nowhere"}}
            ).encode(),
            "deal.stage_changed",
            "invalid event envelope",
        ),
        (
            json.dumps({**_sample_envelope(), "deal": None}).encode(),
            "deal.stage_changed",
            "invalid event envelope",
        ),
    ],
)
async def test_a_body_we_cannot_accept_is_recorded_as_rejected_and_answered_200(
    body: bytes, header: str, reason: str
) -> None:
    """Подпись верна, тело — нет: ретраи ERP не помогут, поэтому 200 и запись для центра."""
    enqueued: list[str] = []
    service, session = _receiver(enqueued=enqueued)
    event_id = str(uuid.uuid4())
    raw, sig = _signed(body)

    assert await service.receive_event(event_id, header, sig, raw) == (False, "rejected")
    row = session.events[event_id]
    assert row.status == "rejected"
    assert reason in (row.error or "")
    assert row.processed_at is not None
    assert enqueued == []


@pytest.mark.asyncio
async def test_an_unknown_event_type_is_skipped_with_200_not_422() -> None:
    """FIX-35: событие более новой ERP записано как «пропущено» — не 422, не ретраи, не красное."""
    enqueued: list[str] = []
    service, session = _receiver(enqueued=enqueued)
    event_id = str(uuid.uuid4())
    raw, sig = _signed({**_sample_envelope(), "event": "warehouse.exploded"})

    assert await service.receive_event(event_id, "warehouse.exploded", sig, raw) == (
        False,
        "skipped",
    )
    row = session.events[event_id]
    assert row.status == "skipped"
    assert row.error == "unknown event type: warehouse.exploded"
    assert row.processed_at is not None
    assert (row.erp_company_id, row.crm_client_id) == (202, 101)
    assert enqueued == []


@pytest.mark.asyncio
async def test_the_reader_is_tolerant_to_new_fields_everywhere() -> None:
    """FIX-35: лишнее поле в конверте, в `deal`, `actor` и в теле не даёт отказа."""
    data = _sample_envelope()
    data["brand_new_field"] = 1
    data["deal"]["brand_new_field"] = 1
    data["actor"]["brand_new_field"] = 1
    data["payload"]["brand_new_field"] = 1
    enqueued: list[str] = []
    service, session = _receiver(enqueued=enqueued)
    event_id = str(uuid.uuid4())
    raw, sig = _signed(data)

    assert await service.receive_event(event_id, "deal.stage_changed", sig, raw) == (
        False,
        "enqueued",
    )
    assert session.events[event_id].status == "received"
    assert enqueued == [event_id]


@pytest.mark.asyncio
async def test_a_header_that_disagrees_with_the_body_is_rejected_not_422() -> None:
    service, session = _receiver()
    event_id = str(uuid.uuid4())
    raw, sig = _signed(_sample_envelope(event="deal.stage_changed"))

    assert await service.receive_event(event_id, "quote.sent", sig, raw) == (False, "rejected")
    assert "header mismatch" in (session.events[event_id].error or "")


@pytest.mark.asyncio
async def test_headers_are_validated_only_after_the_signature() -> None:
    service, _ = _receiver()
    raw, sig = _signed(_sample_envelope())

    with pytest.raises(ValidationFailedError) as bad_id:
        await service.receive_event("not-a-uuid", "deal.stage_changed", sig, raw)
    assert bad_id.value.details["field"] == "X-Event-Id"
    with pytest.raises(ValidationFailedError) as no_type:
        await service.receive_event(str(uuid.uuid4()), None, sig, raw)
    assert no_type.value.details["field"] == "X-Event-Type"


# ---------------------------------------------------------------------------
# 4. API Эндпоинт POST /api/v1/integrations/erp/events
# ---------------------------------------------------------------------------

URL = "/api/v1/integrations/erp/events"


@pytest.fixture
def api_client() -> Iterator[tuple[TestClient, _MockSession]]:
    app = FastAPI()
    errors.install(app)
    app.include_router(integrations_router)
    service, session = _receiver()
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(erp_events_service=service)
    with TestClient(app) as test_client:
        yield test_client, session


def _headers(event_id: str, event_type: str, signature: str | None) -> dict[str, str]:
    headers = {
        "X-Event-Id": event_id,
        "X-Event-Type": event_type,
        "X-Timestamp": "2026-10-16T12:00:00Z",
    }
    if signature is not None:
        headers["X-Signature"] = signature
    return headers


@pytest.mark.parametrize("body", [b"{}", b"garbage", b""])
def test_api_unsigned_request_is_401_whatever_the_body_and_headers(
    api_client: tuple[TestClient, _MockSession], body: bytes
) -> None:
    client, session = api_client
    assert client.post(URL, content=body).status_code == 401  # даже без заголовков
    res = client.post(URL, headers=_headers("not-a-uuid", "x", None), content=body)
    assert res.status_code == 401
    assert session.events == {}


def test_api_invalid_event_id_not_uuid(api_client: tuple[TestClient, _MockSession]) -> None:
    client, _ = api_client
    raw, sig = _signed(_sample_envelope())
    res = client.post(URL, headers=_headers("not-a-uuid", "deal.stage_changed", sig), content=raw)
    assert res.status_code == 422
    assert res.json()["details"]["field"] == "X-Event-Id"


def test_api_mismatched_event_type_is_200_and_recorded_as_rejected(
    api_client: tuple[TestClient, _MockSession],
) -> None:
    client, session = api_client
    raw, sig = _signed(_sample_envelope(event="deal.stage_changed"))
    eid = str(uuid.uuid4())
    res = client.post(URL, headers=_headers(eid, "quote.sent", sig), content=raw)
    assert res.status_code == 200
    assert session.events[eid].status == "rejected"


def test_api_invalid_signature(api_client: tuple[TestClient, _MockSession]) -> None:
    client, _ = api_client
    raw, _ = _signed(_sample_envelope())
    res = client.post(
        URL, headers=_headers(str(uuid.uuid4()), "deal.stage_changed", "sha256=wrong"), content=raw
    )
    assert res.status_code == 401


def test_api_success_and_idempotency(api_client: tuple[TestClient, _MockSession]) -> None:
    client, session = api_client
    raw, sig = _signed(_sample_envelope(event="deal.stage_changed"))
    eid = str(uuid.uuid4())
    headers = _headers(eid, "deal.stage_changed", sig)

    res = client.post(URL, headers=headers, content=raw)
    assert (res.status_code, res.json()) == (200, {"status": "ok", "duplicate": False})
    assert eid in session.events

    res2 = client.post(URL, headers=headers, content=raw)
    assert (res2.status_code, res2.json()) == (200, {"status": "ok", "duplicate": True})


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

    @asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        yield

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
        if "from documents" in sql_str:
            wanted = stmt.compile().params.get("erp_document_id_1")
            return next(
                (d for d in self.added if isinstance(d, Document) and d.erp_document_id == wanted),
                None,
            )
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


def _buttons(markup: Any) -> list[tuple[str, str | None]]:
    return [(row[0].text, row[0].url) for row in markup.inline_keyboard]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "text_part", "buttons"),
    [
        (
            "ru",
            "коммерческое предложение",
            [
                ("Открыть КП", "https://erp.example.com/q/42"),
                ("Кабинет", "https://cab.example.com"),
            ],
        ),
        (
            "uz",
            "tijorat taklifi",
            [
                ("Taklifni ochish", "https://erp.example.com/q/42"),
                ("Kabinet", "https://cab.example.com"),
            ],
        ),
        (
            "en",
            "commercial proposal",
            [
                ("Open the quote", "https://erp.example.com/q/42"),
                ("Cabinet", "https://cab.example.com"),
            ],
        ),
    ],
)
async def test_client_message_follows_lead_language_with_cabinet_button(
    language: str, text_part: str, buttons: list[tuple[str, str]]
) -> None:
    """I-8: текст из settings.texts на языке лида, кнопки «Открыть КП» и «Кабинет»."""
    client = Client(id=101, name="ООО Тест", erp_company_id=202)
    lead = Lead(id=501, client_id=101, display_name="Лид", language=language)
    deal = Deal(id=701, client_id=101, lead_id=501, erp_deal_id=9001, title="Оси")
    tg = TelegramIdentity(id=1, tg_user_id=777, client_id=101, lead_id=501, is_blocked=False)
    env = _sample_envelope(
        event="quote.sent",
        deal_stage="quote_sent",
        payload={"erp_quote_id": 42, "version": 1, "public_url": "https://erp.example.com/q/42"},
    )
    row = ErpIncomingEvent(
        event_id="evt-lang",
        event_type="quote.sent",
        erp_company_id=202,
        crm_client_id=101,
        payload=env,
        status="received",
    )
    session = _StatefulSession({"evt-lang": row}, {101: client}, {501: lead}, {701: deal}, [tg], {})
    bot = _FakeBot()

    async def get_bot() -> Any:
        return bot

    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService("https://cab.example.com"),  # type: ignore[arg-type]
        _DummyStore(SECRET),
        Settings(erp_webhook_secret=SECRET),
        get_bot,
    )

    assert await service.process_event("evt-lang") is True
    assert len(bot.sent_messages) == 1
    assert text_part in bot.sent_messages[0]["text"]
    assert _buttons(bot.sent_messages[0]["reply_markup"]) == buttons


@pytest.mark.asyncio
async def test_no_cabinet_button_when_cabinet_url_is_empty() -> None:
    client = Client(id=101, name="ООО Тест", erp_company_id=202)
    lead = Lead(id=501, client_id=101, display_name="Лид", language="ru")
    deal = Deal(id=701, client_id=101, lead_id=501, erp_deal_id=9001, title="Оси")
    tg = TelegramIdentity(id=1, tg_user_id=777, client_id=101, lead_id=501, is_blocked=False)
    env = _sample_envelope(
        event="invoice.paid",
        deal_stage="paid",
        payload={
            "erp_invoice_id": 4,
            "number": "INV-01",
            "amount": "100.00",
            "currency": "UZS",
            "due_date": "2026-10-30",
        },
    )
    row = ErpIncomingEvent(
        event_id="evt-nocab",
        event_type="invoice.paid",
        erp_company_id=202,
        crm_client_id=101,
        payload=env,
        status="received",
    )
    session = _StatefulSession(
        {"evt-nocab": row}, {101: client}, {501: lead}, {701: deal}, [tg], {}
    )
    bot = _FakeBot()

    async def get_bot() -> Any:
        return bot

    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService(""),  # type: ignore[arg-type]
        _DummyStore(SECRET),
        Settings(erp_webhook_secret=SECRET),
        get_bot,
    )

    assert await service.process_event("evt-nocab") is True
    assert "INV-01" in bot.sent_messages[0]["text"]
    assert bot.sent_messages[0]["reply_markup"] is None  # сообщение не ломается без адреса


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


# ---------------------------------------------------------------------------
# 6. Приёмка и замечания по строкам поставки (FIX-37)
# ---------------------------------------------------------------------------


def _line_envelope(event: str, **overrides: Any) -> dict[str, Any]:
    status = "accepted" if event == "delivery.line_accepted" else "disputed"
    payload: dict[str, Any] = {
        "line_no": 2,
        "title": "Труба 89х4 ст20",
        "status": status,
        "decided_at": "2026-10-20T10:00:00+05:00",
    }
    if status == "disputed":
        payload["remark"] = "Часть труб с трещинами"
    env = _sample_envelope(event=event, deal_stage="fulfilment", payload=payload)
    env["actor"] = {"type": "client", "name": "Азамат Каримов"}
    env.update(overrides)
    return env


def test_delivery_line_event_requires_deal_client_actor_and_matching_payload() -> None:
    assert parse_event(_line_envelope("delivery.line_disputed")).deal is not None

    no_deal = _line_envelope("delivery.line_accepted")
    del no_deal["deal"]
    with pytest.raises(ValidationError):
        parse_event(no_deal)

    with pytest.raises(ValidationError):  # решает клиент, не сотрудник и не система
        parse_event(_line_envelope("delivery.line_accepted", actor={"type": "staff", "name": "М"}))

    no_remark = _line_envelope("delivery.line_disputed")
    del no_remark["payload"]["remark"]
    with pytest.raises(ValidationError):  # замечание при disputed обязательно
        parse_event(no_remark)

    blank_remark = _line_envelope("delivery.line_disputed")
    blank_remark["payload"]["remark"] = "   "
    with pytest.raises(ValidationError):
        parse_event(blank_remark)

    mismatch = _line_envelope("delivery.line_accepted")
    mismatch["payload"]["status"] = "disputed"
    mismatch["payload"]["remark"] = "x"
    with pytest.raises(ValidationError):  # тип события и статус строки не совпадают
        parse_event(mismatch)

    extra = _line_envelope("delivery.line_accepted")
    extra["payload"]["new_optional_field"] = "x"
    # терпимый читатель: лишнее поле принимается
    assert parse_event(extra).event == "delivery.line_accepted"

    too_long = _line_envelope("delivery.line_disputed")
    too_long["payload"]["remark"] = "x" * 2001
    with pytest.raises(ValidationError):
        parse_event(too_long)


class _StaffSession(_StatefulSession):
    """Сессия, которая знает Telegram ответственного сотрудника (запрос `User.tg_user_id`)."""

    def __init__(self, *args: Any, staff_tg_id: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._staff_tg_id = staff_tg_id

    async def scalar(self, stmt: Any) -> Any:
        if "users" in str(stmt).lower() and "from deals" not in str(stmt).lower():
            return self._staff_tg_id
        return await super().scalar(stmt)


async def _process_line_event(event: str) -> tuple[_StaffSession, _FakeBot, ErpIncomingEvent, Deal]:
    client = Client(id=101, name="ООО Тест", erp_company_id=202)
    lead = Lead(id=501, client_id=101, display_name="Лид", language="uz")
    deal = Deal(
        id=701,
        client_id=101,
        lead_id=501,
        erp_deal_id=9001,
        title="Оси",
        stage="open",
        external_stage="fulfilment",
        owner_user_id=1,
    )
    tg = TelegramIdentity(id=1, tg_user_id=777, client_id=101, lead_id=501, is_blocked=False)
    user = User(id=1, email="manager@railtech.uz", full_name="Менеджер")
    row = ErpIncomingEvent(
        event_id=f"evt-{event}",
        event_type=event,
        erp_company_id=202,
        crm_client_id=101,
        payload=_line_envelope(event),
        status="received",
    )
    session = _StaffSession(
        {row.event_id: row},
        {101: client},
        {501: lead},
        {701: deal},
        [tg],
        {1: user},
        staff_tg_id=555,
    )
    bot = _FakeBot()

    async def get_bot() -> Any:
        return bot

    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService("https://cab.example.com"),  # type: ignore[arg-type]
        _DummyStore(SECRET),
        Settings(erp_webhook_secret=SECRET),
        get_bot,
    )
    assert await service.process_event(row.event_id) is True
    return session, bot, row, deal


@pytest.mark.asyncio
async def test_line_accepted_goes_to_the_feed_and_nobody_is_messaged() -> None:
    session, bot, row, deal = await _process_line_event("delivery.line_accepted")

    assert row.status == "processed"
    notes = [item for item in session.added if isinstance(item, LeadNote)]
    assert len(notes) == 1
    assert "Азамат Каримов" in notes[0].text
    assert "Труба 89х4 ст20" in notes[0].text
    assert "принял" in notes[0].text
    assert notes[0].visible_to_bot is False
    assert deal.external_stage == "fulfilment"  # стадию задаёт DealRef события
    # решение клиента — его же действие: ни клиенту, ни менеджеру сообщения нет
    assert bot.sent_messages == []


@pytest.mark.asyncio
async def test_line_disputed_goes_to_the_feed_and_alerts_the_deal_owner_only() -> None:
    session, bot, row, _ = await _process_line_event("delivery.line_disputed")

    assert row.status == "processed"
    notes = [item for item in session.added if isinstance(item, LeadNote)]
    assert len(notes) == 1
    assert "оспорил" in notes[0].text
    assert "Часть труб с трещинами" in notes[0].text
    # одно сообщение — ответственному (Telegram 555), с замечанием; клиент (777) ничего не получает
    assert [m["chat_id"] for m in bot.sent_messages] == [555]
    text = bot.sent_messages[0]["text"]
    assert "ООО Тест" in text
    assert "Поставка осей РУ1Ш" in text
    assert "Часть труб с трещинами" in text
    assert "{" not in text


# ---------------------------------------------------------------------------
# 5. Ротация секрета вебхуков без простоя и защита от повтора тела (FIX-35)
# ---------------------------------------------------------------------------

OLD_SECRET = "old-webhook-secret-xyz-0001"
NEW_SECRET = "new-webhook-secret-xyz-0002"


def _rotating_receiver(
    store: _DummyStore, env_secret: str = ""
) -> tuple[ErpEventsService, _MockSession]:
    session = _MockSession()

    async def enqueue(event_id: str) -> int:
        return 1

    service = ErpEventsService(
        _mock_session_factory(session),
        _DummySettingsService(),  # type: ignore[arg-type]
        store,
        Settings(erp_webhook_secret=env_secret),
        _no_bot,
        enqueue_task=enqueue,
    )
    return service, session


def _signed_with(secret: str, body: dict[str, Any]) -> tuple[bytes, str]:
    raw = json.dumps(body).encode("utf-8")
    return raw, _sign(secret, raw)


def test_verify_signature_any_accepts_each_listed_secret_and_only_them() -> None:
    body = b'{"hello": "world"}'
    assert verify_signature_any([NEW_SECRET, OLD_SECRET], body, _sign(OLD_SECRET, body))
    assert verify_signature_any([NEW_SECRET, OLD_SECRET], body, _sign(NEW_SECRET, body))
    assert not verify_signature_any([NEW_SECRET, OLD_SECRET], body, _sign("third", body))
    assert not verify_signature_any([], body, _sign(NEW_SECRET, body))
    assert not verify_signature_any([NEW_SECRET], body, None)


@pytest.mark.asyncio
async def test_old_secret_is_accepted_while_it_is_the_previous_one_and_refused_once_removed() -> (
    None
):
    """Ротация без простоя: ERP ещё подписывает старым — принимается; сняли предыдущий — 401."""
    service, _ = _rotating_receiver(_DummyStore(NEW_SECRET, previous=OLD_SECRET))
    for secret in (OLD_SECRET, NEW_SECRET):
        raw, sig = _signed_with(
            secret, _sample_envelope(payload={"from": "request", "to": "quoting", "n": secret})
        )
        assert await service.receive_event(str(uuid.uuid4()), "deal.stage_changed", sig, raw) == (
            False,
            "enqueued",
        )

    removed, _ = _rotating_receiver(_DummyStore(NEW_SECRET, previous=None))
    raw, sig = _signed_with(OLD_SECRET, _sample_envelope())
    with pytest.raises(AuthError):
        await removed.receive_event(str(uuid.uuid4()), "deal.stage_changed", sig, raw)
    raw, sig = _signed_with(NEW_SECRET, _sample_envelope())
    assert (await removed.receive_event(str(uuid.uuid4()), "deal.stage_changed", sig, raw))[
        1
    ] == "enqueued"


@pytest.mark.asyncio
async def test_a_secret_list_in_env_works_without_the_connector() -> None:
    service, _ = _rotating_receiver(_DummyStore(), env_secret=f"{NEW_SECRET},{OLD_SECRET}")
    for secret in (OLD_SECRET, NEW_SECRET):
        raw, sig = _signed_with(
            secret, _sample_envelope(payload={"from": "request", "to": "quoting", "n": secret})
        )
        assert (await service.receive_event(str(uuid.uuid4()), "deal.stage_changed", sig, raw))[
            1
        ] == "enqueued"
    raw, sig = _signed_with("a-secret-nobody-listed", _sample_envelope())
    with pytest.raises(AuthError):
        await service.receive_event(str(uuid.uuid4()), "deal.stage_changed", sig, raw)


@pytest.mark.asyncio
async def test_the_same_body_under_another_event_id_is_a_replay_and_is_rejected_with_200() -> None:
    """X-Event-Id и X-Timestamp не подписаны: перехваченное тело под новым id — повтор (FIX-35)."""
    enqueued: list[str] = []
    service, session = _receiver(enqueued=enqueued)
    raw, sig = _signed(_sample_envelope())
    first, replay = str(uuid.uuid4()), str(uuid.uuid4())

    assert await service.receive_event(first, "deal.stage_changed", sig, raw) == (False, "enqueued")
    assert await service.receive_event(replay, "deal.stage_changed", sig, raw) == (
        False,
        "rejected",
    )

    row = session.events[replay]
    assert row.status == "rejected"
    assert row.error == f"replayed body: already received as event {first}"
    assert row.processed_at is not None
    assert enqueued == [first], "повтор не ставится в очередь"
    # тот же id — по-прежнему обычный дубль, а не повтор
    assert await service.receive_event(first, "deal.stage_changed", sig, raw) == (True, "duplicate")


@pytest.mark.asyncio
async def test_different_bodies_are_never_taken_for_a_replay() -> None:
    service, _ = _receiver()
    for stage in ("quoting", "quote_sent", "accepted"):
        raw, sig = _signed(_sample_envelope(payload={"from": "request", "to": stage}))
        assert (await service.receive_event(str(uuid.uuid4()), "deal.stage_changed", sig, raw))[
            1
        ] == "enqueued"
