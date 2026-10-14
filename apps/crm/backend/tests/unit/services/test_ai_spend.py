"""AiSpendService (M3-CRM-09): записанный журнал LiteLLM → отчёт «Расходы», бюджеты, кэш, ошибки."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from pydantic import AnyHttpUrl, SecretStr

from app.domain.errors import UpstreamUnavailableError, ValidationFailedError
from app.domain.system_status import AiBudgetFacts
from app.integrations.litellm_spend import LiteLLMSpendError, LiteLLMSpendLogs, SpendLogs
from app.services.ai_spend import AiSpendService

FIXTURE = Path(__file__).parents[2] / "fixtures" / "litellm" / "spend_logs_v2.json"
RECORDED: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
PAGE: dict[str, Any] = RECORDED["page"]
# 07:43 по Ташкенту 14.10.2026 — в тот же день, что и записанный журнал.
NOW = datetime(2026, 10, 14, 2, 43, 30, tzinfo=UTC)


class Settings:
    def __init__(self, crm: float = 2.0, erp: float = 1.0) -> None:
        self.cfg = SimpleNamespace(
            business_hours=SimpleNamespace(timezone="Asia/Tashkent"),
            budget=SimpleNamespace(daily_usd=crm, erp_daily_usd=erp),
        )

    async def get(self) -> Any:
        return self.cfg


class Source:
    def __init__(self, rows: list[dict[str, Any]] | None = None, fail: bool = False) -> None:
        self.rows = PAGE["data"] if rows is None else rows
        self.fail = fail
        self.calls: list[tuple[datetime, datetime]] = []

    async def fetch(self, start: datetime, end: datetime) -> SpendLogs:
        self.calls.append((start, end))
        if self.fail:
            raise LiteLLMSpendError(None, "ConnectError")
        return SpendLogs(rows=list(self.rows))


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def service(source: Source, settings: Settings | None = None, clock: Clock | None = None) -> Any:
    return AiSpendService(
        cast(Any, source),
        cast(Any, settings or Settings()),
        clock=clock or Clock(),
        now=lambda: NOW,
    )


async def test_report_matches_recorded_log_to_the_call() -> None:
    report = await service(Source()).report(None, None, "day")
    assert (report.date_from, report.date_to) == (date(2026, 9, 15), date(2026, 10, 14))
    assert len(report.rows) == 30
    today = report.rows[-1]
    assert (today.key, today.calls, today.failed_calls, today.fallback_calls) == (
        "2026-10-14",
        len(PAGE["data"]),
        1,
        2,
    )
    assert today.cost_usd == pytest.approx(sum(r["spend"] for r in PAGE["data"]), abs=1e-12)
    assert [s.system for s in today.by_system] == ["crm", "erp", "other"]
    assert report.totals.calls == PAGE["total"]
    assert report.erp_connected is True
    assert report.truncated is False


@pytest.mark.parametrize(
    ("group", "keys"),
    [
        ("system", ["crm", "erp", "other"]),
        ("feature", ["dialog", "intake", "other", "kb-search"]),
        (
            "model",
            ["dialog-model", "fallback-model", "embed-model", "intake-model"],
        ),
    ],
)
async def test_report_groups(group: str, keys: list[str]) -> None:
    report = await service(Source()).report(date(2026, 10, 14), date(2026, 10, 14), group)
    assert [r.key for r in report.rows] == keys
    assert sum(r.calls for r in report.rows) == PAGE["total"]


async def test_budgets_and_overruns_per_system() -> None:
    # CRM потратила 2 вызова × 1.35e-05 + 2e-07: лимит ниже — превышение; ERP в лимите.
    report = await service(Source(), Settings(crm=0.00001, erp=1.0)).report(None, None, "day")
    crm, erp, other = report.systems
    assert (crm.system, crm.over_today, crm.days_over, crm.connected) == ("crm", True, 1, True)
    assert crm.today_usd == pytest.approx(2 * 1.35e-05 + 2e-07)
    assert (crm.fallback_calls, erp.fallback_calls) == (1, 1)
    assert (erp.over_today, erp.daily_usd, erp.today_calls) == (False, 1.0, 2)
    assert (other.system, other.daily_usd) == ("other", 0.0)
    assert [(o.system, o.day) for o in report.overruns] == [("crm", date(2026, 10, 14))]


async def test_erp_budget_overrun_is_visible() -> None:
    report = await service(Source(), Settings(crm=2.0, erp=0.00001)).report(None, None, "day")
    assert [o.system for o in report.overruns] == ["erp"]
    assert report.systems[1].over_today is True


async def test_no_erp_rows_means_not_connected() -> None:
    crm_only = [r for r in PAGE["data"] if "system=erp" not in r["request_tags"]]
    report = await service(Source(crm_only)).report(None, None, "system")
    assert report.erp_connected is False
    erp = report.systems[1]
    assert (erp.system, erp.connected, erp.period_calls) == ("erp", False, 0)


async def test_cache_60s_per_period() -> None:
    source, clock = Source(), Clock()
    svc = service(source, clock=clock)
    await svc.report(None, None, "day")
    await svc.report(None, None, "model")  # другой разрез — тот же журнал из кэша
    assert len(source.calls) == 1
    clock.t = 61
    await svc.report(None, None, "day")
    assert len(source.calls) == 2


async def test_past_period_fetches_today_separately() -> None:
    source = Source()
    report = await service(source).report(date(2026, 10, 1), date(2026, 10, 13), "day")
    assert len(source.calls) == 2  # период и сегодня (бюджет «сегодня»)
    assert report.totals.calls == 0
    assert report.systems[0].today_calls == 3


@pytest.mark.parametrize(
    ("first", "last"),
    [
        (date(2026, 7, 1), date(2026, 10, 14)),
        (date(2026, 10, 14), date(2026, 10, 13)),
        (date(2026, 10, 14), date(2026, 10, 15)),
    ],
)
async def test_bad_period_is_validation_error(first: date, last: date) -> None:
    with pytest.raises(ValidationFailedError) as caught:
        await service(Source()).report(first, last, "day")
    assert caught.value.details["reason"] == "ai_spend_period"


async def test_gateway_down_is_upstream_error_on_report_and_none_on_status() -> None:
    svc = service(Source(fail=True))
    with pytest.raises(UpstreamUnavailableError) as caught:
        await svc.report(None, None, "day")
    assert caught.value.details["reason"] == "litellm_unavailable"
    assert await svc.today_facts() is None


async def test_today_facts_for_system_status() -> None:
    facts = await service(Source(), Settings(crm=2.0, erp=1.0)).today_facts()
    assert facts is not None
    assert [(f.system, f.daily_usd) for f in facts] == [("crm", 2.0), ("erp", 1.0), ("other", 0.0)]
    assert facts[1] == AiBudgetFacts("erp", 1.35e-05, 1.0)


def page(rows: list[dict[str, Any]], *, page_no: int, pages: int, capped: bool = False) -> Any:
    return {
        "data": rows,
        "total": len(rows),
        "page": page_no,
        "page_size": 1000,
        "total_pages": pages,
        "total_is_capped": capped,
    }


async def test_client_pages_through_the_log_with_master_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        number = int(request.url.params["page"])
        return httpx.Response(
            200, json=page([{"request_id": f"p{number}"}], page_no=number, pages=2)
        )

    logs = await LiteLLMSpendLogs(
        AnyHttpUrl("http://litellm:4000"),
        SecretStr("sk-test-master"),
        transport=httpx.MockTransport(handler),
    ).fetch(datetime(2026, 10, 13, 19, tzinfo=UTC), datetime(2026, 10, 14, 19, tzinfo=UTC))
    assert [r["request_id"] for r in logs.rows] == ["p1", "p2"]
    first = seen[0]
    assert first.url.path == "/spend/logs/v2"
    assert first.headers["authorization"] == "Bearer sk-test-master"
    assert dict(first.url.params) == {
        "start_date": "2026-10-13 19:00:00",
        "end_date": "2026-10-14 19:00:01",
        "page": "1",
        "page_size": "1000",
        "sort_by": "startTime",
        "sort_order": "asc",
    }


async def test_client_splits_capped_window() -> None:
    windows: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start = request.url.params["start_date"]
        windows.append(start)
        capped = start == "2026-10-13 19:00:00" and request.url.params["end_date"].endswith(
            "19:00:01"
        )
        return httpx.Response(
            200, json=page([{"request_id": start}], page_no=1, pages=1, capped=capped)
        )

    logs = await LiteLLMSpendLogs(
        AnyHttpUrl("http://litellm:4000"), SecretStr("k"), transport=httpx.MockTransport(handler)
    ).fetch(datetime(2026, 10, 13, 19, tzinfo=UTC), datetime(2026, 10, 14, 19, tzinfo=UTC))
    assert windows == ["2026-10-13 19:00:00", "2026-10-13 19:00:00", "2026-10-14 07:00:00"]
    assert logs.truncated is False
    assert len(logs.rows) == 2


@pytest.mark.parametrize(
    ("status", "body", "detail"),
    [
        (401, RECORDED["unauthorized"]["body"], "unauthorized"),
        (400, RECORDED["bad_request"]["body"], "Start date and end date are required"),
        (500, "oops", "HTTP 500"),
    ],
)
async def test_client_errors_are_typed_without_key_hash(
    status: int, body: Any, detail: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    client = LiteLLMSpendLogs(
        AnyHttpUrl("http://litellm:4000"), SecretStr("k"), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(LiteLLMSpendError) as caught:
        await client.fetch(datetime(2026, 10, 14, tzinfo=UTC), datetime(2026, 10, 15, tzinfo=UTC))
    assert (caught.value.status, caught.value.detail) == (status, detail)
