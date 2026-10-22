"""Unit-тесты обработчика событий ERP и секретов шины CRM (M3-CRM-04 → B4, CONTRACTS §3, §9).

Приём (подпись, окно, идемпотентность по id, `skipped`, 422) — это библиотека `rt_bus` и её тесты;
здесь — то, что делает CRM: секреты пар шины (L12), применение события к зеркалу сделки, ленте
лида и индексу документов, сообщения Telegram (они считаются обработчиком и кладутся в
`erp_event_notices`, отправка — `tests/integration/test_erp_events.py`).
"""

import hashlib
import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from rt_bus import Event
from rt_bus.signing import secret_env_name

from app.bus.secrets import SecretCache, derive_pair_secret
from app.models.clients import Client, Document
from app.models.deals import Deal
from app.models.leads import Lead, LeadNote
from app.schemas.settings import AppSettings, CompanySettings, IntegrationsSettings
from app.services.erp_events import ErpEventError, ErpEventsService
from tests.bus_events import envelope_for

WEBHOOK = "erp-webhook-secret-xyz-42"  # фиктивный


# ---------------------------------------------------------------------------
# 1. Секреты пар шины (решение L12)
# ---------------------------------------------------------------------------


def test_the_pair_secret_is_derived_from_the_webhook_secret_and_is_directional() -> None:
    expected = hmac.new(WEBHOOK.encode(), b"rt-bus/v1/erp->crm", hashlib.sha256).hexdigest()
    assert derive_pair_secret(WEBHOOK, "erp", "crm") == expected
    assert derive_pair_secret(WEBHOOK, "crm", "erp") != expected
    assert derive_pair_secret("other-webhook-secret", "erp", "crm") != expected


def test_known_answer_vector_for_the_other_side_of_the_pair() -> None:
    """Общий вектор: ERP считает ту же формулу и обязана получить те же секреты (L12)."""
    webhook = "webhook-secret-for-the-vector"  # фиктивный
    assert derive_pair_secret(webhook, "erp", "crm") == (
        "cea37d07953f1c87b8982b26a12011a13d1c8034c22b736e41f040df907567ee"
    )
    assert derive_pair_secret(webhook, "crm", "erp") == (
        "b8e95db94f3efb6daeef5544a6c5fa38c47af956fbf1952a2441815fc33c64f5"
    )


def test_both_active_webhook_secrets_give_both_pair_secrets_for_a_rotation() -> None:
    cache = SecretCache()
    cache.set_webhook_secrets(["new-secret-value", "old-secret-value", "new-secret-value", ""])
    assert cache("erp", "crm") == [
        derive_pair_secret("new-secret-value", "erp", "crm"),
        derive_pair_secret("old-secret-value", "erp", "crm"),
    ]


def test_only_the_pair_crm_erp_is_derived_everything_else_needs_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = SecretCache()
    cache.set_webhook_secrets([WEBHOOK])
    assert cache("erp", "crm")
    assert cache("crm", "erp")
    assert cache("platform-bff", "crm") == []
    assert cache("crm", "platform-bff") == []
    assert cache("crm", "crm") == []

    monkeypatch.setenv(secret_env_name("platform-bff", "crm"), "bff-secret-a,bff-secret-b")
    assert cache("platform-bff", "crm") == ["bff-secret-a", "bff-secret-b"]


def test_an_explicit_environment_secret_wins_over_the_derived_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = SecretCache()
    cache.set_webhook_secrets([WEBHOOK])
    monkeypatch.setenv("RT_BUS_SECRET_ERP_CRM", "explicit-pair-secret")
    assert cache("erp", "crm") == ["explicit-pair-secret"]
    assert cache("crm", "erp") == [derive_pair_secret(WEBHOOK, "crm", "erp")]


def test_without_webhook_secrets_there_is_no_pair_secret() -> None:
    assert SecretCache()("erp", "crm") == []


@pytest.mark.asyncio
async def test_the_cache_reloads_every_time_by_default_and_keeps_old_values_on_failure() -> None:
    state: dict[str, Any] = {"secrets": ["first-secret-value"], "fail": False, "calls": 0}

    async def loader() -> list[str]:
        state["calls"] += 1
        if state["fail"]:
            raise OSError("db down")
        return list(state["secrets"])

    cache = SecretCache(loader)
    await cache.refresh()
    assert cache("erp", "crm") == [derive_pair_secret("first-secret-value", "erp", "crm")]

    state["secrets"] = ["second-secret-value"]
    await cache.refresh()
    assert cache("erp", "crm") == [derive_pair_secret("second-secret-value", "erp", "crm")]

    state["fail"] = True
    await cache.refresh()
    assert cache("erp", "crm") == [derive_pair_secret("second-secret-value", "erp", "crm")]
    assert state["calls"] == 3


