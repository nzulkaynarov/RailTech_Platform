"""Правила обращений сотрудников к администратору (W15-H7): темы, статусы, значения, лимит."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.staff_tickets import (
    BODY_MAX_LEN,
    MAX_PER_HOUR,
    PAGE_MAX_LEN,
    REPLY_MAX_LEN,
    TicketValueError,
    after_reply,
    can_move,
    checked_body,
    checked_page,
    checked_reply,
    checked_status,
    checked_subject,
    clipped_role,
    id_of,
    number_of,
    rate_exceeded,
    reply_note,
    resolved_note,
    snippet,
    telegram_text,
    window_start,
)


@pytest.mark.parametrize("value", ["access", "notification", "template", "error", "other"])
def test_subject_known(value: str) -> None:
    assert checked_subject(value) == value


@pytest.mark.parametrize("value", ["", "ACCESS", "bug", "tickets"])
def test_subject_unknown(value: str) -> None:
    with pytest.raises(TicketValueError) as err:
        checked_subject(value)
    assert (err.value.reason, err.value.field) == ("ticket_subject_unknown", "subject")


@pytest.mark.parametrize("value", ["new", "in_progress", "resolved"])
def test_status_known(value: str) -> None:
    assert checked_status(value) == value


def test_status_unknown() -> None:
    with pytest.raises(TicketValueError) as err:
        checked_status("closed")
    assert err.value.reason == "ticket_status_unknown"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "ticket_text_empty"),
        ("   \n ", "ticket_text_empty"),
        ("я" * (BODY_MAX_LEN + 1), "ticket_text_too_long"),
    ],
)
def test_body_rejected(text: str, reason: str) -> None:
    with pytest.raises(TicketValueError) as err:
        checked_body(text)
    assert (err.value.reason, err.value.field) == (reason, "body")


def test_body_trimmed_and_limit_inclusive() -> None:
    assert checked_body("  Нужен доступ к «Расчёту»  ") == "Нужен доступ к «Расчёту»"
    assert len(checked_body("я" * BODY_MAX_LEN)) == BODY_MAX_LEN


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "ticket_reply_empty"),
        (" ", "ticket_reply_empty"),
        ("x" * (REPLY_MAX_LEN + 1), "ticket_reply_too_long"),
    ],
)
def test_reply_rejected(text: str, reason: str) -> None:
    with pytest.raises(TicketValueError) as err:
        checked_reply(text)
    assert err.value.reason == reason


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("/eds/inbox?panel=open&tab=resolution", "/eds/inbox?panel=open&tab=resolution"),
        ("  /crm/leads  ", "/crm/leads"),
        ("/eds/inbox/%D0%92%D0%A5-104%2F26", "/eds/inbox/%D0%92%D0%A5-104%2F26"),
    ],
)
def test_page_ok(page: str | None, expected: str | None) -> None:
    assert checked_page(page) == expected


@pytest.mark.parametrize(
    "page",
    [
        "https://evil.example/x",
        "//evil.example/x",
        "javascript:alert(1)",
        "eds/inbox",
        "/a\\b",
        "/<script>",
        "/line\nbreak",
        "/" + "a" * PAGE_MAX_LEN,
    ],
)
def test_page_rejected(page: str) -> None:
    with pytest.raises(TicketValueError) as err:
        checked_page(page)
    assert (err.value.reason, err.value.field) == ("ticket_page_invalid", "page")


def test_role_clipped() -> None:
    assert clipped_role(None) is None
    assert clipped_role("  ") is None
    assert clipped_role(" Менеджер ") == "Менеджер"
    assert len(clipped_role("р" * 500) or "") == 120


@pytest.mark.parametrize(
    ("current", "target", "ok"),
    [
        ("new", "in_progress", True),
        ("new", "resolved", True),
        ("in_progress", "resolved", True),
        ("resolved", "in_progress", True),
        ("in_progress", "new", False),
        ("resolved", "new", False),
        ("new", "new", False),
        ("resolved", "resolved", False),
        ("unknown", "resolved", False),
    ],
)
def test_status_moves(current: str, target: str, ok: bool) -> None:
    assert can_move(current, target) is ok


@pytest.mark.parametrize(
    ("current", "expected"),
    [("new", "in_progress"), ("in_progress", "in_progress"), ("resolved", "resolved")],
)
def test_reply_takes_new_ticket_into_work(current: str, expected: str) -> None:
    assert after_reply(current) == expected


def test_rate_limit_is_five_per_hour() -> None:
    assert MAX_PER_HOUR == 5
    assert not rate_exceeded(4)
    assert rate_exceeded(5)
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    assert window_start(now) == now - timedelta(hours=1)


def test_number_round_trip() -> None:
    assert number_of(12) == "ОБР-0012"
    assert number_of(12345) == "ОБР-12345"
    assert id_of("ОБР-0012") == 12
    assert id_of(" ОБР-12345 ") == 12345
    assert id_of("L-0012") is None
    assert id_of("ОБР-") is None


def test_snippet_flattens_and_cuts() -> None:
    assert snippet("строка\n\n  вторая") == "строка вторая"
    long = snippet("слово " * 100)
    assert len(long) <= 110
    assert long.endswith("…")


@pytest.mark.parametrize(
    ("language", "title"),
    [
        ("ru", "Ответ на обращение ОБР-0012"),
        ("uz", "ОБР-0012 murojaatiga javob"),
        ("en", "Reply to request ОБР-0012"),
        (None, "Ответ на обращение ОБР-0012"),
        ("de", "Ответ на обращение ОБР-0012"),
    ],
)
def test_reply_note_language(language: str | None, title: str) -> None:
    note = reply_note(language, "ОБР-0012", "Доступ выдан")
    assert note.title == title
    assert note.subtitle == "Доступ выдан"


def test_resolved_and_telegram_texts() -> None:
    assert resolved_note("ru", "ОБР-0012", "ok").title == "Обращение ОБР-0012 решено"
    text = telegram_text("en", "ОБР-0012", "Access granted", "https://p.example/help?ticket=12")
    for part in ("ОБР-0012", "Access granted", "https://p.example/help?ticket=12"):
        assert part in text
