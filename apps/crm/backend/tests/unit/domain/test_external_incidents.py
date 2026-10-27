"""Инциденты, антиспам оповещений и сводка внешних сервисов (M3-CRM-12, ADR-0024)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import external_incidents as inc
from app.domain.external_incidents import Counts, OpenIncident

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
OPEN = OpenIncident(1, NOW - timedelta(minutes=5), None)


@pytest.mark.parametrize(
    ("open_incident", "status", "kwargs", "step"),
    [
        (None, "ok", {}, "none"),
        (None, "warn", {}, "none"),
        (None, "unknown", {}, "none"),
        (None, "off", {}, "none"),
        (None, "fail", {}, "open"),
        (None, "fail", {"sustained": False}, "none"),  # короткий провал — дребезг, не инцидент
        (OPEN, "fail", {"sustained": False}, "update"),
        (OPEN, "ok", {}, "close"),
        (OPEN, "ok", {"recovered": False}, "none"),  # ok короче 5 мин — инцидент ещё открыт
        (OPEN, "warn", {}, "none"),
        (
            OPEN,
            "unknown",
            {},
            "none",
        ),  # нет данных — инцидент не закрывается и не открывается заново
        (OPEN, "off", {}, "none"),
    ],
)
def test_transition(
    open_incident: OpenIncident | None, status: str, kwargs: dict[str, bool], step: str
) -> None:
    assert inc.transition(open_incident, status, **kwargs) == step  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("delta", "text"),
    [
        (timedelta(seconds=30), "меньше минуты"),
        (timedelta(minutes=12), "12 мин"),
        (timedelta(hours=2), "2 ч"),
        (timedelta(hours=2, minutes=5), "2 ч 5 мин"),
        (timedelta(days=3), "3 дн"),
        (timedelta(days=3, hours=4, minutes=10), "3 дн 4 ч"),
    ],
)
def test_duration_text(delta: timedelta, text: str) -> None:
    assert inc.duration_text(delta) == text


def test_count_and_uptime() -> None:
    counts = inc.count(
        [("ok", False), ("ok", False), ("fail", False), ("off", True), ("unknown", False)]
    )
    assert counts == Counts(ok=2, warn=0, fail=1, unknown=1, off=1, disabled=1)
    assert inc.uptime({"ok": 8, "warn": 1, "fail": 1, "unknown": 5}) == 0.9
    assert inc.uptime({"unknown": 3, "off": 2}) is None


def test_summary_component() -> None:
    never = inc.summary_component(Counts(), [], [], NOW, checked=False)
    assert never.status == "unknown"
    assert "раз в минуту" in never.reason
    fail = inc.summary_component(
        Counts(ok=9, fail=1), ["Telegram Bot API"], ["Почта"], NOW, checked=True
    )
    assert (fail.key, fail.status) == ("external_services", "fail")
    assert fail.reason == "Сбой: Telegram Bot API; в норме 9"
    warn = inc.summary_component(Counts(ok=9, warn=1, disabled=1), [], ["Почта"], NOW, checked=True)
    assert warn.status == "warn"
    assert warn.reason == "Внимание: Почта; в норме 9, выключено вручную 1"
    ok = inc.summary_component(Counts(ok=12), [], [], NOW, checked=True)
    assert (ok.status, ok.reason) == ("ok", "В норме: 12")
