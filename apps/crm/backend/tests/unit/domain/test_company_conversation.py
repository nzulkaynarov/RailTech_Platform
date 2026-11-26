"""КОНТР-1а: беседа известного контакта компании — признак, «непрочитанное» и личное уведомление."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.api.v1.leads import _unread
from app.domain.company_conversation import MARK_KEY, is_company_conversation
from app.domain.staff_notify import Staff, lead_dm_target
from app.models.leads import Lead

MARK = {MARK_KEY: {"client_id": 1}}


@pytest.mark.parametrize(
    ("mode", "user", "client", "qual", "expected"),
    [
        ("bot", 5, 1, MARK, True),
        ("bot", None, 1, MARK, False),
        ("bot", 5, None, MARK, False),
        ("bot", 5, 1, {}, False),
        ("human", 5, 1, MARK, False),
        ("paused", 5, 1, MARK, False),
    ],
)
def test_marker(
    mode: str, user: int | None, client: int | None, qual: dict[str, Any], expected: bool
) -> None:
    assert is_company_conversation(mode, user, client, qual) is expected


def _lead(**kw: object) -> Lead:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "owner_mode": "bot",
        "assigned_user_id": 5,
        "client_id": 1,
        "qualification": MARK,
        "last_lead_msg_at": now,
        "last_human_msg_at": now - timedelta(hours=1),
    }
    return Lead(**{**base, **kw})


def test_company_conversation_is_unread_until_a_person_answers() -> None:
    assert _unread(_lead()) is True
    assert _unread(_lead(last_human_msg_at=datetime.now(UTC) + timedelta(minutes=1))) is False
    assert _unread(_lead(qualification={})) is False  # обычный лид с ботом — не «ваше»


def test_owner_gets_a_personal_notice_only_for_company_conversation() -> None:
    manager = Staff(5, ("manager",), True, 77, True, True)
    assert lead_dm_target("bot", manager, company_conversation=True) == 77
    assert lead_dm_target("bot", manager) is None
    assert lead_dm_target("human", manager) == 77
