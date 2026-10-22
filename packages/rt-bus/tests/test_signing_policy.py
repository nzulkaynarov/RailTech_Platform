"""Подпись HMAC v2 и окно (L3, L4); расписание повторов, jitter, Retry-After, классификация ответов."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest

from rt_bus import RetryPolicy, env_secrets, secret_env_name, sign, verify
from rt_bus.policy import Verdict, classify_status, parse_retry_after
from rt_bus.signing import format_timestamp, window_problem

from .conftest import T0

BODY = b'{"id":"x"}'


def test_signature_v2_covers_id_timestamp_body() -> None:
    ts = format_timestamp(T0)
    assert ts == "2026-10-23T09:00:00Z"
    signature = sign("k1", "evt-1", ts, BODY)
    assert signature.startswith("sha256=")
    assert verify(["k1"], "evt-1", ts, BODY, signature)
    assert not verify(["k1"], "evt-2", ts, BODY, signature)
    assert not verify(["k1"], "evt-1", "2026-10-23T09:00:01Z", BODY, signature)
    assert not verify(["k1"], "evt-1", ts, BODY + b" ", signature)
    assert not verify(["k2"], "evt-1", ts, BODY, signature)
    assert not verify([], "evt-1", ts, BODY, signature)


def test_rotation_accepts_any_current_secret() -> None:
    ts = format_timestamp(T0)
    old = sign("old", "e", ts, BODY)
    new = sign("new", "e", ts, BODY)
    assert verify(["new", "old"], "e", ts, BODY, old)
    assert verify(["new", "old"], "e", ts, BODY, new)
    assert not verify(["new"], "e", ts, BODY, old)


def test_window() -> None:
    assert window_problem("2026-10-23T09:05:00Z", T0) is None
    assert window_problem("2026-10-23T08:55:00Z", T0) is None
    assert "window" in (window_problem("2026-10-23T09:05:01Z", T0) or "")
    assert "window" in (window_problem("2026-10-23T08:54:59Z", T0) or "")
    assert window_problem("2026-10-23T09:00:00", T0) == "X-RT-Timestamp has no UTC offset"
    assert window_problem("yesterday", T0) == "X-RT-Timestamp is not ISO 8601"


def test_env_secret_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    assert secret_env_name("platform-bff", "crm") == "RT_BUS_SECRET_PLATFORM_BFF_CRM"
    monkeypatch.setenv("RT_BUS_SECRET_ERP_CRM", " first , second ,,")
    assert env_secrets("erp", "crm") == ["first", "second"]
    assert env_secrets("erp", "eds") == []


def test_schedule_with_jitter_and_dead_after_sixth_retry() -> None:
    policy = RetryPolicy()
    rng = random.Random(1)
    expected = [30, 120, 600, 3600, 21600, 86400]
    for attempts, base in enumerate(expected, start=1):
        delays = [policy.delay_after(attempts, rng) for _ in range(50)]
        assert all(d is not None and base * 0.8 <= d <= base * 1.2 for d in delays)
        assert len({round(d or 0, 6) for d in delays}) > 1  # jitter есть
    assert policy.max_attempts == 7
    assert policy.delay_after(7, rng) is None  # шестой повтор не удался — dead


def test_retry_after_replaces_step_within_bounds() -> None:
    policy = RetryPolicy()
    rng = random.Random(1)
    assert policy.delay_after(1, rng, retry_after=90) == 90
    assert policy.delay_after(1, rng, retry_after=0) == 1
    assert policy.delay_after(1, rng, retry_after=10**7) == 86400
    assert policy.delay_after(7, rng, retry_after=5) is None
    assert parse_retry_after("120", T0) == 120
    assert parse_retry_after(format_http_date(T0 + timedelta(seconds=45)), T0) == 45
    assert parse_retry_after("soon", T0) is None
    assert parse_retry_after(None, T0) is None


def format_http_date(moment: datetime) -> str:
    from email.utils import format_datetime

    return format_datetime(moment, usegmt=True)


@pytest.mark.parametrize(
    ("code", "verdict"),
    [
        (200, Verdict.DELIVERED),
        (202, Verdict.DELIVERED),
        (400, Verdict.DEAD),
        (404, Verdict.DEAD),
        (410, Verdict.DEAD),
        (413, Verdict.DEAD),
        (415, Verdict.DEAD),
        (422, Verdict.DEAD),
        (401, Verdict.RETRY),
        (408, Verdict.RETRY),
        (409, Verdict.RETRY),
        (429, Verdict.RETRY),
        (500, Verdict.RETRY),
        (503, Verdict.RETRY),
        (301, Verdict.RETRY),
    ],
)
def test_classification(code: int, verdict: Verdict) -> None:
    assert classify_status(code) is verdict
