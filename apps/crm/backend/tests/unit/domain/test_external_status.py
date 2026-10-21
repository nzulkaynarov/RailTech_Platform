"""Правила статусов внешних сервисов (M3-CRM-12, ADR-0024): таблицы кейсов."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import external_status as rules
from app.domain import system_status
from app.domain.external_status import HttpFacts, MailFacts, TelegramFacts, TlsFacts
from app.domain.system_status import BackupFacts, Component

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
OK = HttpFacts(None, None, 12)
HOOK = "https://crm.example/telegram/webhook"


@pytest.mark.parametrize(
    ("facts", "status", "words"),
    [
        (TelegramFacts(False, "polling"), "fail", "Токен бота не задан"),
        (TelegramFacts(True, "disabled"), "off", "выключен настройкой"),
        (TelegramFacts(True, "polling", error="unauthorized"), "fail", "не принимает токен"),
        (TelegramFacts(True, "polling", error="timeout"), "fail", "Нет связи с Telegram"),
        (TelegramFacts(True, "polling", error="unavailable"), "fail", "Нет связи с Telegram"),
        (TelegramFacts(True, "polling", username="rt_bot", pending_updates=0), "ok", "@rt_bot"),
        (TelegramFacts(True, "polling", pending_updates=150), "warn", "150 сообщений ждут"),
        (TelegramFacts(True, "polling", webhook_url="https://x/tg"), "fail", "другого сервера"),
        (
            TelegramFacts(True, "webhook", config_url=HOOK, webhook_url=None),
            "fail",
            "не установлен",
        ),
        (TelegramFacts(True, "webhook", config_url=""), "fail", "Вебхук Telegram не настроен"),
        (
            TelegramFacts(True, "webhook", config_url="http://crm.example/tg"),
            "fail",
            "Вебхук Telegram не настроен",
        ),
        (
            TelegramFacts(True, "webhook", config_url=HOOK, webhook_url=HOOK, username="rt_bot"),
            "ok",
            "@rt_bot",
        ),
        (
            TelegramFacts(
                True, "webhook", config_url=HOOK, webhook_error="getWebhookInfo: HTTP 502"
            ),
            "warn",
            "Не удалось узнать состояние вебхука",
        ),
        (
            TelegramFacts(
                True,
                "webhook",
                config_url=HOOK,
                webhook_url="https://crm.example/tg",
                last_error_message="Connection timed out",
                last_error_at=NOW - timedelta(minutes=3),
            ),
            "warn",
            "не может доставить",
        ),
        (
            TelegramFacts(
                True,
                "webhook",
                config_url=HOOK,
                webhook_url="https://crm.example/tg",
                last_error_message="old",
                last_error_at=NOW - timedelta(hours=2),
            ),
            "ok",
            "Бот отвечает",
        ),
    ],
)
def test_telegram(facts: TelegramFacts, status: str, words: str) -> None:
    result = rules.telegram(facts, NOW)
    assert result.status == status
    assert words in result.summary
    if status in ("fail", "warn"):
        assert result.hint, "у проблемы всегда есть «что сделать»"


def test_telegram_webhook_not_configured_has_error_and_hint() -> None:
    result = rules.telegram(TelegramFacts(True, "webhook", config_url=""), NOW)
    assert result.error == "TELEGRAM_WEBHOOK_URL пуст"
    assert "CRM_DOMAIN" in (result.hint or "")
    assert "/telegram/webhook" in (result.hint or "")


def test_webhook_not_configured_has_no_fix_button_target() -> None:
    """«Исправить» вёл бы в «Подключения», а адрес вебхука там не правится (FIX-66)."""
    result = rules.telegram(TelegramFacts(True, "webhook", config_url=""), NOW)
    assert result.metrics["_no_fix"] == 1


def test_telegram_shows_actual_webhook_and_last_error() -> None:
    """FIX-66: центр показывает фактический адрес и последнюю ошибку из getWebhookInfo."""
    result = rules.telegram(
        TelegramFacts(
            True,
            "webhook",
            config_url=HOOK,
            username="rt_bot",
            webhook_url=HOOK,
            last_error_message="Connection timed out",
            last_error_at=NOW - timedelta(minutes=3),
        ),
        NOW,
    )
    assert result.status == "warn"
    assert result.metrics["webhook_url"] == HOOK
    assert result.metrics["webhook_error"] == "Connection timed out"
    assert result.metrics["webhook_error_at"] == (NOW - timedelta(minutes=3)).isoformat()


def test_telegram_error_never_carries_token() -> None:
    result = rules.telegram(
        TelegramFacts(True, "polling", error="unauthorized", detail="getMe: HTTP 401"), NOW
    )
    assert result.error == "getMe: HTTP 401"
    assert "«Подключениях»" in (result.hint or "")


@pytest.mark.parametrize(
    ("facts", "status"),
    [
        (rules.GatewayFacts(OK, "connected"), "ok"),
        (rules.GatewayFacts(OK, None), "ok"),
        (rules.GatewayFacts(OK, "disconnected"), "warn"),
        (rules.GatewayFacts(HttpFacts("unavailable", "ConnectError")), "fail"),
    ],
)
def test_litellm(facts: rules.GatewayFacts, status: str) -> None:
    assert rules.litellm(facts).status == status


@pytest.mark.parametrize(
    ("facts", "status"),
    [
        (rules.LangfuseFacts(False), "off"),
        (rules.LangfuseFacts(True, OK, True), "ok"),
        (rules.LangfuseFacts(True, OK, None), "ok"),
        (rules.LangfuseFacts(True, OK, False), "fail"),
        (rules.LangfuseFacts(True, HttpFacts("timeout")), "fail"),
    ],
)
def test_langfuse(facts: rules.LangfuseFacts, status: str) -> None:
    assert rules.langfuse(facts).status == status


@pytest.mark.parametrize(
    ("facts", "status", "words"),
    [
        (MailFacts(False), "off", "Не подключена"),
        (MailFacts(True, sent_24h=3), "ok", "Письма уходят"),
        (
            MailFacts(True, probe_error="auth_failed"),
            "fail",
            "не принимает",
        ),
        (MailFacts(True, probe_error="unavailable"), "fail", "не принимает"),
        (
            MailFacts(True, queued=2, oldest_queued_at=NOW - timedelta(minutes=30)),
            "warn",
            "2 писем ждут",
        ),
        (
            MailFacts(True, queued=2, oldest_queued_at=NOW - timedelta(minutes=30), paused=True),
            "ok",
            "Письма уходят",
        ),
        (
            MailFacts(True, last_error="rejected", last_failed_at=NOW - timedelta(hours=1)),
            "warn",
            "не отправлено",
        ),
        (
            MailFacts(
                True,
                last_failed_at=NOW - timedelta(hours=2),
                last_sent_at=NOW - timedelta(hours=1),
            ),
            "ok",
            "Письма уходят",
        ),
    ],
)
def test_mail(facts: MailFacts, status: str, words: str) -> None:
    result = rules.mail(facts, NOW)
    assert result.status == status
    assert words in result.summary
    assert result.metrics["sent_24h"] == facts.sent_24h


def test_mail_hint_by_smtp_error_kind() -> None:
    auth = rules.mail(MailFacts(True, probe_error="auth_failed"), NOW)
    assert "логин или пароль" in (auth.hint or "")
    assert auth.error == "auth_failed"


def test_s3_and_docling() -> None:
    usage = {"bucket.kb-sources.bytes": 1024}
    assert rules.s3(OK, usage).metrics == usage
    assert rules.s3(HttpFacts("unavailable"), usage).status == "fail"
    assert rules.docling(OK).status == "ok"
    down = rules.docling(HttpFacts("timeout", "ReadTimeout"))
    assert down.status == "fail"
    assert down.error == "ReadTimeout"
    assert down.hint


def test_backup_maps_existing_rule() -> None:
    ok = Component("backup", "Резервные копии", "ok", "Последняя копия 3 ч назад", NOW)
    assert rules.backup(ok, 3.0).metrics == {"last_copy_hours": 3.0}
    stale = Component(
        "backup",
        "Резервные копии",
        "warn",
        "Последняя копия 30 ч назад — сделайте копию в «Резервных копиях»",
        NOW,
    )
    assert rules.backup(stale, 30.0).hint == "Откройте «Резервные копии»"


def test_backup_from_rustfs_shows_source_time_and_hint() -> None:
    last = NOW - timedelta(hours=30)
    facts = BackupFacts(
        True,
        True,
        last,
        None,
        True,
        "rustfs",
        databases={"crm": last, "erp": NOW - timedelta(hours=2)},
    )
    component = system_status.backup(NOW, facts)
    result = rules.backup(component, 30.0, facts)
    assert result.status == "fail"  # «нет копии за сутки» открывает инцидент
    assert result.metrics["backup_source"] == "rustfs"
    assert result.metrics["last_copy_at"] == last.isoformat()
    assert result.metrics["db.crm.hours"] == 30.0
    assert result.metrics["db.erp.hours"] == 2.0
    assert result.hint
    assert "backup-now.sh" in result.hint


def test_backup_from_rustfs_bucket_error_is_explained() -> None:
    facts = BackupFacts(False, True, None, None, True, "rustfs", "bucket_missing", "NoSuchBucket")
    result = rules.backup(system_status.backup(NOW, facts), None, facts)
    assert result.status == "fail"
    assert result.error == "NoSuchBucket"
    assert result.hint
    assert "backups" in result.hint


def test_backup_from_volume_reports_its_source() -> None:
    facts = BackupFacts(True, True, NOW - timedelta(hours=3), None)
    result = rules.backup(system_status.backup(NOW, facts), 3.0, facts)
    assert result.status == "ok"
    assert result.metrics["backup_source"] == "volume"


@pytest.mark.parametrize(
    ("url", "host", "reason"),
    [
        ("https://crm.railtech.uz", "crm.railtech.uz", None),
        ("https://CRM.railtech.uz/path", "crm.railtech.uz", None),
        ("http://crm.railtech.uz", None, "без https"),
        ("https://crm.localhost", None, "локальный"),
        ("http://localhost", None, "локальный"),
        ("", None, "не задан"),
    ],
)
def test_tls_target(url: str, host: str | None, reason: str | None) -> None:
    found_host, found_reason = rules.tls_target(url)
    assert found_host == host
    assert (reason is None and found_reason is None) or (reason or "") in (found_reason or "")


@pytest.mark.parametrize(
    ("days", "status"),
    [(90, "ok"), (22, "ok"), (21, "warn"), (8, "warn"), (7, "fail"), (0, "fail")],
)
def test_tls_days(days: int, status: str) -> None:
    result = rules.tls(TlsFacts("crm", "crm.railtech.uz", days_left=days))
    assert result.status == status
    assert result.metrics["days_left"] == days


def test_tls_not_applicable_and_invalid() -> None:
    assert rules.tls(TlsFacts("erp", None, not_applicable="адрес не задан")).status == "off"
    invalid = rules.tls(TlsFacts("crm", "crm.x", error="invalid", detail="certificate has expired"))
    assert invalid.status == "fail"
    assert "недействителен" in invalid.summary
    down = rules.tls(TlsFacts("crm", "crm.x", error="unavailable"))
    assert "не отвечает" in down.summary


def test_tls_days_left_rounds_down() -> None:
    assert rules.tls_days_left(NOW + timedelta(days=10, hours=23), NOW) == 10


@pytest.mark.parametrize(
    ("age", "tiers", "stale"),
    [
        (timedelta(minutes=4), ("cheap",), False),
        (timedelta(minutes=6), ("cheap",), True),
        (timedelta(minutes=30), ("heavy",), False),
        (timedelta(minutes=46), ("heavy",), True),
    ],
)
def test_stale(age: timedelta, tiers: tuple[str, ...], stale: bool) -> None:
    assert rules.stale(NOW - age, tiers, NOW) is stale


def test_erp_reported_has_no_data_until_m3_erp_06() -> None:
    result = rules.erp_reported("erp.cbu_rates")
    assert result.status == "unknown"
    assert "M3-ERP-06" in result.summary
