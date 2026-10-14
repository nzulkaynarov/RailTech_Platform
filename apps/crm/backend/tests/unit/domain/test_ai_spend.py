"""Свёртка журнала расходов LiteLLM (M3-CRM-09): теги, строка, сутки по Ташкенту, превышения."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from app.domain import ai_spend as rules
from app.domain.ai_spend import LogRow

FIXTURE = Path(__file__).parents[2] / "fixtures" / "litellm" / "spend_logs_v2.json"
TZ = "Asia/Tashkent"
DAY = date(2026, 10, 14)


def recorded() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))["page"]["data"]
    return data


def row(at: str, *, rid: str = "r1", cost: float = 0.5, system: str = "crm") -> LogRow:
    return LogRow(rid, datetime.fromisoformat(at), cost, 1, 1, system, "dialog", "m", False, False)


def test_call_tags_are_key_value() -> None:
    assert rules.call_tags("crm", "dialog", "dialog-model") == [
        "system=crm",
        "feature=dialog",
        "model=dialog-model",
    ]


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (
            ["system=crm", "feature=dialog", "model=dialog-model"],
            {"system": "crm", "feature": "dialog", "model": "dialog-model"},
        ),
        (["system:erp", "feature:intake"], {"system": "erp", "feature": "intake"}),
        (["User-Agent: AsyncOpenAI", "User-Agent: AsyncOpenAI/Python 3.28.0"], {}),
        (["system=", "feature", 7, None, "SYSTEM=crm"], {"system": "crm"}),
        (["system=crm", "system=erp"], {"system": "crm"}),  # первый тег побеждает
        ([], {}),
    ],
)
def test_parse_tags(tags: list[Any], expected: dict[str, str]) -> None:
    assert rules.parse_tags(tags) == expected


def test_recorded_rows_map_to_dimensions() -> None:
    rows = [rules.to_row(r) for r in recorded()]
    assert all(r is not None for r in rows)
    got = [(r.system, r.feature, r.model, r.failed, r.degraded) for r in rows if r]
    assert got == [
        ("crm", "dialog", "dialog-model", False, False),
        ("crm", "dialog", "fallback-model", False, True),  # BudgetGuard CRM → fallback-model
        ("crm", "kb-search", "embed-model", False, False),
        ("erp", "intake", "fallback-model", False, True),  # fallbacks роутера LiteLLM
        ("other", "other", "dialog-model", False, False),  # вызов без тегов
        ("erp", "intake", "intake-model", True, False),  # отказ: строка есть, $0
    ]
    first = rows[0]
    assert first is not None
    assert (first.input_tokens, first.output_tokens, first.cost_usd) == (10, 20, 1.35e-05)
    assert first.at == datetime(2026, 10, 14, 2, 42, 51, 759000, tzinfo=UTC)


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"request_id": "x"},
        {"request_id": "", "startTime": "2026-10-14T00:00:00+00:00"},
        {"request_id": "x", "startTime": "вчера"},
        {"request_id": 5, "startTime": "2026-10-14T00:00:00+00:00"},
    ],
)
def test_foreign_rows_are_skipped(raw: dict[str, Any]) -> None:
    assert rules.to_row(raw) is None


def test_probe_on_fallback_is_not_degradation_and_naive_time_is_utc() -> None:
    parsed = rules.to_row(
        {
            "request_id": "p",
            "startTime": "2026-10-14T05:00:00",
            "spend": "0.001",
            "model_group": "fallback-model",
            "request_tags": ["system=crm", "feature=probe", "model=fallback-model"],
            "status": "success",
        }
    )
    assert parsed is not None
    assert (parsed.degraded, parsed.cost_usd, parsed.at.tzinfo) == (False, 0.001, UTC)


def test_model_falls_back_to_tag_then_provider_model() -> None:
    base = {"request_id": "x", "startTime": "2026-10-14T05:00:00+00:00"}
    tagged = rules.to_row({**base, "request_tags": ["model=draft-model"], "model": "anthropic/x"})
    bare = rules.to_row({**base, "model": "anthropic/x"})
    assert (tagged and tagged.model, bare and bare.model) == ("draft-model", "anthropic/x")


@pytest.mark.parametrize(
    ("at", "counted_day"),
    [
        ("2026-10-13T18:59:59.999+00:00", None),  # 23:59:59 13-го по Ташкенту — вне периода
        ("2026-10-13T19:00:00+00:00", date(2026, 10, 14)),  # 00:00 14-го по Ташкенту
        ("2026-10-14T18:59:59.999+00:00", date(2026, 10, 14)),
        ("2026-10-14T19:00:00+00:00", None),  # уже 15-е по Ташкенту
    ],
)
def test_day_boundaries_follow_tashkent(at: str, counted_day: date | None) -> None:
    cube = rules.build_cube([row(at)], DAY, DAY, TZ)
    assert [c.day for c in cube.cells] == ([counted_day] if counted_day else [])


def test_window_is_half_open_in_utc() -> None:
    start, end = rules.window(date(2026, 10, 13), DAY, TZ)
    assert (start, end) == (
        datetime(2026, 10, 12, 19, tzinfo=UTC),
        datetime(2026, 10, 14, 19, tzinfo=UTC),
    )


def test_duplicate_request_counted_once() -> None:
    at = "2026-10-14T05:00:00+00:00"
    cube = rules.build_cube([row(at), row(at), row(at, rid="r2")], DAY, DAY, TZ)
    assert rules.total(cube).calls == 2


def test_recorded_totals_match_litellm_to_the_call() -> None:
    raw = recorded()
    rows = [r for x in raw if (r := rules.to_row(x)) is not None]
    total = rules.total(rules.build_cube(rows, DAY, DAY, TZ))
    assert total.calls == len(raw) == 6
    assert total.cost_usd == pytest.approx(sum(x["spend"] for x in raw), abs=1e-12)
    assert total.input_tokens == sum(x["prompt_tokens"] for x in raw)
    assert total.output_tokens == sum(x["completion_tokens"] for x in raw)
    assert (total.failed_calls, total.fallback_calls) == (1, 2)


def test_group_by_day_fills_every_day_and_splits_systems() -> None:
    rows = [
        row("2026-10-14T05:00:00+00:00", rid="a", cost=1.0),
        row("2026-10-14T06:00:00+00:00", rid="b", cost=0.25, system="erp"),
    ]
    cube = rules.build_cube(rows, date(2026, 10, 12), DAY, TZ)
    grouped = rules.group(cube, "day")
    assert [(k, a.calls) for k, a, _ in grouped] == [
        ("2026-10-12", 0),
        ("2026-10-13", 0),
        ("2026-10-14", 2),
    ]
    split = grouped[-1][2]
    assert {s: a.cost_usd for s, a in split.items()} == {"crm": 1.0, "erp": 0.25}


def test_group_by_dimension_sorted_by_cost_then_key() -> None:
    rows = [
        row("2026-10-14T05:00:00+00:00", rid="a", cost=0.1, system="erp"),
        row("2026-10-14T05:00:01+00:00", rid="b", cost=0.3, system="crm"),
        row("2026-10-14T05:00:02+00:00", rid="c", cost=0.1, system="other"),
    ]
    cube = rules.build_cube(rows, DAY, DAY, TZ)
    assert [k for k, _, _ in rules.group(cube, "system")] == ["crm", "erp", "other"]


@pytest.mark.parametrize(
    ("spent", "limit", "over"),
    [(1.0, 1.0, True), (1.01, 1.0, True), (0.99, 1.0, False), (5.0, 0.0, False), (0, 0, False)],
)
def test_over_budget(spent: float, limit: float, over: bool) -> None:
    assert rules.over_budget(spent, limit) is over


def test_systems_order_keeps_crm_and_erp_first() -> None:
    assert rules.systems_order([]) == ["crm", "erp"]
    assert rules.systems_order(["other", "cabinet", "crm"]) == ["crm", "erp", "cabinet", "other"]


@pytest.mark.parametrize(
    ("first", "last", "problem"),
    [
        (date(2026, 7, 17), DAY, None),  # ровно 90 дней
        (date(2026, 7, 16), DAY, "too_long"),
        (DAY, date(2026, 10, 13), "from_after_to"),
        (DAY, date(2026, 10, 15), "future"),
        (DAY, DAY, None),
    ],
)
def test_period_rules(first: date, last: date, problem: str | None) -> None:
    assert rules.period_error(first, last, DAY) == problem
