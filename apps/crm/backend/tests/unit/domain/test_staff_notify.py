"""Личные уведомления сотрудникам (Q-010): кому писать, троттлинг, текст."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.staff_notify import (
    PREVIEW_CHARS,
    Staff,
    alert_recipients,
    lead_dm_due,
    lead_dm_target,
    lead_dm_text,
)

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
WINDOW = timedelta(minutes=5)


def staff(
    uid: int = 1,
    roles: tuple[str, ...] = ("admin",),
    *,
    active: bool = True,
    tg: int | None = 100,
    system: bool = True,
    leads: bool = True,
) -> Staff:
    return Staff(uid, roles, active, tg, system, leads)


@pytest.mark.parametrize(
    ("people", "expected"),
    [
        ([staff()], [100]),
        ([staff(roles=("manager",))], []),
        ([staff(active=False)], []),
        ([staff(tg=None)], []),
        ([staff(system=False)], []),
        ([staff(1, tg=100), staff(2, ("admin", "manager"), tg=200)], [100, 200]),
        ([staff(1, tg=100), staff(2, tg=100)], [100]),
        ([], []),
    ],
    ids=[
        "admin",
        "manager-not-alerted",
        "inactive",
        "no-telegram",
        "unsubscribed",
        "two-admins",
        "dedupe",
        "nobody",
    ],
)
def test_alert_recipients(people: list[Staff], expected: list[int]) -> None:
    assert alert_recipients(people) == expected


@pytest.mark.parametrize(
    ("mode", "manager", "expected"),
    [
        ("human", staff(roles=("manager",), tg=7), 7),
        ("bot", staff(roles=("manager",), tg=7), None),
        ("paused", staff(roles=("manager",), tg=7), None),
        ("human", None, None),
        ("human", staff(roles=("manager",), tg=None), None),
        ("human", staff(roles=("manager",), tg=7, leads=False), None),
        ("human", staff(roles=("manager",), tg=7, active=False), None),
    ],
    ids=["owner", "bot-mode", "paused", "no-owner", "no-telegram", "unsubscribed", "inactive"],
)
def test_lead_dm_target(mode: str, manager: Staff | None, expected: int | None) -> None:
    assert lead_dm_target(mode, manager) == expected


@pytest.mark.parametrize(
    ("last", "expected"),
    [
        (None, True),
        (NOW - timedelta(minutes=1), False),
        (NOW - timedelta(minutes=4, seconds=59), False),
        (NOW - WINDOW, True),
        (NOW - timedelta(hours=1), True),
    ],
    ids=["first", "1-min-ago", "just-inside", "boundary", "long-ago"],
)
def test_lead_dm_due(last: datetime | None, expected: bool) -> None:
    assert lead_dm_due(last, NOW, WINDOW) is expected


def test_lead_dm_text_has_preview_and_link() -> None:
    text = lead_dm_text("Иван", "Когда  будет\nпоставка?", "https://crm.example.com/", 42)
    assert text == (
        "💬 Новое сообщение от Иван: «Когда будет поставка?» — открыть: "
        "https://crm.example.com/leads/42"
    )


def test_lead_dm_text_truncates_and_names_unnamed() -> None:
    text = lead_dm_text("", "a" * 500, "http://localhost", 5)
    assert "Лид #5" in text
    preview = text.split("«", 1)[1].split("»", 1)[0]
    assert len(preview) == PREVIEW_CHARS
    assert preview.endswith("…")


def test_lead_dm_text_attachment_only() -> None:
    assert "(вложение)" in lead_dm_text("Иван", "  ", "http://x", 1)
