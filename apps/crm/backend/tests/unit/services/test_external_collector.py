"""Сбор фактов центра внешних сервисов (M3-CRM-12, ADR-0024) на подставных границах.

HTTP — respx (Telegram, LiteLLM, docling, S3, Langfuse), SMTP — подставной транспорт, журнал шлюза —
записанные строки, TLS — подставная проба. Платных вызовов и сети нет.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from pydantic import AnyHttpUrl, SecretStr

from app.config import Settings
from app.integrations.external_probes import TlsProbe
from app.integrations.litellm_admin import LiteLLMAdmin
from app.integrations.litellm_catalog import ModelEntry
from app.integrations.litellm_spend import LiteLLMSpendError, SpendLogs
from app.integrations.smtp import SmtpCheck, SmtpConnection, SmtpProbeError
from app.repositories import external_services as repo
from app.repositories.external_services import MailLogStats
from app.schemas.settings import AppSettings
from app.services.external_services.collector import Collector, Deps

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
TOKEN = "123456:fake-collector-token"  # фиктивный
LITELLM = "http://litellm.invalid:4000"
CONFIG = Settings(
    _env_file=None,
    app_env="test",
    litellm_base_url=AnyHttpUrl(LITELLM),
    litellm_api_key=SecretStr("sk-master-test"),
    s3_endpoint=AnyHttpUrl("http://rustfs.invalid:9000"),
    docling_url=AnyHttpUrl("http://docling.invalid:5001"),
    telegram_bot_token=SecretStr(TOKEN),
    cabinet_origin="https://cabinet.railtech.uz",
)
CONNECTION = SmtpConnection("smtp.example", 587, "starttls", "u", "p", "crm@example.com", "CRM")


class FakeSettings:
    def __init__(self) -> None:
        self.value = AppSettings()
        self.value.company.crm_base_url = "https://crm.railtech.uz"

    async def get(self) -> AppSettings:
        return self.value


class FakeSecrets:
    enabled = False

    async def get(self, key: str) -> str | None:
        return None


class FakeTransport:
    def __init__(self) -> None:
        self.error: SmtpProbeError | None = None
        self.checks = 0

    async def check(self, connection: SmtpConnection) -> SmtpCheck:
        self.checks += 1
        if self.error is not None:
            raise self.error
        return SmtpCheck("smtp.example ESMTP", True, 7)


class FakeResolution:
    def __init__(self, connection: SmtpConnection | None) -> None:
        self.connection = connection


class FakeMail:
    def __init__(self, connection: SmtpConnection | None = CONNECTION) -> None:
        self.transport = FakeTransport()
        self._connection = connection

    async def resolution(self) -> FakeResolution:
        return FakeResolution(self._connection)


class FakeStorage:
    async def bucket_usage(self, bucket: str) -> tuple[int, int]:
        if bucket == "tg-attachments":
            raise RuntimeError("no bucket")
        return 3, 3072


class FakeCatalog:
    async def entries(self) -> dict[str, ModelEntry]:
        return {
            "dialog-model": ModelEntry("dialog-model", "anthropic", "anthropic/claude"),
            "fallback-model": ModelEntry("fallback-model", "gemini", "gemini/flash"),
        }


class FakeLogs:
    def __init__(self, rows: list[dict[str, Any]] | None = None, *, down: bool = False) -> None:
        self.rows = rows or []
        self.down = down
        self.windows: list[tuple[datetime, datetime]] = []

    async def fetch(self, start: datetime, end: datetime) -> SpendLogs:
        self.windows.append((start, end))
        if self.down:
            raise LiteLLMSpendError(None, "ConnectError")
        return SpendLogs(rows=self.rows)


class FakeSessions:
    """`async with sessions()` — журнал писем подменяется monkeypatch'ем репозитория."""

    def __call__(self) -> "FakeSessions":
        return self

    async def __aenter__(self) -> "FakeSessions":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


