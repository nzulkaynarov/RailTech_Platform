"""Строка «Ответы ИИ клиентам» центра внешних сервисов (W15-H3b): сбои агента по ответам бота."""

from datetime import UTC, datetime, timedelta

from app.domain import external_ai_replies as rules
from app.domain import external_cause as cause
from app.domain import external_registry as reg
from app.domain.external_ai_replies import AiFacts

NOW = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)


def _ago(minutes: float) -> datetime:
    return NOW - timedelta(minutes=minutes)


def test_no_answers_for_a_day_is_unknown_neither_recovery_nor_failure() -> None:
    result = rules.ai_replies(AiFacts(), NOW)
    assert result.status == "unknown"
    assert "нечего проверять" in result.summary


def test_the_last_answer_successful_holds_ok_even_when_there_was_no_traffic_for_hours() -> None:
    """Ночью обращений нет, но последний ответ успешный: строка ok, «Восстановлено» придёт."""
    result = rules.ai_replies(AiFacts(last_answered_at=_ago(7 * 60)), NOW)
    assert result.status == "ok"


def test_a_failure_without_a_later_answer_is_fail_with_the_cause_while_fresh() -> None:
    result = rules.ai_replies(
        AiFacts(failed=2, answered=3, last_failed_at=_ago(1), last_answered_at=_ago(3)), NOW
    )
    assert result.status == "fail"
    assert result.cause == "ai_unavailable"
    assert "2" in result.summary
    assert result.hint
    assert "администратору сервера" not in result.hint


def test_an_old_failure_with_no_later_traffic_is_unknown_not_a_standing_outage() -> None:
    """Последнее событие — сбой, но ему больше окна и ответов после него нет: данных нет."""
    result = rules.ai_replies(AiFacts(last_failed_at=_ago(60), last_answered_at=_ago(90)), NOW)
    assert result.status == "unknown"


def test_a_failure_followed_by_a_successful_answer_is_ok() -> None:
    result = rules.ai_replies(
        AiFacts(failed=1, answered=1, last_failed_at=_ago(3), last_answered_at=_ago(1)), NOW
    )
    assert result.status == "ok"


def test_registry_has_the_row_and_the_diagnosis_follows_the_policy() -> None:
    spec = next(s for s in reg.registry({}) if s.key == "ai_replies")
    assert spec.title == "Ответы ИИ клиентам"
    assert "cheap" in spec.tiers
    failing = rules.ai_replies(AiFacts(failed=1, last_failed_at=_ago(1)), NOW)
    short = cause.diagnose(spec, failing, cause.Context(fail_for=timedelta(minutes=2)))
    assert short.state == "unstable"  # короткий провал — без письма
    sustained = cause.diagnose(spec, failing, cause.Context(fail_for=timedelta(minutes=15)))
    assert sustained.state == "broken"
    assert sustained.cause_key == "ai_replies:ai_unavailable"
    quiet = cause.diagnose(spec, rules.ai_replies(AiFacts(), NOW), cause.Context())
    assert quiet.state == "not_checked"  # нет обращений — запись причины не закрывается


def test_failure_exactly_five_minutes_old_is_fail_and_one_second_older_is_unknown() -> None:
    edge = rules.ai_replies(AiFacts(failed=1, last_failed_at=_ago(5)), NOW)
    assert edge.status == "fail"
    past = rules.ai_replies(
        AiFacts(failed=0, last_failed_at=NOW - timedelta(minutes=5, seconds=1)), NOW
    )
    assert past.status == "unknown"