@pytest.mark.asyncio
async def test_a_ttl_makes_the_cache_skip_reloads() -> None:
    now = [100.0]
    calls = [0]

    async def loader() -> list[str]:
        calls[0] += 1
        return ["some-webhook-secret"]

    cache = SecretCache(loader, ttl_s=30, clock=lambda: now[0])
    await cache.refresh()
    await cache.refresh()
    now[0] += 31
    await cache.refresh()
    assert calls[0] == 2


# ---------------------------------------------------------------------------
# 2. Применение событий (сессия-заглушка)
# ---------------------------------------------------------------------------


class _DummySettingsService:
    def __init__(self, cabinet_url: str = "") -> None:
        self._cabinet_url = cabinet_url

    async def get(self) -> AppSettings:
        return AppSettings(
            integrations=IntegrationsSettings(erp_base_url="https://erp.internal"),
            company=CompanySettings(cabinet_url=self._cabinet_url),
        )


class _Notices:
    """Вместо `ErpEventNotices`: запоминает, какие сообщения обработчик положил в транзакцию."""

    def __init__(self) -> None:
        self.added: list[tuple[str, list[dict[str, Any]]]] = []

    def add(self, session: Any, event_id: str, items: list[dict[str, Any]]) -> None:
        self.added.append((event_id, items))

    @property
    def items(self) -> list[dict[str, Any]]:
        return [item for _, items in self.added for item in items]


class _Session:
    def __init__(
        self,
        clients: dict[int, Client],
        leads: dict[int, Lead],
        deals: dict[int, Deal],
    ) -> None:
        self.clients = clients
        self.leads = leads
        self.deals = deals
        self.added: list[Any] = []
        self._next_id = 5000

    @asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        yield

    async def flush(self) -> None:
        for item in self.added:
            if getattr(item, "id", None) is None:
                self._next_id += 1
                item.id = self._next_id

    async def execute(self, stmt: Any) -> Any:
        return object()

    async def get(self, model: type[Any], pk: Any, **_: Any) -> Any:
        if model is Client:
            return self.clients.get(int(pk))
        return None

    async def scalar(self, stmt: Any) -> Any:
        sql_str = str(stmt).lower()
        if "from deals" in sql_str:
            return next(iter(self.deals.values()), None)
        if "from leads" in sql_str:
            return next(iter(self.leads.values()), None)
        if "from documents" in sql_str:
            wanted = stmt.compile().params.get("erp_document_id_1")
            return next(
                (d for d in self.added if isinstance(d, Document) and d.erp_document_id == wanted),
                None,
            )
        return None

    def add(self, instance: Any) -> None:
        self.added.append(instance)
        if isinstance(instance, Deal):
            if instance.id is None:
                self._next_id += 1
                instance.id = self._next_id
            self.deals[instance.id] = instance


def _data(
    client_id: int = 101,
    company_id: int = 202,
    stage: str = "quoting",
    payload: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "erp_company_id": company_id,
        "crm_client_id": client_id,
        "deal": {
            "erp_deal_id": 9001,
            "number": "DL-9001",
            "title": "Поставка осей РУ1Ш",
            "stage": stage,
            "amount": "15000000.00",
            "currency": "UZS",
        },
        "actor": actor or {"type": "system", "name": "ERP Auto"},
        "payload": payload if payload is not None else {"from": "request", "to": stage},
    }


def _event(event: str, data: dict[str, Any], time: datetime | None = None) -> Event:
    return Event.from_dict(envelope_for(f"uz.railtech.erp.{event}.v1", data, time=time))


def _service(cabinet_url: str = "") -> tuple[ErpEventsService, _Notices]:
    notices = _Notices()
    service = ErpEventsService(
        _DummySettingsService(cabinet_url),  # type: ignore[arg-type]
        notices,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )
    return service, notices


def _world(**lead_kwargs: Any) -> tuple[Client, Lead, Deal, Any]:
    client = Client(id=101, name="ООО Тест", inn="1234567890", erp_company_id=202)
    lead = Lead(id=501, client_id=101, display_name="Лид", **lead_kwargs)
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
    return client, lead, deal, _Session({101: client}, {501: lead}, {701: deal})