def deps(**overrides: Any) -> Deps:
    async def erp_url() -> str:
        return ""

    async def tls(host: str) -> TlsProbe:
        return TlsProbe(NOW + timedelta(days=60))

    base: dict[str, Any] = {
        "config": CONFIG,
        "settings": FakeSettings(),
        "secrets": FakeSecrets(),
        "sessions": FakeSessions(),
        "mail": FakeMail(),
        "storage": FakeStorage(),
        "backups": None,
        "admin": LiteLLMAdmin(AnyHttpUrl(LITELLM), SecretStr("sk-master-test")),
        "spend_logs": FakeLogs(),
        "catalog": FakeCatalog(),
        "erp_url": erp_url,
        "tls_probe": tls,
        "retry_delay_s": 0.0,
    }
    base.update(overrides)
    return Deps(**base)


@pytest.fixture(autouse=True)
def _mail_log(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stats(session: object, since: datetime) -> MailLogStats:
        return MailLogStats(4, 0, 0, None, None, None, NOW - timedelta(hours=1))

    async def no_probes(session: object) -> dict[str, str]:
        return {}

    monkeypatch.setattr(repo, "mail_stats", stats)
    monkeypatch.setattr(repo, "model_probe_problems", no_probes)


async def collect(
    d: Deps,
    keys: list[str],
    run: str = "cheap",
    previous: dict[str, dict[str, Any]] | None = None,
    disabled: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    results = await Collector(d).collect(keys, run, NOW, previous or {}, disabled)  # type: ignore[arg-type]
    return {r.key: r for r in results}


def tg_ok() -> None:
    respx.get(f"https://api.telegram.org/bot{TOKEN}/getMe").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"username": "rt_bot"}})
    )
    respx.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"url": ""}})
    )


@respx.mock
async def test_cheap_pass_over_http_services() -> None:
    tg_ok()
    respx.get(f"{LITELLM}/health/liveliness").mock(return_value=httpx.Response(200, json="ok"))
    respx.get(f"{LITELLM}/health/readiness").mock(
        return_value=httpx.Response(200, json={"status": "healthy", "db": "connected"})
    )
    respx.get("http://rustfs.invalid:9000/health").mock(return_value=httpx.Response(200))
    respx.get("http://docling.invalid:5001/health").mock(side_effect=httpx.ConnectError("x"))
    found = await collect(
        deps(), ["telegram", "litellm", "s3", "docling", "langfuse", "erp.sentry"]
    )
    assert found["telegram"].status == "ok"
    assert found["telegram"].metrics["bot"] == "rt_bot"
    assert found["litellm"].status == "ok"
    assert found["s3"].status == "ok"
    assert found["docling"].status == "fail"
    assert found["langfuse"].status == "off"
    assert found["erp.sentry"].status == "unknown"


@respx.mock
async def test_one_slow_answer_does_not_fail_the_check() -> None:
    """Каждый 5–6-й запрос медленный: повтор внутри проверки до признания fail."""
    route = respx.get("http://docling.invalid:5001/health").mock(
        side_effect=[httpx.ConnectTimeout("slow"), httpx.Response(200, json={"status": "ok"})]
    )
    found = await collect(deps(), ["docling"])
    assert found["docling"].status == "ok"
    assert route.call_count == 2


@respx.mock
async def test_two_failed_attempts_are_a_fail_and_a_wrong_token_is_not_retried() -> None:
    route = respx.get("http://docling.invalid:5001/health").mock(
        side_effect=httpx.ConnectTimeout("slow")
    )
    assert (await collect(deps(), ["docling"]))["docling"].status == "fail"
    assert route.call_count == 2
    me = respx.get(re.compile(r".*/getMe")).mock(return_value=httpx.Response(401, json={}))
    respx.get(re.compile(r".*/getWebhookInfo")).mock(return_value=httpx.Response(200, json={}))
    found = await collect(deps(), ["telegram"])
    assert found["telegram"].cause == "token_rejected"
    assert me.call_count == 1  # причина не транзиентная — повтора нет


def test_probe_timeouts_are_not_short() -> None:
    from app.integrations import external_probes
    from app.services.external_services import collector

    assert collector.HTTP_TIMEOUT_S >= 10
    assert external_probes.TLS_TIMEOUT_S >= 10
    assert collector.PROBE_TIMEOUT_S >= 2 * collector.HTTP_TIMEOUT_S


