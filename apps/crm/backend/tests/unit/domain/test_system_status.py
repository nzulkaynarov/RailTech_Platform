"""Экран «Состояние системы»: правила статуса по фактам."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import system_status as rules
from app.domain.alerts import QUEUE_LIMIT
from app.domain.system_status import AlertRow, BackupFacts, BotFacts, Component, QueueFacts

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
    assert result[0].reason.startswith("закончились кредиты")


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
    ("facts", "mode", "status", "needle"),
    [
        (None, "polling", "fail", "Токен"),
        (BotFacts(False, "none", None), "polling", "fail", "Токен"),
        (BotFacts(False, "db", "TelegramUnauthorizedError"), "polling", "fail", "Unauthorized"),
        (BotFacts(True, "env", None), "polling", "ok", ""),
        (BotFacts(True, "env", None), "disabled", "fail", "выключен"),
    ],
    ids=["no-supervisor", "no-token", "crashed", "running", "disabled"],
)
def test_bot(facts: BotFacts | None, mode: str, status: str, needle: str) -> None:
    result = rules.bot(facts, mode, NOW)
    assert result.status == status
    assert needle in result.reason
    assert "перезапустите api" not in result.reason


@pytest.mark.parametrize(
    ("url", "problem"),
    [
        ("https://crm.railtech.uz", False),
        ("https://crm.railtech.uz/", False),
        ("http://localhost", True),
        ("https://localhost:8443", True),
        ("http://127.0.0.1:5173", True),
        ("http://crm.railtech.uz", True),
        ("", True),
    ],
)
def test_crm_url_problem(url: str, problem: bool) -> None:
    assert (rules.crm_url_problem(url) is not None) is problem
    assert rules.crm_url(url, NOW).status == ("warn" if problem else "ok")


def _backup(
    mounted: bool = True,
    alive: bool = True,
    last: datetime | None = NOW - timedelta(hours=2),
    asked: datetime | None = None,
) -> str:
    return rules.backup(NOW, BackupFacts(mounted, alive, last, asked)).status


def test_channel_and_backup_and_secrets() -> None:
    assert rules.channel(None, NOW).status == "warn"
    assert rules.channel(-100, NOW).status == "ok"
    assert _backup(mounted=False) == "unknown"
    assert _backup(alive=False) == "fail"
    assert _backup(last=None) == "fail"
    assert _backup() == "ok"
    assert _backup(last=NOW - timedelta(hours=30)) == "warn"
    assert _backup(asked=NOW - timedelta(minutes=5)) == "warn"
    assert _backup(asked=NOW - timedelta(minutes=1)) == "ok"
    assert _backup(asked=NOW - timedelta(hours=3)) == "ok"  # копия после запроса уже есть
    missing = rules.secrets(["JWT_SECRET"], NOW)
    assert missing.status == "fail"
    assert "JWT_SECRET" in missing.reason
    assert rules.secrets([], NOW).status == "ok"
    assert rules.secrets([], NOW, secrets_key=False).status == "warn"


def test_request_answered_by_newer_success() -> None:
    asked = NOW - timedelta(minutes=10)
    done = BackupFacts(True, True, NOW - timedelta(minutes=3), asked)
    assert not rules.request_unanswered(NOW, done)


def test_ordered_puts_failures_first() -> None:
    comps = [Component(k, k, st, "", NOW) for k, st in [("a", "ok"), ("b", "warn"), ("c", "fail")]]
    assert [c.key for c in rules.ordered(comps)] == ["c", "b", "a"]


def test_model_titles_are_roles() -> None:
    [row] = rules.models([AlertRow("model:dialog-model", True, "нет кредитов", NOW)])
    assert row.title == "Модель ИИ: Диалог"
    assert row.reason.startswith("нет кредитов")


def test_budget_warns_on_active_alert() -> None:
    assert rules.budget([AlertRow("budget", True, "$1.8 из $2", NOW)], NOW).status == "warn"
    assert rules.budget([], NOW).status == "ok"