@pytest.mark.asyncio
async def test_deal_won_closes_the_mirror_and_writes_the_feed_and_messages_nobody() -> None:
    _, _, deal, session = _world()
    service, notices = _service()
    event = _event(
        "deal.won",
        _data(stage="won", payload={"amount": "15000000.00", "currency": "UZS"}),
    )

    assert await service.apply(session, event) is True

    assert deal.stage == "won"
    assert deal.external_stage == "won"
    assert deal.closed_at is not None
    notes = [item for item in session.added if isinstance(item, LeadNote)]
    assert len(notes) == 1
    assert "won" in notes[0].text.lower()
    assert notes[0].visible_to_bot is False
    assert notices.items == [], "для deal.won сообщение клиенту не уходит"


@pytest.mark.asyncio
async def test_quote_sent_prepares_a_client_message_with_the_link_button() -> None:
    _, _, deal, session = _world()
    service, notices = _service()
    payload = {
        "erp_quote_id": 42,
        "version": 1,
        "public_url": "https://cabinet.railtech.uz/quotes/42",
        "total": "15000000.00",
        "currency": "UZS",
    }
    event = _event("quote.sent", _data(stage="quote_sent", payload=payload))

    await service.apply(session, event)

    assert deal.external_stage == "quote_sent"
    (item,) = notices.items
    assert item["kind"] == "client"
    assert item["client_id"] == 101
    assert "коммерческое предложение" in item["text"]
    assert item["buttons"], "кнопка со ссылкой на КП"
    assert notices.added[0][0] == event.id, "ключ сообщений — id события шины"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "text_part", "buttons"),
    [
        (
            "ru",
            "коммерческое предложение",
            [
                ["Открыть КП", "https://erp.example.com/q/42"],
                ["Кабинет", "https://cab.example.com"],
            ],
        ),
        (
            "uz",
            "tijorat taklifi",
            [
                ["Taklifni ochish", "https://erp.example.com/q/42"],
                ["Kabinet", "https://cab.example.com"],
            ],
        ),
        (
            "en",
            "commercial proposal",
            [
                ["Open the quote", "https://erp.example.com/q/42"],
                ["Cabinet", "https://cab.example.com"],
            ],
        ),
    ],
)
async def test_client_message_follows_lead_language_with_cabinet_button(
    language: str, text_part: str, buttons: list[list[str]]
) -> None:
    """I-8: текст из settings.texts на языке лида, кнопки «Открыть КП» и «Кабинет»."""
    _, _, _, session = _world(language=language)
    service, notices = _service("https://cab.example.com")
    payload = {"erp_quote_id": 42, "version": 1, "public_url": "https://erp.example.com/q/42"}
    event = _event("quote.sent", _data(stage="quote_sent", payload=payload))

    await service.apply(session, event)

    (item,) = notices.items
    assert text_part in item["text"]
    assert item["buttons"] == buttons


@pytest.mark.asyncio
async def test_no_cabinet_button_when_cabinet_url_is_empty() -> None:
    _, _, _, session = _world(language="ru")
    service, notices = _service("")
    payload = {
        "erp_invoice_id": 4,
        "number": "INV-01",
        "amount": "100.00",
        "currency": "UZS",
        "due_date": "2026-10-30",
    }
    await service.apply(session, _event("invoice.paid", _data(stage="paid", payload=payload)))

    (item,) = notices.items
    assert "INV-01" in item["text"]
    assert item["buttons"] == [], "сообщение не ломается без адреса кабинета"


@pytest.mark.asyncio
async def test_document_created_goes_into_the_index() -> None:
    _, _, _, session = _world()
    service, _ = _service()
    payload = {"erp_document_id": 88, "kind": "invoice", "number": "INV-2026-001"}
    event = _event("document.created", _data(stage="invoiced", payload=payload))

    assert await service.apply(session, event) is True

    docs = [item for item in session.added if isinstance(item, Document)]
    assert len(docs) == 1
    assert docs[0].client_id == 101
    assert docs[0].type == "invoice"
    assert docs[0].extract_status == "skipped"
    assert "INV-2026-001" in docs[0].title


@pytest.mark.asyncio
async def test_a_missing_client_fails_the_event_so_that_the_bus_retries_and_then_marks_it() -> None:
    service, notices = _service()
    session: Any = _Session({}, {}, {})

    with pytest.raises(ErpEventError, match="not found"):
        await service.apply(session, _event("deal.stage_changed", _data(client_id=99999)))

    assert session.added == []
    assert notices.added == []


