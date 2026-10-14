"""Здоровье вендоров по журналу шлюза (M3-CRM-12, ADR-0024): записанный ответ LiteLLM v1.105.0."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.domain import external_vendor as v
from app.domain.external_vendor import CallRow, VendorFacts, VendorStats

FIXTURE = Path(__file__).parents[2] / "fixtures" / "litellm" / "spend_logs_v2.json"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
PROVIDERS = {"dialog-model": "anthropic", "intake-model": "anthropic", "fallback-model": "gemini"}


def fixture_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))["page"]["data"]
    return rows


def test_recorded_rows_parse_with_vendor_latency_and_errors() -> None:
    calls = [c for raw in fixture_rows() if (c := v.to_call(raw, PROVIDERS)) is not None]
    assert len(calls) == len(fixture_rows())
    assert {c.vendor for c in calls} == {"openai"}  # подставные модели записи — openai
    assert all(c.latency_ms is not None and c.latency_ms >= 0 for c in calls)
    failed = [c for c in calls if c.failed]
    assert len(failed) == 1
    assert failed[0].error is not None
    assert "InternalServerError" in failed[0].error
    assert failed[0].error_kind == "other"
    # ERP intake ушёл на запасную модель по router fallbacks: вызов «ушёл» с anthropic.
    assert sum(1 for c in calls if c.diverted_from == "anthropic") == 1


def test_vendor_falls_back_to_alias_provider_when_row_has_none() -> None:
    raw = {
        "startTime": "2026-10-14T08:59:00+00:00",
        "model_group": "dialog-model",
        "status": "success",
    }
    call = v.to_call(raw, PROVIDERS)
    assert call is not None
    assert call.vendor == "anthropic"
    assert call.latency_ms is None
    assert v.to_call({"model_group": "dialog-model"}, PROVIDERS) is None


@pytest.mark.parametrize(
    ("info", "kind"),
    [
        ({"error_code": "401", "error_class": "AuthenticationError"}, "auth"),
        ({"error_code": "403", "error_class": "PermissionDeniedError"}, "auth"),
        ({"error_code": "429", "error_class": "RateLimitError"}, "quota"),
        ({"error_code": "500", "error_class": "InternalServerError"}, "other"),
    ],
)
def test_error_kinds(info: dict[str, str], kind: str) -> None:
    raw = {
        "startTime": "2026-10-14T08:59:00+00:00",
        "custom_llm_provider": "anthropic",
        "status": "failure",
        "metadata": {"error_information": {**info, "error_message": "boom"}},
    }
    call = v.to_call(raw, PROVIDERS)
    assert call is not None
    assert call.error_kind == kind
    assert call.failed


def test_scrub_hides_key_fragments() -> None:
    # Фрагменты собираются в тесте: в исходнике нет строк, похожих на ключ (gitleaks).
    openai_like = "sk" + "-proj-" + "x" * 12
    gemini_like = "AIza" + "y" * 11
    text = v.scrub(f"Incorrect API key provided: {openai_like} and {gemini_like}")
    assert openai_like not in text
    assert gemini_like not in text


def call(
    minutes_ago: float, *, failed: bool = False, vendor: str = "anthropic", **kw: Any
) -> CallRow:
    return CallRow(vendor, NOW - timedelta(minutes=minutes_ago), 100, failed, 0.001, **kw)


def test_stats_by_vendor_and_window() -> None:
    rows = [
        call(1),
        call(2, failed=True, error="401 AuthenticationError", error_kind="auth"),
        call(30),
        call(3, vendor="gemini", diverted_from="anthropic"),
    ]
    window = v.stats(rows, NOW - timedelta(minutes=15))
    assert window["anthropic"].calls == 2
    assert window["anthropic"].failures == 1
    assert window["anthropic"].diverted == 1
    assert window["gemini"].calls == 1
    assert window["anthropic"].last_error_kind == "auth"
    assert window["anthropic"].last_success_at == NOW - timedelta(minutes=1)


@pytest.mark.parametrize(
    ("values", "p95"),
    [([], None), ([5], 5), (list(range(1, 101)), 95), (list(range(1, 21)), 19)],
)
def test_p95(values: list[int], p95: int | None) -> None:
    assert v.p95(values) == p95


def test_day_metrics() -> None:
    stats = VendorStats(calls=4, failures=1, cost_usd=0.5, diverted=2, latencies=[100, 200, 300])
    assert v.day_metrics(stats) == {
        "calls_24h": 4,
        "failures_24h": 1,
        "error_rate_24h": 0.25,
        "p95_ms_24h": 300,
        "spend_24h_usd": 0.5,
        "fallback_24h": 2,
    }
    assert v.day_metrics(None)["error_rate_24h"] is None


def window(
    calls: int, failures: int, *, kind: str = "other", last_failed: bool = True
) -> VendorStats:
    s = VendorStats(calls=calls, failures=failures)
    if failures:
        s.last_error, s.last_error_kind = "boom", kind
        s.last_error_at = NOW - timedelta(minutes=1 if last_failed else 5)
    if calls > failures:
        s.last_success_at = NOW - timedelta(minutes=3)
    return s


@pytest.mark.parametrize(
    ("facts", "status", "words"),
    [
        (VendorFacts("anthropic", True, window(0, 0)), "ok", "не было"),
        (VendorFacts("anthropic", True, window(10, 0)), "ok", "без ошибок"),
        (VendorFacts("anthropic", True, window(10, 1, last_failed=False)), "ok", "ошибок 1"),
        # Неверный ключ: первый же вызов с отказом авторизации — сбой (≤ 1 мин, ADR-0024).
        (VendorFacts("anthropic", True, window(1, 1, kind="auth")), "fail", "ошибками"),
        (VendorFacts("anthropic", True, window(10, 5)), "fail", "5 из 10"),
        (VendorFacts("anthropic", True, window(10, 2, last_failed=False)), "warn", "2 из 10"),
        (VendorFacts("anthropic", True, window(2, 1)), "warn", "1 из 2"),
        (VendorFacts("anthropic", False), "unknown", "недоступен"),
        (VendorFacts("anthropic", True, window(5, 5), disabled=True), "off", "вручную"),
        (VendorFacts("anthropic", True, window(1, 0), 3.0, 3.0), "fail", "потолок"),
        (VendorFacts("anthropic", True, window(1, 0), 2.5, 3.0), "warn", "83%"),
        (VendorFacts("anthropic", True, window(1, 0), 1.0, None), "ok", "без ошибок"),
    ],
)
def test_vendor_rules(facts: VendorFacts, status: str, words: str) -> None:
    result = v.vendor(facts)
    assert result.key == "vendor.anthropic"
    assert result.status == status, result.summary
    assert words in result.summary
    if status in ("fail", "warn"):
        assert result.hint


@pytest.mark.parametrize(
    ("kind", "hint"),
    [("auth", "«Модели ИИ»"), ("quota", "пополните баланс"), ("other", "запасную модель")],
)
def test_vendor_hint_by_error_kind(kind: str, hint: str) -> None:
    result = v.vendor(VendorFacts("anthropic", True, window(10, 9, kind=kind)))
    assert hint in (result.hint or "")


def test_vendor_metrics_include_window_budget_and_day() -> None:
    result = v.vendor(VendorFacts("gemini", True, window(4, 0), 0.1, 1.0, {"calls_24h": 40}))
    assert result.metrics == {
        "calls_15m": 4,
        "failures_15m": 0,
        "budget_spend_usd": 0.1,
        "budget_limit_usd": 1.0,
        "calls_24h": 40,
    }
