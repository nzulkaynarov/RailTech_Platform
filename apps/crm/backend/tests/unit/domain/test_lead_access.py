"""Кто может «Отложить» открытую передачу (Q-018)."""

import pytest

from app.domain.lead_access import may_snooze

ME, OTHER = 1, 2


@pytest.mark.parametrize(
    ("assigned", "user", "is_admin", "allowed"),
    [
        (None, ME, False, True),  # общая очередь: любой с правом брать лидов
        (None, ME, True, True),
        (ME, ME, False, True),  # свой лид
        (OTHER, ME, False, False),  # у лида есть ответственный — не я
        (OTHER, ME, True, True),  # админ может всегда
    ],
)
def test_may_snooze(assigned: int | None, user: int, is_admin: bool, allowed: bool) -> None:
    assert may_snooze(assigned_user_id=assigned, user_id=user, is_admin=is_admin) is allowed
