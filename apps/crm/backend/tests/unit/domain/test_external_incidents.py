"""Инциденты, антиспам оповещений и сводка внешних сервисов (M3-CRM-12, ADR-0024)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import external_incidents as inc
from app.domain.external_incidents import Counts, OpenIncident

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
OPEN = OpenIncident(1, NOW - timedelta(minutes=5), None)


@pytest.mark.parametrize(
    ("open_incident", "status", "step"),
    [
        (None, "ok", "none"),
        (None, "warn", "none"),
        (None, "unknown", "none"),
        (None, "off", "none"),
        (None, "fail", "open"),
        (OPEN, "fail", "update"),
        (OPEN, "ok", "close"),
        (OPEN, "warn", "close"),
        (OPEN, "unknown", "none"),  # нет данных — инцидент не закрывается и не открывается заново
        (OPEN, "off", "none"),
    ],
)
def test_transition(open_incident: OpenIncident | None, status: str, step: str) -> None:
    assert inc.transition(open_incident, status) == step  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("last", "due"),
    [
        (None, True),
        (NOW - timedelta(minutes=61), True),
        (NOW - timedelta(minutes=60), True),
        (NOW - timedelta(minutes=59), False),
        (NOW - timedelta(minutes=1), False),
    ],
)
def test_failure_alert_antispam(last: datetime | None, due: bool) -> None:
    assert inc.failure_alert_due(last, NOW, timedelta(minutes=60)) is due


def test_recovery_alert_only_if_failure_was_alerted() -> None:
    assert inc.recovery_alert_due(NOW) is True
    assert inc.recovery_alert_due(None) is False


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


def test_alert_texts_have_what_to_do_and_link() -> None:
    failure = inc.failure_alert(
        "Telegram Bot API", "Нет связи", "ConnectError", "Проверьте сеть", "https://crm/x"
    )
    assert failure.subject == "⚠️ Сбой: Telegram Bot API"
    assert failure.plain.splitlines()[1:] == [
        "Нет связи",
        "Ошибка: ConnectError",
        "Что сделать: Проверьте сеть",
        "Открыть: https://crm/x",
    ]
    recovery = inc.recovery_alert("Почтовый релей", timedelta(minutes=7), "https://crm/y")
    assert recovery.subject == "✅ Восстановлено: Почтовый релей"
    assert "Сбой длился 7 мин." in recovery.plain


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
