"""«Расходы» и «Модели ИИ»: сборка отчёта, каталог LiteLLM, статусы, проверка, запись учёта."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast

import httpx2
import pytest
from openai import APIConnectionError

from app.integrations.litellm_catalog import ModelEntry, parse_model_info
from app.integrations.llm_usage import UsageEvent
from app.models.system import SystemAlert
from app.schemas.settings import ModelKeyMask
from app.services import models_status
from app.services.llm_usage import DbUsageRecorder
from app.services.spend import provider_rows, series

MODEL_INFO = {
    "data": [
        {
            "model_name": "dialog-model",
            "litellm_params": {"model": "anthropic/claude-sonnet-5-5", "api_key": "sk-secret"},
            "model_info": {"litellm_provider": "anthropic"},
        },
        {"model_name": "embed-model", "litellm_params": {"model": "gemini/gemini-embedding-2"}},
        {"model_name": "bare", "litellm_params": {"model": "gpt-x"}},
        {"model_name": 7},
        "junk",
    ]
}


def test_parse_model_info_takes_provider_and_model_only() -> None:
    entries = parse_model_info(MODEL_INFO)
    assert entries == {
        "dialog-model": ModelEntry("dialog-model", "anthropic", "anthropic/claude-sonnet-5-5"),
        "embed-model": ModelEntry("embed-model", "gemini", "gemini/gemini-embedding-2"),
        "bare": ModelEntry("bare", None, "gpt-x"),
    }
    assert "sk-secret" not in repr(entries)


def test_series_fills_empty_days() -> None:
    by_day = {date(2026, 10, 11): {"work": 0.5, "test": 0.25}}
    rows = series(date(2026, 10, 12), 3, by_day)
    assert [(r.day.day, r.work_usd, r.test_usd) for r in rows] == [
        (10, 0.0, 0.0),
        (11, 0.5, 0.25),
        (12, 0.0, 0.0),
    ]


def test_provider_rows_union_of_limits_and_spend() -> None:
    rows = provider_rows({"anthropic": 3.0, "gemini": 1.0}, {"openai": 0.1, "anthropic": 1.5})
    assert [(r.provider, r.spent_usd, r.limit_usd) for r in rows] == [
        ("anthropic", 1.5, 3.0),
        ("gemini", 0.0, 1.0),
        ("openai", 0.1, 0.0),
    ]


def test_statuses_health_from_monitor() -> None:
    now = datetime(2026, 10, 12, tzinfo=UTC)
    alerts = {
        "model:dialog-model": SystemAlert(
            key="model:dialog-model", active=True, detail="нет кредитов", updated_at=now
        ),
        "model:fallback-model": SystemAlert(
            key="model:fallback-model", active=False, updated_at=now
        ),
    }
    entries = {"dialog-model": ModelEntry("dialog-model", "anthropic", "anthropic/x")}
    rows = {r.alias: r for r in models_status.statuses(entries, alerts, {"dialog-model": 0.4})}
    assert (rows["dialog-model"].health, rows["dialog-model"].health_detail) == (
        "problem",
        "нет кредитов",
    )
    assert rows["dialog-model"].today_usd == 0.4
    assert rows["fallback-model"].health == "ok"
    assert (rows["embed-model"].health, rows["embed-model"].provider) == ("unknown", None)


def test_health_detail_from_monitor_is_masked() -> None:
    """Сырой текст провайдера в «Требует внимания» идёт только замаскированным (W15-H3)."""
    now = datetime(2026, 10, 12, tzinfo=UTC)
    raw = "401: Error code: 401 - Authorization: Bearer sk-ant-abcdef0123456789 rejected"
    alerts = {
        "model:dialog-model": SystemAlert(
            key="model:dialog-model", active=True, detail=raw, updated_at=now
        )
    }
    entries = {"dialog-model": ModelEntry("dialog-model", "anthropic", "anthropic/x")}
    row = next(r for r in models_status.statuses(entries, alerts, {}) if r.alias == "dialog-model")
    assert row.health_detail is not None
    assert "sk-ant-abcdef" not in row.health_detail
    assert "401" in row.health_detail


class Raw:
    def __init__(self, parsed: Any) -> None:
        self._parsed = parsed
        self.headers = {"x-litellm-response-cost": "0.00001"}

    def parse(self) -> Any:
        return self._parsed


class FakeLlm:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.kwargs: list[dict[str, Any]] = []
        create = SimpleNamespace(create=self.create)
        self.chat = SimpleNamespace(completions=SimpleNamespace(with_raw_response=create))
        self.embeddings = SimpleNamespace(with_raw_response=create)

    async def create(self, **kwargs: Any) -> Raw:
        self.kwargs.append(kwargs)
        if self.fail:
            raise APIConnectionError(request=httpx2.Request("POST", "http://litellm"))
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1)
        return Raw(SimpleNamespace(model="served", usage=usage))


class Sink:
    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    async def record(self, event: UsageEvent) -> None:
        self.events.append(event)


@pytest.mark.parametrize("alias", ["dialog-model", "embed-model"])
async def test_probe_is_minimal_and_recorded(alias: str) -> None:
    client, sink = FakeLlm(), Sink()
    result = await models_status.probe(cast(Any, client), alias, sink)
    assert result.ok is True
    assert result.cost_usd == pytest.approx(0.00001)
    sent = client.kwargs[0]
    tags = {"tags": ["system=crm", "feature=probe", f"model={alias}"]}
    if alias == "embed-model":
        assert (sent["input"], sent["extra_body"]) == (["ping"], {"metadata": tags})
    else:
        extra = {"metadata": tags, "disable_fallbacks": True}
        assert (sent["max_tokens"], sent["extra_body"]) == (1, extra)
    assert [(e.purpose, e.alias) for e in sink.events] == [("probe", alias)]


async def test_probe_failure_is_reported_not_raised() -> None:
    sink = Sink()
    result = await models_status.probe(cast(Any, FakeLlm(fail=True)), "dialog-model", sink)
    assert result.ok is False
    assert result.detail
    assert sink.events == []


async def test_recorder_never_breaks_the_call() -> None:
    def broken_sessions() -> Any:
        raise RuntimeError("db down")

    recorder = DbUsageRecorder(cast(Any, broken_sessions), None)
    await recorder.record(UsageEvent("dialog", "dialog-model", "m", 1, 1, 0.1))


def test_statuses_expose_key_mask_but_no_key() -> None:
    now = datetime(2026, 10, 12, tzinfo=UTC)
    keys = {
        "dialog-model": ModelKeyMask(source="crm", last4="4321", updated_at=now),
        "fallback-model": ModelKeyMask(source="env", updated_at=now),
    }
    rows = {r.alias: r for r in models_status.statuses({}, {}, {}, keys)}
    assert (rows["dialog-model"].key_source, rows["dialog-model"].key_last4) == ("crm", "4321")
    assert (rows["fallback-model"].key_source, rows["fallback-model"].key_last4) == ("env", None)
    assert (rows["embed-model"].key_source, rows["embed-model"].key_last4) == (None, None)
    assert set(rows["dialog-model"].model_dump()) == {
        "alias",
        "provider",
        "model",
        "health",
        "health_detail",
        "checked_at",
        "today_usd",
        "key_source",
        "key_last4",
    }