@pytest.mark.asyncio
async def test_another_company_fails_the_event_and_changes_nothing() -> None:
    client, _, deal, session = _world()
    service, notices = _service()

    with pytest.raises(ErpEventError, match="company mismatch"):
        await service.apply(session, _event("deal.stage_changed", _data(company_id=999)))

    assert client.erp_company_id == 202
    assert deal.external_stage == "quoting"
    assert session.added == []
    assert notices.added == []


@pytest.mark.asyncio
async def test_a_body_that_does_not_fit_the_model_fails_without_echoing_values() -> None:
    _, _, _, session = _world()
    service, _ = _service()
    data = _data(stage="quote_sent", payload={"erp_quote_id": "secret-looking-value"})

    with pytest.raises(ErpEventError) as info:
        await service.apply(session, _event("quote.sent", data))

    assert "secret-looking-value" not in str(info.value)


# ── Приёмка и замечания по строкам поставки (FIX-37) ────────────────────────────────────────────


def _line_data(event: str) -> dict[str, Any]:
    status = "accepted" if event == "delivery.line_accepted" else "disputed"
    payload: dict[str, Any] = {
        "line_no": 2,
        "title": "Труба 89х4 ст20",
        "status": status,
        "decided_at": "2026-10-20T10:00:00+05:00",
    }
    if status == "disputed":
        payload["remark"] = "Часть труб с трещинами"
    return _data(
        stage="fulfilment",
        payload=payload,
        actor={"type": "client", "name": "Азамат Каримов"},
    )


@pytest.mark.asyncio
async def test_line_accepted_goes_to_the_feed_and_nobody_is_messaged() -> None:
    _, _, deal, session = _world(language="uz")
    service, notices = _service("https://cab.example.com")

    await service.apply(
        session, _event("delivery.line_accepted", _line_data("delivery.line_accepted"))
    )

    notes = [item for item in session.added if isinstance(item, LeadNote)]
    assert len(notes) == 1
    assert "Азамат Каримов" in notes[0].text
    assert "Труба 89х4 ст20" in notes[0].text
    assert "принял" in notes[0].text
    assert deal.external_stage == "fulfilment"  # стадию задаёт DealRef события
    assert notices.items == [], "решение клиента — его же действие: сообщений нет"


@pytest.mark.asyncio
async def test_line_disputed_goes_to_the_feed_and_alerts_the_deal_owner_only() -> None:
    _, _, deal, session = _world(language="uz")
    deal.owner_user_id = 1
    service, notices = _service("https://cab.example.com")

    await service.apply(
        session, _event("delivery.line_disputed", _line_data("delivery.line_disputed"))
    )

    notes = [item for item in session.added if isinstance(item, LeadNote)]
    assert len(notes) == 1
    assert "оспорил" in notes[0].text
    assert "Часть труб с трещинами" in notes[0].text
    (item,) = notices.items
    assert (item["kind"], item["user_id"]) == ("staff", 1), "ответственному, не клиенту"
    assert "ООО Тест" in item["text"]
    assert "Поставка осей РУ1Ш" in item["text"]
    assert "Часть труб с трещинами" in item["text"]
    assert "{" not in item["text"]


@pytest.mark.asyncio
async def test_a_stale_event_does_not_roll_the_mirror_back() -> None:
    _, _, deal, session = _world()
    deal.external_stage, deal.external_stage_at = "paid", datetime(2026, 10, 20, 12, tzinfo=UTC)
    service, notices = _service()
    stale = _event(
        "delivery.eta_changed",
        _data(
            stage="fulfilment",
            payload={"line_summary": "Оси", "eta": "2026-11-01", "status": "in_transit"},
        ),
        time=datetime(2026, 10, 20, 10, tzinfo=UTC),
    )

    await service.apply(session, stale)

    assert deal.external_stage == "paid"
    assert deal.title == "Поставка осей", "устаревшее событие название не меняет"
    assert [item for item in session.added if isinstance(item, LeadNote)], "но лента пишется"
    assert notices.items == [], "устаревший «срок сдвинулся» в бот не идёт"


def test_the_pair_environment_name_matches_the_documented_convention() -> None:
    assert secret_env_name("erp", "crm") == "RT_BUS_SECRET_ERP_CRM"
    assert secret_env_name("platform-bff", "crm") == "RT_BUS_SECRET_PLATFORM_BFF_CRM"
