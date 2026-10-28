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
    new_lead_recipients,
    web_lead_dm_text,
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
    url = "https://platform.example.com/crm/leads?lead=L-0042&panel=open&tab=card"
    text = lead_dm_text("Иван", "Когда  будет\nпоставка?", url, 42)
    assert text == (
        "💬 Новое сообщение от лида #42 Иван: «Когда будет поставка?» — "
        f'<a href="{url.replace("&", "&amp;")}">открыть</a>'
    )


def test_lead_dm_text_escapes_html() -> None:
    text = lead_dm_text("<b>", "a < b", "https://x", 1)
    assert "&lt;b&gt;" in text
    assert "a &lt; b" in text


def test_lead_dm_text_truncates_and_names_unnamed() -> None:
    text = lead_dm_text("", "a" * 500, "http://localhost", 5)
    assert "лида #5:" in text
    preview = text.split("«", 1)[1].split("»", 1)[0]
    assert len(preview) == PREVIEW_CHARS
    assert preview.endswith("…")


def test_lead_dm_text_attachment_only() -> None:
    assert "(вложение)" in lead_dm_text("Иван", "  ", "http://x", 1)


def _staff(
    user_id: int, roles: tuple[str, ...], tg: int | None, *, active: bool = True, leads: bool = True
) -> Staff:
    return Staff(user_id, roles, active, tg, True, leads)


def test_new_lead_recipients_are_subscribed_active_managers_and_admins_with_telegram() -> None:
    staff = [
        _staff(1, ("manager",), 101),
        _staff(2, ("admin",), 102),
        _staff(3, ("manager",), None),  # Telegram не привязан
        _staff(4, ("manager",), 104, leads=False),  # отписан от лидов
        _staff(5, ("manager",), 105, active=False),
        _staff(6, ("viewer",), 106),
        _staff(7, ("manager",), 101),  # тот же Telegram — без дубля
    ]
    assert new_lead_recipients(staff) == [101, 102]


def test_web_lead_text_escapes_the_form_input_and_links_to_the_card() -> None:
    text = web_lead_dm_text(
        "{who}|{need}|{minutes}|{link}|{lead_id}",
        name="<b>Али</b>",
        company="ООО & Ко",
        need="Нужен <script>расчёт</script>",
        minutes=15,
        lead_url="https://platform.example.com/crm/leads?lead=L-0007&panel=open&tab=card",
        lead_id=7,
    )
    assert "<b>" not in text
    assert "<script>" not in text
    assert "&lt;b&gt;Али&lt;/b&gt; (ООО &amp; Ко)" in text
    assert (
        'href="https://platform.example.com/crm/leads?lead=L-0007&amp;panel=open&amp;tab=card"'
        in text
    )
    assert "|15|" in text


def test_web_lead_text_without_name_and_need() -> None:
    text = web_lead_dm_text(
        "{who}|{need}", name="", company=None, need=None, minutes=5, lead_url="https://c", lead_id=9
    )
    assert text == "#9|без описания"
