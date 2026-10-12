"""«Вернуть из отложенных»: передача снова открыта, SLA заново (SPEC §10.1)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.errors import ForbiddenError, ValidationFailedError
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.schemas.settings import AppSettings
from app.security.principal import Principal
from app.services import lead_snooze

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)  # понедельник, рабочее время Ташкента
OWNER = Principal(user_id=7, full_name="Анна", roles=("manager",))
OTHER = Principal(user_id=8, full_name="Борис", roles=("manager",))
ADMIN = Principal(user_id=1, full_name="Админ", roles=("admin",))


@pytest.mark.parametrize(
    ("priority", "sla_reset"), [("hot", True), ("warm", True), ("info", False)]
)
def test_reopen_resets_sla_for_sla_priorities(priority: str, sla_reset: bool) -> None:
    old_due = NOW - timedelta(hours=3)
    escalation = Escalation(
        status="snoozed",
        priority=priority,
        snoozed_until=NOW + timedelta(hours=1),
        sla_due_at=old_due,
        sla_notified_at=old_due,
    )
    lead = Lead(snoozed_until=NOW + timedelta(hours=1))
    lead_snooze.reopen(escalation, lead, NOW, AppSettings())
    assert (escalation.status, escalation.snoozed_until, lead.snoozed_until) == ("open", None, None)
    if sla_reset:
        assert escalation.sla_due_at is not None
        assert escalation.sla_due_at > NOW
        assert escalation.sla_notified_at is None
    else:
        assert escalation.sla_due_at == old_due


@pytest.mark.parametrize(
    ("assigned", "who", "allowed"),
    [(None, OTHER, True), (7, OWNER, True), (7, OTHER, False), (7, ADMIN, True)],
)
def test_check_snoozer(assigned: int | None, who: Principal, allowed: bool) -> None:
    lead = Lead(assigned_user_id=assigned)
    if allowed:
        lead_snooze.check_snoozer(lead, who)
    else:
        with pytest.raises(ForbiddenError):
            lead_snooze.check_snoozer(lead, who)


@pytest.mark.parametrize(
    ("delta", "ok"),
    [
        (timedelta(hours=1), True),
        (timedelta(days=7), True),
        (timedelta(0), False),
        (timedelta(days=8), False),
    ],
)
def test_check_until(delta: timedelta, ok: bool) -> None:
    if ok:
        lead_snooze.check_until(NOW + delta, NOW)
    else:
        with pytest.raises(ValidationFailedError):
            lead_snooze.check_until(NOW + delta, NOW)
