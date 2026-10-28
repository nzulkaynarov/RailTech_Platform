"""Экран «Состояние системы»: правила статуса по фактам."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.domain import system_status as rules
from app.domain.alerts import QUEUE_LIMIT
from app.domain.system_status import (
    AlertRow,
    BackupFacts,
    BotFacts,
    Component,
    ErpFacts,
    PlatformUrlFacts,
    QueueFacts,
    Status,
)

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
    ("facts", "text"),
    [
        (
            QueueFacts(0, 1, 1),
            "1 задача выполняется дольше 15 минут; 1 задача упала за последний час",
        ),
        (
            QueueFacts(0, 2, 3),
            "2 задачи выполняются дольше 15 минут; 3 задачи упали за последний час",
        ),
        (
            QueueFacts(0, 5, 11),
            "5 задач выполняются дольше 15 минут; 11 задач упали за последний час",
        ),
        (QueueFacts(101, 21, 0), "21 задача выполняется дольше 15 минут"),
    ],
    ids=["one", "few", "many", "twenty-one"],
)
def test_queue_text_agrees_in_number(facts: QueueFacts, text: str) -> None:
    """W15-G-7: «1 задач выполняются» — нет; число согласовано со словом."""
    reason = rules.queue(facts, NOW).reason
    assert text in reason
    assert not re.search(r"(?<![\d])1 задач ", reason)


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
        (
            BotFacts(False, "db", "TelegramUnauthorizedError"),
            "polling",
            "fail",
            "не принимает токен",
        ),
        (BotFacts(True, "env", None), "polling", "ok", ""),
        (BotFacts(True, "env", None), "disabled", "fail", "выключен"),
        (BotFacts(False, "none", "bot_process_never_started"), "polling", "fail", "crm-bot"),
        (BotFacts(False, "db", "bot_process_down"), "polling", "fail", "не отвечает"),
    ],
    ids=["no-supervisor", "no-token", "crashed", "running", "disabled", "never", "down"],
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


PROD_OK = PlatformUrlFacts("https://platform.example.com", prod=True)
CRM_OK = "https://crm.example.com"


@pytest.mark.parametrize(
    ("crm", "platform", "status", "needles"),
    [
        (CRM_OK, PROD_OK, "ok", []),
        (CRM_OK, None, "ok", []),
        # localhost на проде: понятный текст и действие (W15-H8a)
        (
            CRM_OK,
            PlatformUrlFacts("http://localhost", True),
            "warn",
            ["Платформы", "localhost", "PLATFORM_DOMAIN"],
        ),
        (CRM_OK, PlatformUrlFacts("http://127.0.0.1:8088", True), "warn", ["localhost", "хостинг"]),
        # ссылки Telegram идут в Платформу: адрес CRM — только запасной (B-009)
        ("http://localhost", PROD_OK, "ok", []),
        ("http://localhost", None, "warn", ["Адрес CRM", "«Настройки» → «Компания»"]),
        # на стенде localhost для Платформы — норма
        (CRM_OK, PlatformUrlFacts("http://platform.localhost:8088", False), "ok", []),
        # адреса нет совсем — честная строка в любом режиме, а не localhost в письме
        (CRM_OK, PlatformUrlFacts(None, True), "warn", ["Платформы не задан", "PLATFORM_DOMAIN"]),
        (
            CRM_OK,
            PlatformUrlFacts(None, False),
            "warn",
            ["Платформы не задан", "ссылки из Telegram"],
        ),
    ],
    ids=[
        "ok",
        "no-platform-check",
        "platform-localhost",
        "platform-127",
        "crm-localhost-platform-ok",
        "crm-localhost-no-platform-check",
        "dev-ok",
        "missing-prod",
        "missing-dev",
    ],
)
def test_crm_url_component_covers_platform(
    crm: str, platform: PlatformUrlFacts | None, status: str, needles: list[str]
) -> None:
    result = rules.crm_url(crm, NOW, platform)
    assert result.key == "crm_url"
    assert result.status == status
    for needle in needles:
        assert needle in result.reason


def test_crm_url_component_reports_both_problems_in_one_row() -> None:
    result = rules.crm_url("http://localhost", NOW, PlatformUrlFacts(None, True))
    assert "Адрес CRM" in result.reason
    assert "Платформы не задан" in result.reason


def _backup(
    mounted: bool = True,
    alive: bool = True,
    last: datetime | None = NOW - timedelta(hours=2),
    asked: datetime | None = None,
    seen: bool = True,
) -> str:
    return rules.backup(NOW, BackupFacts(mounted, alive, last, asked, seen)).status


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
    statuses: list[tuple[str, Status]] = [("a", "ok"), ("b", "warn"), ("c", "fail")]
    comps = [Component(k, k, st, "", NOW) for k, st in statuses]
    assert [c.key for c in rules.ordered(comps)] == ["c", "b", "a"]


def test_model_titles_are_roles() -> None:
    [row] = rules.models([AlertRow("model:dialog-model", True, "нет кредитов", NOW)])
    assert row.title == "Модель ИИ: Диалог"
    assert row.reason.startswith("нет кредитов")


def test_budget_warns_on_active_alert() -> None:
    assert rules.budget([AlertRow("budget", True, "$1.8 из $2", NOW)], NOW).status == "warn"
    assert rules.budget([], NOW).status == "ok"


@pytest.mark.parametrize(
    ("alive", "seen", "expected"),
    [
        (False, False, "warn"),  # демон не развёрнут (dev)
        (False, True, "fail"),  # heartbeat был и устарел
        (True, True, "ok"),
    ],
)
def test_backup_daemon_never_seen_is_warn(alive: bool, seen: bool, expected: str) -> None:
    assert _backup(alive=alive, seen=seen) == expected
    if not seen:
        facts = BackupFacts(True, alive, None, None, seen)
        reason = rules.backup(NOW, facts).reason
        assert reason == "Резервное копирование не запущено на этом сервере"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("TelegramNetworkError", "Нет связи с Telegram"),
        ("TelegramUnauthorizedError", "не принимает токен"),
        ("TelegramConflictError", "другой сервер"),
        (None, "Бот не принимает сообщения"),
    ],
)
def test_bot_failure_in_words(error: str | None, expected: str) -> None:
    assert expected in rules._bot_failure(error)
    assert "Error" not in rules._bot_failure(error)


@pytest.mark.parametrize(
    ("facts", "status", "fragment"),
    [
        (ErpFacts(configured=False), "unknown", "не настроен"),
        (ErpFacts(True, "ok", "1.2.3", True, True, NOW, 12), "ok", "версия 1.2.3"),
        (ErpFacts(True, "degraded", "1.2.3", True, True, NOW, 12), "warn", "деградации"),
        (ErpFacts(True, "ok", "1.2.3", False, True, NOW, 12), "warn", "миграции"),
        (ErpFacts(True, "ok", "1.2.3", True, False, NOW, 12), "warn", "очередь"),
        (ErpFacts(True, error="unauthorized"), "fail", "токен"),
        (ErpFacts(True, error="unavailable", detail="timeout"), "fail", "(timeout)"),
        (ErpFacts(True, error="invalid_url"), "fail", "Адрес"),
        (ErpFacts(True, error="bad_response"), "fail", "неожиданно"),
    ],
    ids=[
        "none",
        "ok",
        "degraded",
        "migrations",
        "queue",
        "unauthorized",
        "unavailable",
        "invalid_url",
        "bad_response",
    ],
)
def test_erp(facts: ErpFacts, status: str, fragment: str) -> None:
    """Коннектор не настроен — «нет данных», не сбой: CRM без ERP автономна (ADR-0022)."""
    component = rules.erp(facts, NOW)
    assert (component.key, component.status) == ("erp", status)
    assert fragment in component.reason
    assert "Error" not in component.reason


@pytest.mark.parametrize(
    ("facts", "status", "reason"),
    [
        (None, "unknown", "Журнал расходов шлюза моделей недоступен"),
        (
            [rules.AiBudgetFacts("crm", 0.42, 2.0), rules.AiBudgetFacts("erp", 0.0, 1.0)],
            "ok",
            "CRM 0.42/2.00 USD, ERP 0.00/1.00 USD",
        ),
        (
            [rules.AiBudgetFacts("crm", 0.5, 2.0), rules.AiBudgetFacts("erp", 1.2, 1.0)],
            "warn",
            "Бюджет превышен: ERP. CRM 0.50/2.00 USD, ERP 1.20/1.00 USD",
        ),
        (
            [
                rules.AiBudgetFacts("crm", 0.5, 0.0),
                rules.AiBudgetFacts("erp", 0.0, 1.0),
                rules.AiBudgetFacts("other", 0.0, 0.0),
            ],
            "ok",
            "CRM 0.50 USD (без лимита), ERP 0.00/1.00 USD",
        ),
    ],
)
def test_ai_budget(facts: list[rules.AiBudgetFacts] | None, status: str, reason: str) -> None:
    """M3-CRM-09: «Бюджет ИИ сегодня: CRM x/y USD, ERP x/y USD»; превышение ERP видно в CRM."""
    component = rules.ai_budget(facts, NOW)
    assert (component.key, component.title) == ("ai_budget", "Бюджет ИИ сегодня")
    assert component.status == status
    assert component.reason.startswith(reason)
    assert component.reason == reason or facts is None
