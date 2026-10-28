"""Внешняя копия бэкапов на Google Drive (OPS-GDRIVE): правила строки и кто исправляет, без сети."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.domain import external_cause as cause
from app.domain import external_registry as reg
from app.domain.external_cause import Context
from app.domain.external_offsite import (
    KEY,
    OWNER_WHO,
    OffsiteFacts,
    offsite_backup,
    parse,
    size_text,
)
from app.domain.system_status import HOSTING_WHO, hosting_ask

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
SPEC = {s.key: s for s in reg.registry({})}[KEY]
GB = 1073741824


def ago(**delta: float) -> datetime:
    return NOW - timedelta(**delta)


def status(**fields: Any) -> bytes:
    """status.json, как его пишет infra/offsite/gdrive-sync.sh."""
    body: dict[str, Any] = {
        "schema": 1,
        "result": "ok",
        "reason": "",
        "message": "",
        "detail": "",
        "attempt_at": "2026-10-27T23:05:00Z",
        "last_success_at": "2026-10-27T23:05:00Z",
        "duration_s": 300,
        "bytes": 13314398618,
        "objects": 20160,
        "base_backups": 15,
        "oldest_base_at": "2026-10-13T21:04:11Z",
        "newest_base_at": "2026-10-27T21:03:52Z",
        "quota_bytes": 100 * GB,
        "keep_days": 14,
        "prefix": "pg17",
    }
    body.update(fields)
    return json.dumps(body).encode()


def diagnose(facts: OffsiteFacts, **ctx: Any) -> cause.Diagnosis:
    return cause.diagnose(SPEC, offsite_backup(facts, NOW), Context(**ctx))


def test_registry_row_is_an_ensemble_row_checked_every_minute() -> None:
    assert SPEC.title == "Внешняя копия бэкапов"
    assert SPEC.system == "ensemble"
    assert SPEC.tiers == ("cheap",)


def test_fresh_copy_is_ok_with_volume_backups_and_window() -> None:
    result = offsite_backup(parse(status()), NOW)
    assert result.status == "ok"
    assert result.summary == (
        "Копия на Google Drive обновлена 12 ч назад: 12,4 ГБ, базовых копий 15 (с 13.10)"
    )
    assert result.metrics["last_success_hours"] == 12.9
    assert result.metrics["quota_pct"] == 12
    assert result.cause is None


def test_last_success_older_than_26_hours_is_a_failure_for_hosting() -> None:
    stale = parse(status(attempt_at="2026-10-27T09:00:00Z", last_success_at="2026-10-27T09:00:00Z"))
    result = offsite_backup(stale, NOW)
    assert result.status == "fail"
    assert "27 ч назад" in result.summary
    assert result.cause == "server_down"
    assert result.hint
    assert HOSTING_WHO in result.hint
    assert "offsite-backup" in result.hint


def test_25_hours_is_still_ok() -> None:
    fresh = parse(status(last_success_at="2026-10-27T11:00:00Z"))
    assert offsite_backup(fresh, NOW).status == "ok"


def test_failed_last_attempt_is_fail_even_with_a_recent_success() -> None:
    failed = parse(
        status(
            result="fail",
            reason="network",
            message="Нет связи с Google Drive: сеть сервера или ограничение запросов",
            detail="ERROR : dial tcp: i/o timeout",
            attempt_at="2026-10-28T11:30:00Z",
            last_success_at="2026-10-28T00:00:00Z",
        )
    )
    result = offsite_backup(failed, NOW)
    assert result.status == "fail"
    assert result.summary.startswith("Внешняя копия бэкапов не обновляется: Нет связи")
    assert result.error == "ERROR : dial tcp: i/o timeout"
    assert result.cause == "server_down"
    assert result.hint
    assert "Последняя успешная копия 12 ч назад" in result.hint


@pytest.mark.parametrize(
    ("reason", "expected_cause", "todo"),
    [
        ("access", "offsite_access", "«Менеджер контента»"),
        ("not_shared_drive", "offsite_access", "общем диске (Shared Drive)"),
        ("quota", "offsite_quota", "OFFSITE_MAX_GB"),
    ],
)
def test_drive_refusals_are_fixed_by_the_owner(reason: str, expected_cause: str, todo: str) -> None:
    failed = parse(status(result="fail", reason=reason, message="Google Drive отказал"))
    result = offsite_backup(failed, NOW)
    assert result.status == "fail"
    assert result.cause == expected_cause
    assert result.hint
    assert OWNER_WHO in result.hint
    assert todo in result.hint


@pytest.mark.parametrize("reason", ["no_key", "bad_key", "no_folder"])
def test_not_configured_says_who_fixes_and_what_to_do(reason: str) -> None:
    facts = parse(
        status(
            result="not_configured",
            reason=reason,
            message="Нет ключа сервисного аккаунта Google",
            last_success_at=None,
            bytes=None,
        )
    )
    result = offsite_backup(facts, NOW)
    assert result.status == "off"
    assert result.cause == "offsite_not_configured"
    assert result.summary.startswith("Внешняя копия бэкапов на Google Drive не настроена")
    assert result.hint
    assert "Кто исправляет: владелец" in result.hint
    assert "/opt/rt/secrets/gdrive-sa.json" in result.hint
    assert "OFFSITE_GDRIVE_FOLDER_ID" in result.hint
    assert "docs/runbooks/offsite-gdrive.md" in result.hint
    assert result.metrics["reason"] == reason


def test_no_status_file_yet_is_not_configured_too() -> None:
    result = offsite_backup(OffsiteFacts(missing=True), NOW)
    assert result.status == "off"
    assert result.cause == "offsite_not_configured"
    assert result.metrics["reason"] == "no_status"


def test_unreadable_status_is_not_checked_with_a_hosting_hint() -> None:
    result = offsite_backup(OffsiteFacts(error="AccessDenied"), NOW)
    assert result.status == "unknown"
    assert result.hint
    assert "offsite/status.json" in result.hint


@pytest.mark.parametrize(
    "raw", [b"not json", b"[]", json.dumps({"result": "maybe"}).encode(), b'{"result": 1}']
)
def test_broken_or_foreign_status_file_is_not_checked(raw: bytes) -> None:
    assert parse(raw).error == "bad_status_json"


def test_quota_near_the_limit_is_a_warning_for_the_owner() -> None:
    result = offsite_backup(parse(status(bytes=85 * GB)), NOW)
    assert result.status == "warn"
    assert result.cause == "offsite_quota"
    assert "85 %" in result.summary


def test_success_without_any_copy_on_record_is_a_failure() -> None:
    result = offsite_backup(parse(status(result="fail", reason="error", last_success_at=None)), NOW)
    assert result.status == "fail"
    assert result.hint
    assert "Успешной копии ещё не было" in result.hint


@pytest.mark.parametrize(
    ("value", "text"),
    [(0, "0 МБ"), (350 * 1048576, "350 МБ"), (1023 * 1048576, "1023 МБ"), (13314398618, "12,4 ГБ")],
)
def test_size_text(value: int, text: str) -> None:
    assert size_text(value) == text


# --- кто исправляет и «Сломано» по общей политике H3 ---------------------------------------------


def test_not_configured_row_is_not_configured_for_the_owner_and_grey_on_the_stand() -> None:
    facts = parse(status(result="not_configured", reason="no_key", last_success_at=None))
    prod = diagnose(facts)
    assert (prod.state, prod.owner, prod.action) == ("not_configured", "owner", "write_owner")
    assert prod.detail
    assert "Кто исправляет: владелец" in prod.detail
    assert diagnose(facts, stand=True).state == "expected"


def test_access_refusal_is_broken_after_15_minutes_and_routed_to_the_owner() -> None:
    failed = parse(status(result="fail", reason="access", message="Google Drive отказал в доступе"))
    assert diagnose(failed, fail_for=timedelta(minutes=5)).state == "unstable"
    d = diagnose(failed, fail_for=timedelta(minutes=16))
    assert (d.state, d.owner, d.action) == ("broken", "owner", "write_owner")
    group = cause.build_groups([d])[0]
    assert group.message
    assert "Google Drive отказал в доступе" in group.message


def test_network_failure_is_broken_for_hosting_with_a_ready_message() -> None:
    failed = parse(status(result="fail", reason="network", message="Нет связи с Google Drive"))
    d = diagnose(failed, fail_for=timedelta(minutes=20))
    assert (d.state, d.owner, d.action) == ("broken", "hosting", "write_hosting")
    assert hosting_ask(d.detail)