async def test_docling_without_url_is_off_not_a_failure() -> None:
    d = deps(config=CONFIG.model_copy(update={"docling_url": None}))
    found = await collect(d, ["docling"])
    assert found["docling"].status == "off"
    assert "не используется на этом сервере" in found["docling"].summary.lower()


@respx.mock
async def test_telegram_check_follows_configured_bot_api_address() -> None:
    """Статус Telegram — прямой getMe/getWebhookInfo; адрес Bot API берётся из настроек."""
    base = "http://fake-bot-api:8081"
    me = respx.get(f"{base}/bot{TOKEN}/getMe").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"username": "rt_bot"}})
    )
    respx.get(f"{base}/bot{TOKEN}/getWebhookInfo").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"url": ""}})
    )
    config = CONFIG.model_copy(update={"telegram_api_base_url": f" {base}/ "})
    result = (await collect(deps(config=config), ["telegram"]))["telegram"]
    assert me.called
    assert result.metrics["bot"] == "rt_bot"


@respx.mock
async def test_wrong_bot_token_is_a_failure_with_fix() -> None:
    respx.get(f"https://api.telegram.org/bot{TOKEN}/getMe").mock(
        return_value=httpx.Response(401, json={"ok": False})
    )
    result = (await collect(deps(), ["telegram"]))["telegram"]
    assert result.status == "fail"
    assert "«Подключениях»" in result.hint
    assert TOKEN not in (result.error or "")


HOOK = "https://crm.railtech.uz/telegram/webhook"


def webhook_config(url: str) -> Settings:
    return CONFIG.model_copy(update={"telegram_mode": "webhook", "telegram_webhook_url": url})


def tg_hook(info: dict[str, Any] | httpx.Response) -> respx.Route:
    respx.get(f"https://api.telegram.org/bot{TOKEN}/getMe").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"username": "rt_bot"}})
    )
    response = (
        info
        if isinstance(info, httpx.Response)
        else httpx.Response(200, json={"ok": True, "result": info})
    )
    return respx.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo").mock(
        return_value=response
    )


@pytest.mark.parametrize("url", ["", "http://crm.railtech.uz/telegram/webhook"])
@respx.mock
async def test_webhook_mode_with_bad_url_is_an_incident_with_hint(url: str) -> None:
    """FIX-66: вебхук не настроен — `fail` (открывает инцидент) с подсказкой, без токена."""
    tg_hook({"url": ""})
    result = (await collect(deps(config=webhook_config(url)), ["telegram"]))["telegram"]
    assert result.status == "fail"
    assert "Вебхук Telegram не настроен" in result.summary
    assert "CRM_DOMAIN" in (result.hint or "")
    assert TOKEN not in repr(result)


@respx.mock
async def test_webhook_mode_shows_actual_address_and_last_error_from_one_probe() -> None:
    route = tg_hook(
        {
            "url": HOOK,
            "last_error_date": int((NOW - timedelta(minutes=2)).timestamp()),
            "last_error_message": "Connection timed out",
        }
    )
    d = deps(config=webhook_config(HOOK))
    result = (await collect(d, ["telegram"]))["telegram"]
    assert result.status == "warn"
    assert result.metrics["webhook_url"] == HOOK
    assert result.metrics["webhook_error"] == "Connection timed out"
    assert result.metrics["webhook_error_at"] == (NOW - timedelta(minutes=2)).isoformat()
    assert route.call_count == 1  # один getWebhookInfo на проход, без лишних вызовов Bot API
    assert TOKEN not in repr(result)


@respx.mock
async def test_explicit_override_url_is_accepted() -> None:
    other = "https://crm2.example.com/hook"
    tg_hook({"url": other})
    result = (await collect(deps(config=webhook_config(other)), ["telegram"]))["telegram"]
    assert result.status == "ok"
    assert result.metrics["webhook_url"] == other


