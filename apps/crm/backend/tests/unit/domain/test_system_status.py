"""Экран «Состояние системы»: правила статуса по фактам."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import system_status as rules
from app.domain.alerts import QUEUE_LIMIT
from app.domain.system_status import AlertRow, QueueFacts

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def test_dependencies_ok_and_fail() -> None:
    result = {c.key: c for c in rules.dependencies({"database": True, "s3": False}, NOW)}
    assert result["database"].status == "ok"
    assert result["s3"].status == "fail"
    assert "S3" in result["s3"].reason
    assert "litellm" not in result


def test_models_unknown_until_monitor_probed() -> None:
    [only] = rules.models([AlertRow("budget", False, None, NOW)])
    assert only.status == "unknown"
    assert only.checked_at is None


def test_models_from_monitor_rows() -> None:
    rows = [
        AlertRow("model:fallback-model", False, None, NOW),
        AlertRow("model:dialog-model", True, "закончились кредиты", NOW),
    ]
    result = rules.models(rows)
    assert [(c.key, c.status) for c in result] == [
        ("model:dialog-model", "fail"),
        ("model:fallback-model", "ok"),
    ]
    assert result[0].reason == "закончились кредиты"


@pytest.mark.parametrize(
    ("facts", "status"),
    [
        (QueueFacts(0, 0, 0), "ok"),
        (QueueFacts(QUEUE_LIMIT + 1, 0, 0), "warn"),
        (QueueFacts(0, 2, 0), "warn"),
        (QueueFacts(0, 0, 1), "warn"),
    ],
    ids=["idle", "backlog", "stalled", "failed"],
)
def test_queue(facts: QueueFacts, status: str) -> None:
    assert rules.queue(facts, NOW).status == status


@pytest.mark.parametrize(
    ("running", "status"), [(None, "fail"), (False, "fail"), (True, "ok")], ids=str
)
def test_bot(running: bool | None, status: str) -> None:
    assert rules.bot(running, "polling", NOW).status == status


def test_channel_and_backup_and_secrets() -> None:
    assert rules.channel(None, NOW).status == "warn"
    assert rules.channel(-100, NOW).status == "ok"
    assert rules.backup(NOW, available=False, last_success=None).status == "unknown"
    assert rules.backup(NOW, available=True, last_success=None).status == "fail"
    assert rules.backup(NOW, available=True, last_success=NOW - timedelta(hours=2)).status == "ok"
    assert (
        rules.backup(NOW, available=True, last_success=NOW - timedelta(hours=30)).status == "warn"
    )
    missing = rules.secrets(["JWT_SECRET"], NOW)
    assert missing.status == "fail"
    assert "JWT_SECRET" in missing.reason
    assert rules.secrets([], NOW).status == "ok"


def test_budget_warns_on_active_alert() -> None:
    assert rules.budget([AlertRow("budget", True, "$1.8 из $2", NOW)], NOW).status == "warn"
    assert rules.budget([], NOW).status == "ok"
