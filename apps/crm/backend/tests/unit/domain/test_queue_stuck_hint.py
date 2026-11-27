"""Подсказка «Ящик давно не опрашивался» говорит правду о причине (ЗАВИС-1)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import external_cause as cause
from app.domain.external_mail_inbound import InboundFacts, mail_inbound
from app.domain.external_status import MailFacts, mail, stale_summary
from app.domain.system_status import HOSTING_WHO

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=5)


def _inbound(alive: bool | None):  # type: ignore[no-untyped-def]
    return mail_inbound(InboundFacts(True, last_poll_at=OLD, worker_alive=alive), NOW)


def test_dead_worker_sends_the_user_to_hosting() -> None:
    result = _inbound(False)
    assert result.cause == "queue_stuck"
    assert result.hint is not None
    assert HOSTING_WHO in result.hint
    assert "воркер CRM) не отвечает" in result.hint


def test_unknown_worker_state_is_treated_like_a_dead_worker() -> None:
    assert _inbound(None).cause == "queue_stuck"


def test_live_worker_means_a_stalled_job_and_no_advice_to_start_the_worker() -> None:
    result = _inbound(True)
    assert result.cause == "job_stalled"
    assert result.hint is not None
    assert "зависла" in result.hint
    assert "Запустить crm-worker" not in result.hint
    assert HOSTING_WHO not in result.hint


def test_job_stalled_is_fixed_by_the_admin_by_rechecking() -> None:
    route = cause.ROUTES["job_stalled"]
    assert (route.owner, route.action) == ("admin", "recheck")


def test_recent_poll_is_ok() -> None:
    result = mail_inbound(InboundFacts(True, last_poll_at=NOW, worker_alive=True), NOW)
    assert result.status == "ok"


@pytest.mark.parametrize(("alive", "expected"), [(True, "job_stalled"), (False, "queue_stuck")])
def test_stuck_mail_queue_follows_the_worker_state(alive: bool, expected: str) -> None:
    facts = MailFacts(True, queued=3, oldest_queued_at=OLD, worker_alive=alive)
    assert mail(facts, NOW).cause == expected


def test_stale_checks_with_a_live_worker_do_not_blame_hosting() -> None:
    _, hint = stale_summary(OLD, NOW, True)
    assert HOSTING_WHO not in hint
    _, hint_dead = stale_summary(OLD, NOW, False)
    assert HOSTING_WHO in hint_dead