@respx.mock
async def test_get_webhook_info_failure_is_a_warning_not_a_missing_webhook() -> None:
    tg_hook(httpx.Response(502))
    result = (await collect(deps(config=webhook_config(HOOK)), ["telegram"]))["telegram"]
    assert result.status == "warn"
    assert "состояние вебхука" in result.summary
    assert result.metrics["webhook_url"] is None


async def test_mail_heavy_probe_and_cheap_carry_over() -> None:
    mail = FakeMail()
    d = deps(mail=mail)
    heavy = (await collect(d, ["mail"], "heavy"))["mail"]
    assert heavy.status == "ok"
    assert mail.transport.checks == 1
    assert heavy.metrics["_smtp"] == "ok"
    assert heavy.metrics["sent_24h"] == 4

    mail.transport.error = SmtpProbeError("auth_failed", "SMTP 535")
    failed = (await collect(d, ["mail"], "heavy"))["mail"]
    assert failed.status == "fail"
    assert failed.error == "auth_failed: SMTP 535"
    # Дешёвый проход не ходит в SMTP, а несёт итог последнего тяжёлого.
    cheap = (await collect(d, ["mail"], "cheap", {"mail": dict(failed.metrics)}))["mail"]
    assert cheap.status == "fail"
    assert mail.transport.checks == 2


async def test_mail_without_connector_is_off() -> None:
    result = (await collect(deps(mail=FakeMail(None)), ["mail"], "heavy"))["mail"]
    assert result.status == "off"
    assert result.hint


@respx.mock
async def test_s3_heavy_pass_measures_buckets() -> None:
    respx.get("http://rustfs.invalid:9000/health").mock(return_value=httpx.Response(200))
    heavy = (await collect(deps(), ["s3"], "heavy"))["s3"]
    assert heavy.metrics["bucket.kb-sources.bytes"] == 3072
    assert heavy.metrics["bucket.client-documents.objects"] == 3
    assert "bucket.tg-attachments.bytes" not in heavy.metrics
    cheap = (await collect(deps(), ["s3"], "cheap", {"s3": dict(heavy.metrics)}))["s3"]
    assert cheap.metrics == heavy.metrics


def log_row(minutes_ago: int, status: str = "success", **extra: Any) -> dict[str, Any]:
    at = NOW - timedelta(minutes=minutes_ago)
    return {
        "request_id": f"r{minutes_ago}{status}",
        "startTime": at.isoformat(),
        "endTime": (at + timedelta(milliseconds=800)).isoformat(),
        "custom_llm_provider": "anthropic",
        "model_group": "dialog-model",
        "status": status,
        "spend": 0.01,
        **extra,
    }


@respx.mock
async def test_vendor_from_gateway_log_and_budget_without_model_calls() -> None:
    respx.get(f"{LITELLM}/provider/budgets").mock(
        return_value=httpx.Response(
            200, json={"providers": {"anthropic": {"budget_limit": 3.0, "spend": 1.0}}}
        )
    )
    failure = {
        "metadata": {
            "error_information": {"error_code": "401", "error_class": "AuthenticationError"}
        }
    }
    logs = FakeLogs([log_row(2), log_row(1, "failure", **failure), log_row(300)])
    d = deps(spend_logs=logs)
    cheap = await collect(d, ["vendor.anthropic", "vendor.gemini"])
    assert cheap["vendor.anthropic"].status == "fail"
    assert "«Модели ИИ»" in cheap["vendor.anthropic"].hint
    assert cheap["vendor.anthropic"].metrics["budget_limit_usd"] == 3.0
    assert cheap["vendor.gemini"].status == "ok"
    assert len(logs.windows) == 1  # журнал читается один раз на проход
    start, end = logs.windows[0]
    assert end - start == timedelta(minutes=15)

    heavy = (await collect(d, ["vendor.anthropic"], "heavy"))["vendor.anthropic"]
    assert heavy.metrics["calls_24h"] == 3
    assert heavy.metrics["failures_24h"] == 1
    assert heavy.metrics["p95_ms_24h"] == 800
    assert logs.windows[-1][1] - logs.windows[-1][0] == timedelta(hours=24)
    assert not any("chat/completions" in str(c.request.url) for c in respx.calls)


@respx.mock
async def test_hourly_probe_problem_of_a_role_fails_its_provider_with_one_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проба моделей раз в час — источник причины «Ключ <провайдер> отклонён», не письмо по роли."""

    async def problems(session: object) -> dict[str, str]:
        text = "провайдер отклонил ключ — проверьте ключ API; бот не отвечает"
        return {"dialog-model": text, "qualifier-model": text, "fallback-model": "x"}

    monkeypatch.setattr(repo, "model_probe_problems", problems)
    respx.get(f"{LITELLM}/provider/budgets").mock(return_value=httpx.Response(200, json={}))
    found = await collect(deps(spend_logs=FakeLogs()), ["vendor.anthropic", "vendor.gemini"])
    assert (found["vendor.anthropic"].status, found["vendor.anthropic"].cause) == (
        "fail",
        "key_rejected",
    )
    assert found["vendor.gemini"].status != "fail" or found["vendor.gemini"].cause != "key_rejected"


async def test_ai_replies_row_reads_bot_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain.external_ai_replies import AiFacts

    async def stats(session: object, window_since: datetime, day_since: datetime) -> AiFacts:
        assert NOW - window_since == timedelta(minutes=5)
        assert NOW - day_since == timedelta(hours=24)
        return AiFacts(failed=2, last_failed_at=NOW)

    monkeypatch.setattr(repo, "ai_reply_stats", stats)
    found = await collect(deps(), ["ai_replies"])
    assert (found["ai_replies"].status, found["ai_replies"].cause) == ("fail", "ai_unavailable")


@respx.mock
async def test_vendor_unknown_when_gateway_log_is_down_and_off_when_disabled() -> None:
    respx.get(f"{LITELLM}/provider/budgets").mock(side_effect=httpx.ConnectError("x"))
    d = deps(spend_logs=FakeLogs(down=True))
    assert (await collect(d, ["vendor.anthropic"]))["vendor.anthropic"].status == "unknown"
    off = await collect(d, ["vendor.anthropic"], disabled=frozenset({"vendor.anthropic"}))
    assert off["vendor.anthropic"].status == "off"


async def test_tls_targets_from_settings_and_dev_is_not_applicable() -> None:
    probed: list[str] = []

    async def tls(host: str) -> TlsProbe:
        probed.append(host)
        return TlsProbe(NOW + timedelta(days=5))

    found = await collect(deps(tls_probe=tls), ["tls.crm", "tls.erp", "tls.cabinet"], "heavy")
    assert sorted(probed) == ["cabinet.railtech.uz", "crm.railtech.uz"]
    assert found["tls.crm"].status == "fail"  # 5 дней
    assert found["tls.erp"].status == "off"  # ERP не подключена


async def test_probe_crash_becomes_unknown_not_a_crash() -> None:
    async def broken(host: str) -> TlsProbe:
        raise RuntimeError("boom")

    found = await collect(deps(tls_probe=broken), ["tls.crm"], "heavy")
    assert found["tls.crm"].status == "unknown"
    assert found["tls.crm"].error == "RuntimeError"


# --- архив WAL, Redis и шина (W15-H8b, B-004) ---------------------------------------------------


class WalStorage:
    def __init__(self, objects: list[Any], error: Exception | None = None) -> None:
        self.objects, self.error = objects, error

    async def list_objects(self, bucket: str, prefix: str = "", start_after: str = "") -> list[Any]:
        if self.error is not None:
            raise self.error
        return [o for o in self.objects if o.key.startswith(prefix) and o.key > start_after]


def wal_objects(segment_age_min: int) -> list[Any]:
    from app.integrations.s3 import StoredObject

    return [
        StoredObject(
            "pg17/wal_005/000000010000000000000001.zst", 1, NOW - timedelta(minutes=segment_age_min)
        ),
        StoredObject(
            "pg17/basebackups_005/base_01_backup_stop_sentinel.json", 1, NOW - timedelta(hours=8)
        ),
    ]


class OffsiteStorage:
    """Бакет offsite с отметкой сервиса копирования (OPS-GDRIVE); `calls` — что CRM запросила."""

    def __init__(self, body: bytes | None, error: Exception | None = None) -> None:
        self.body, self.error = body, error
        self.calls: list[tuple[str, str]] = []

    async def list_objects(self, bucket: str, prefix: str = "", start_after: str = "") -> list[Any]:
        from app.integrations.s3 import StoredObject

        self.calls.append(("list", bucket))
        if self.error is not None:
            raise self.error
        return [StoredObject("status.json", 1, NOW)] if self.body is not None else []

    async def get(self, bucket: str, key: str) -> bytes:
        self.calls.append(("get", f"{bucket}/{key}"))
        assert self.body is not None
        return self.body


async def test_offsite_backup_row_reads_only_the_status_file_of_the_offsite_bucket() -> None:
    body = (
        b'{"result":"ok","reason":"","last_success_at":"2026-10-14T03:00:00Z",'
        b'"bytes":1048576000,"base_backups":3,"quota_bytes":107374182400}'
    )
    storage = OffsiteStorage(body)
    ok = await collect(deps(storage=storage), ["offsite_backup"])
    assert ok["offsite_backup"].status == "ok"
    assert ok["offsite_backup"].metrics["base_backups"] == 3
    assert storage.calls == [("list", "offsite"), ("get", "offsite/status.json")]

    missing = await collect(deps(storage=OffsiteStorage(None)), ["offsite_backup"])
    assert missing["offsite_backup"].status == "off"  # сервис ещё не отметился — «не настроено»
    assert missing["offsite_backup"].cause == "offsite_not_configured"

    denied = OffsiteStorage(None, error=PermissionError("denied"))
    broken = await collect(deps(storage=denied), ["offsite_backup"])
    assert broken["offsite_backup"].status == "unknown"  # честное «не проверено»
    assert broken["offsite_backup"].error == "PermissionError"


async def test_wal_archive_row_ok_stale_and_unreadable() -> None:
    ok = await collect(deps(storage=WalStorage(wal_objects(2))), ["wal_archive"])
    assert ok["wal_archive"].status == "ok"
    assert ok["wal_archive"].metrics["last_segment_min"] == 2
    assert ok["wal_archive"].metrics["_wal_key"] == "pg17/wal_005/000000010000000000000001.zst"

    stale = await collect(deps(storage=WalStorage(wal_objects(120))), ["wal_archive"])
    assert stale["wal_archive"].status == "fail"
    assert stale["wal_archive"].cause == "server_down"

    broken = await collect(
        deps(storage=WalStorage([], error=PermissionError("denied"))), ["wal_archive"]
    )
    assert broken["wal_archive"].status == "unknown"  # честное «не проверено»
    assert broken["wal_archive"].error == "PermissionError"


async def test_wal_archive_remembers_the_last_key_between_passes() -> None:
    first = await collect(deps(storage=WalStorage(wal_objects(2))), ["wal_archive"])
    carried = dict(first["wal_archive"].metrics)
    # Нового сегмента нет: время берётся из памяти предыдущей проверки, а не «пусто».
    again = await collect(
        deps(storage=WalStorage(wal_objects(2))),
        ["wal_archive"],
        previous={"wal_archive": carried},
    )
    assert again["wal_archive"].status == "ok"
    assert again["wal_archive"].metrics["last_segment_min"] == 2


async def test_redis_rows_use_their_own_address_and_never_print_the_password() -> None:
    from app.integrations.redis_probe import RedisProbe

    asked: list[str] = []

    async def fake(url: str) -> RedisProbe:
        asked.append(url)
        if "broker" in url:
            return RedisProbe(None, 2, {"used_memory": "1048576", "maxmemory": "2097152"})
        return RedisProbe("ConnectionRefusedError")

    config = CONFIG.model_copy(
        update={
            "redis_broker_url": SecretStr("redis://:pw-b@redis-broker:6379/0"),
            "redis_cache_url": SecretStr("redis://:pw-c@redis-cache:6379/0"),
        }
    )
    found = await collect(deps(config=config, redis_probe=fake), ["redis_broker", "redis_cache"])
    assert found["redis_broker"].status == "ok"
    assert found["redis_broker"].metrics["memory_pct"] == 50
    assert found["redis_cache"].status == "fail"
    # Сбой кэша перепроверяется один раз (транзиентная причина), брокер — один запрос.
    assert set(asked) == {
        "redis://:pw-b@redis-broker:6379/0",
        "redis://:pw-c@redis-cache:6379/0",
    }
    for result in found.values():
        assert "pw-" not in repr(result)


async def test_redis_without_an_address_is_not_checked() -> None:
    found = await collect(deps(), ["redis_broker", "redis_cache"])
    assert {r.status for r in found.values()} == {"unknown"}
    assert "REDIS_PROBE_PASSWORD" in (found["redis_broker"].hint or "")


async def test_bus_dlq_row_comes_from_the_bus_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stats(session: object, now: datetime) -> Any:
        return repo.BusDlqStats(dead=2, failed=1, last_error="eds/letter.created: 500")

    monkeypatch.setattr(repo, "bus_dlq_stats", stats)
    found = await collect(deps(), ["bus_dlq"])
    assert found["bus_dlq"].status == "fail"
    assert found["bus_dlq"].cause == "bus_dlq"
    assert found["bus_dlq"].summary == "Шина: не доставлено: 2, не обработано: 1"


# --- права EDS (B-005) -------------------------------------------------------------------------


class EdsRights:
    """Подставные границы строки «Права сотрудников в EDS»: записанный отпечаток и публикация."""

    def __init__(self, stored: str | None, fail: bool = False) -> None:
        self.stored, self.fail, self.publishes = stored, fail, 0

    async def read(self) -> tuple[str | None, int]:
        return self.stored, 4

    async def publish(self) -> Any:
        from app.services.identity_catalog import CatalogSyncResult

        self.publishes += 1
        if self.fail:
            raise ConnectionError("bus password=hunter2")
        self.stored = current_fingerprint()
        return CatalogSyncResult(republished=True, users=4)


def current_fingerprint() -> str:
    from app.domain.platform_roles import eds_catalog_fingerprint

    return eds_catalog_fingerprint()


def eds_deps(box: EdsRights) -> Deps:
    return deps(eds_stored=box.read, eds_publish=box.publish)


async def test_eds_rights_published_row_is_ok_and_does_not_publish() -> None:
    box = EdsRights(current_fingerprint())
    found = await collect(eds_deps(box), ["eds_rights"])
    assert found["eds_rights"].status == "ok"
    assert box.publishes == 0


async def test_eds_rights_check_heals_a_changed_catalog_itself() -> None:
    box = EdsRights("0" * 64)
    found = await collect(eds_deps(box), ["eds_rights"])
    assert found["eds_rights"].status == "ok"
    assert box.publishes == 1
    assert box.stored == current_fingerprint()


async def test_eds_rights_failed_republish_is_a_cause_without_leaking_the_error_text() -> None:
    box = EdsRights("0" * 64, fail=True)
    found = await collect(eds_deps(box), ["eds_rights"])
    result = found["eds_rights"]
    assert result.status == "fail"
    assert result.cause == "eds_rights"
    assert result.error == "ConnectionError"
    assert "hunter2" not in repr(result)


async def test_eds_rights_cheap_pass_backs_off_but_heavy_and_manual_retry() -> None:
    box = EdsRights("0" * 64, fail=True)
    first = await collect(eds_deps(box), ["eds_rights"])
    carry = {k: v for k, v in first["eds_rights"].metrics.items() if k.startswith("_")}
    assert carry
    previous = {"eds_rights": carry}
    again = await collect(eds_deps(box), ["eds_rights"], "cheap", previous)
    assert box.publishes == 1  # пауза между повторами: шину не долбим каждую минуту
    assert again["eds_rights"].status == "fail"
    assert again["eds_rights"].error == "ConnectionError"
    await collect(eds_deps(box), ["eds_rights"], "manual", previous)
    assert box.publishes == 2  # «Перепроверить» повторяет сразу
