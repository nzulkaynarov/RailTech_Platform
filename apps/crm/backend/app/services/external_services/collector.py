"""Сбор фактов о внешних сервисах и вычисление статусов (M3-CRM-12, ADR-0024).

Каждая проба — со своим таймаутом; любая неожиданная ошибка пробы даёт `unknown` с её классом,
а не роняет весь проход. Платных вызовов моделей нет: вендоры — по журналу шлюза и его бюджетам.
Медленные части (SMTP-соединение, место в бакетах, сутки журнала) делает тяжёлый проход раз в
15 мин; дешёвый проход переносит их последний итог из `previous` (метрики последней
тяжёлой проверки).
"""

import asyncio
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
import structlog

from app.config import Settings
from app.domain import external_erp_events as erp_events_rules
from app.domain import external_erp_handoff as erp_handoff_rules
from app.domain import external_erp_reported as erp_reported_rules
from app.domain import external_erp_sync as erp_sync_rules
from app.domain import external_status as rules
from app.domain import external_vendor as vendor_rules
from app.domain import system_status
from app.domain.external_registry import vendor_of
from app.domain.external_status import CheckResult, HttpFacts, Metric
from app.domain.system_status import ErpFacts
from app.integrations import external_probes as probes
from app.integrations.litellm_admin import LiteLLMAdmin, ProviderBudget
from app.integrations.litellm_catalog import ModelCatalog
from app.integrations.s3 import ObjectStorage
from app.integrations.smtp import SmtpProbeError
from app.integrations.telegram import resolve_token
from app.repositories import external_services as repo
from app.security.secrets_store import SecretsStore
from app.services import backups as backup_rules
from app.services.ai_spend import SpendLogSource
from app.services.backups import BackupReader
from app.services.external_services.providers import providers as alias_providers
from app.services.mail import MailService
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)
Run = Literal["cheap", "heavy", "manual"]
PROBE_TIMEOUT_S = 20.0
HTTP_TIMEOUT_S = 8.0
WINDOW = timedelta(minutes=15)
DAY = timedelta(hours=24)
_DAY_KEYS = (
    "calls_24h",
    "failures_24h",
    "error_rate_24h",
    "p95_ms_24h",
    "spend_24h_usd",
    "fallback_24h",
)
_CARRY_PREFIXES = ("bucket.", "_smtp")


@dataclass
class Deps:
    config: Settings
    settings: SettingsService
    secrets: SecretsStore
    sessions: Any
    mail: MailService
    storage: ObjectStorage
    backups: BackupReader | None
    admin: LiteLLMAdmin
    spend_logs: SpendLogSource
    catalog: ModelCatalog
    erp_url: Callable[[], Awaitable[str]]
    transport: httpx.AsyncBaseTransport | None = None
    tls_probe: Callable[[str], Awaitable[probes.TlsProbe]] = probes.tls
    # Значения по умолчанию алиасов: строки вендоров есть и при недоступном шлюзе.
    defaults: Path | None = None
    # Коннектор «ERP» настроен (адрес и токен из «Подключений» или `.env`); не задан — по адресу.
    erp_configured: Callable[[], Awaitable[bool]] | None = None
    # Последний ответ ERP на `GET /health` (кэш коннектора 30 с): из него — сервисы ERP (M3-ERP-06).
    erp_facts: Callable[[], Awaitable[ErpFacts]] | None = None


class Collector:
    def __init__(self, deps: Deps) -> None:
        self._d = deps

    async def providers(self) -> dict[str, str | None]:
        return await alias_providers(self._d.catalog, self._d.defaults)

    async def collect(
        self,
        keys: Collection[str],
        run: Run,
        now: datetime,
        previous: Mapping[str, Mapping[str, Metric]],
        disabled: frozenset[str],
    ) -> list[CheckResult]:
        heavy = run != "cheap"
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, transport=self._d.transport) as http:
            ctx = _Run(self._d, http, now, heavy, previous, disabled)
            results = await asyncio.gather(*(ctx.safe(key) for key in keys))
        return list(results)


class _Run:
    """Один проход: общие для вендоров данные (журнал, бюджеты, алиасы) — один раз."""

    def __init__(
        self,
        deps: Deps,
        http: httpx.AsyncClient,
        now: datetime,
        heavy: bool,
        previous: Mapping[str, Mapping[str, Metric]],
        disabled: frozenset[str],
    ) -> None:
        self.d, self.http, self.now, self.heavy = deps, http, now, heavy
        self.previous, self.disabled = previous, disabled
        self._vendor_data: asyncio.Task[_VendorData] | None = None

    async def safe(self, key: str) -> CheckResult:
        try:
            return await asyncio.wait_for(self.check(key), PROBE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — сбой пробы не должен ронять проход
            logger.warning("external_check_failed", service=key, error=type(exc).__name__)
            return CheckResult(
                key,
                "unknown",
                "Проверка не выполнена — повторится автоматически",
                error=type(exc).__name__,
            )

    async def check(self, key: str) -> CheckResult:
        vendor = vendor_of(key)
        if vendor is not None:
            return await self.vendor(vendor)
        if key.startswith("tls."):
            return await self.tls(key.removeprefix("tls."))
        if key.startswith("erp."):
            return await self.erp_external(key)
        handler: dict[str, Callable[[], Awaitable[CheckResult]]] = {
            "telegram": self.telegram,
            "litellm": self.litellm,
            "langfuse": self.langfuse,
            "mail": self.mail,
            "s3": self.s3,
            "docling": self.docling,
            "backup": self.backup,
            "erp_sync": self.erp_sync,
            "erp_handoff": self.erp_handoff,
            "erp_events": self.erp_events,
        }
        return await handler[key]()

    async def telegram(self) -> CheckResult:
        token, source = await resolve_token(self.d.secrets, self.d.config)
        mode = self.d.config.telegram_mode
        if source == "none" or mode == "disabled":
            return rules.telegram(
                rules.TelegramFacts(configured=source != "none", mode=mode), self.now
            )
        p = await probes.telegram(self.http, token)
        facts = rules.TelegramFacts(
            configured=True,
            mode=mode,
            error=p.error,
            detail=p.detail,
            username=p.username,
            pending_updates=p.pending_updates,
            webhook_url=p.webhook_url,
            last_error_message=p.last_error_message,
            last_error_at=p.last_error_at,
            latency_ms=p.latency_ms,
        )
        return rules.telegram(facts, self.now)

    async def litellm(self) -> CheckResult:
        base = str(self.d.config.litellm_base_url).rstrip("/")
        live = await probes.http_health(self.http, f"{base}/health/liveliness")
        db: str | None = None
        if live.error is None:
            headers = {
                "Authorization": f"Bearer {self.d.config.litellm_api_key.get_secret_value()}"
            }
            try:
                ready = await self.http.get(f"{base}/health/readiness", headers=headers)
                body = ready.json() if ready.status_code < 400 else {}
                db = body.get("db") if isinstance(body, dict) else None
            except (httpx.HTTPError, ValueError):
                db = None
        return rules.litellm(rules.GatewayFacts(live, db if isinstance(db, str) else None))

    async def vendor(self, vendor: str) -> CheckResult:
        data = await self._vendors()
        prev = self.previous.get(f"vendor.{vendor}", {})
        day = (
            vendor_rules.day_metrics(data.day.get(vendor))
            if data.day is not None
            else {k: prev.get(k) for k in _DAY_KEYS if k in prev}
        )
        budget = data.budgets.get(vendor)
        facts = vendor_rules.VendorFacts(
            vendor=vendor,
            logs_available=data.window is not None,
            window=(data.window or {}).get(vendor),
            budget_spend=budget.spend if budget else None,
            budget_limit=budget.limit if budget else None,
            day=day,
            disabled=f"vendor.{vendor}" in self.disabled,
        )
        return vendor_rules.vendor(facts)

    async def _vendors(self) -> "_VendorData":
        if self._vendor_data is None:
            self._vendor_data = asyncio.ensure_future(self._load_vendors())
        return await self._vendor_data

    async def _load_vendors(self) -> "_VendorData":
        providers = await alias_providers(self.d.catalog, self.d.defaults)
        try:
            budgets = await self.d.admin.provider_budgets()
        except Exception as exc:  # noqa: BLE001 — бюджеты необязательны для статуса
            logger.info("provider_budgets_unavailable", error=type(exc).__name__)
            budgets = {}
        start = self.now - (DAY if self.heavy else WINDOW)
        try:
            logs = await self.d.spend_logs.fetch(start, self.now)
        except Exception as exc:  # noqa: BLE001 — журнал недоступен → «нет данных»
            logger.info("vendor_logs_unavailable", error=type(exc).__name__)
            return _VendorData(None, None, budgets)
        rows = [r for raw in logs.rows if (r := vendor_rules.to_call(raw, providers)) is not None]
        window = vendor_rules.stats(rows, self.now - WINDOW)
        day = vendor_rules.stats(rows, self.now - DAY) if self.heavy else None
        return _VendorData(window, day, budgets)

    async def erp_external(self, key: str) -> CheckResult:
        """Сервис ERP (M3-ERP-06): состояние передаёт ERP в `GET /health`, CRM его не пробует."""
        if self.d.erp_facts is None:
            return CheckResult(key, "unknown", "Связь с ERP не настроена в этом процессе")
        return erp_reported_rules.erp_external(key, await self.d.erp_facts())

    async def erp_sync(self) -> CheckResult:
        """Итог синхронизации сотрудников с ERP (FIX-11): ошибки задач, не пробный запрос."""
        probe = self.d.erp_configured
        configured = await probe() if probe is not None else bool(await self.d.erp_url())
        async with self.d.sessions() as session:
            with_access, failed, last_error = await repo.erp_sync_stats(session)
        return erp_sync_rules.erp_sync(
            erp_sync_rules.ErpSyncFacts(configured, with_access, failed, last_error)
        )

    async def erp_handoff(self) -> CheckResult:
        """Итог передач клиентов в ERP (FIX-31): ошибки и зависшие в очереди, не пробный запрос."""
        probe = self.d.erp_configured
        configured = await probe() if probe is not None else bool(await self.d.erp_url())
        async with self.d.sessions() as session:
            stats = await repo.erp_handoff_stats(session, self.now)
        return erp_handoff_rules.erp_handoff(
            erp_handoff_rules.ErpHandoffFacts(
                configured, stats.failed, stats.stuck, stats.pending, stats.last_error
            )
        )

    async def erp_events(self) -> CheckResult:
        """Итог приёма событий ERP (FIX-33): отклонённые, упавшие и зависшие, не пробный запрос."""
        async with self.d.sessions() as session:
            stats = await repo.erp_events_stats(session, self.now)
        return erp_events_rules.erp_events(
            erp_events_rules.ErpEventsFacts(
                stats.rejected, stats.failed, stats.stuck, stats.last_error
            )
        )

    async def langfuse(self) -> CheckResult:
        cfg = self.d.config
        secret = cfg.langfuse_secret_key.get_secret_value()
        if not cfg.langfuse_public_key or not secret:
            return rules.langfuse(rules.LangfuseFacts(configured=False))
        health, keys_ok = await probes.langfuse(
            self.http, str(cfg.langfuse_host), cfg.langfuse_public_key, secret
        )
        return rules.langfuse(rules.LangfuseFacts(True, health, keys_ok))

    async def mail(self) -> CheckResult:
        connection = (await self.d.mail.resolution()).connection
        async with self.d.sessions() as session:
            st = await repo.mail_stats(session, self.now - DAY)
        prev = self.previous.get("mail", {})
        probe_error, probe_detail, latency = (
            _str(prev.get("_smtp")),
            _str(prev.get("_smtp_detail")),
            None,
        )
        if self.heavy and connection is not None:
            probe_error, probe_detail = None, None
            try:
                latency = (await self.d.mail.transport.check(connection)).latency_ms
            except SmtpProbeError as exc:
                probe_error, probe_detail = exc.kind, exc.detail
        facts = rules.MailFacts(
            configured=connection is not None,
            sent_24h=st.sent,
            failed_24h=st.failed,
            queued=st.queued,
            oldest_queued_at=st.oldest_queued_at,
            last_error=st.last_error,
            last_failed_at=st.last_failed_at,
            last_sent_at=st.last_sent_at,
            probe_error=probe_error if connection is not None else None,
            probe_detail=probe_detail,
            probe_latency_ms=latency,
            paused="mail" in self.disabled,
        )
        result = rules.mail(facts, self.now)
        extra = {"_smtp": probe_error or "ok", "_smtp_detail": probe_detail}
        return _with_metrics(result, extra)

    async def s3(self) -> CheckResult:
        endpoint = str(self.d.config.s3_endpoint).rstrip("/")
        health = await probes.http_health(self.http, f"{endpoint}/health")
        prev = self.previous.get("s3", {})
        usage: dict[str, Metric] = {k: v for k, v in prev.items() if k.startswith(_CARRY_PREFIXES)}
        if self.heavy and health.error is None:
            usage = await self._bucket_usage()
        return rules.s3(health, usage)

    async def _bucket_usage(self) -> dict[str, Metric]:
        cfg = self.d.config
        out: dict[str, Metric] = {}
        for bucket in (cfg.s3_bucket_kb, cfg.s3_bucket_documents, cfg.s3_bucket_attachments):
            try:
                objects, size = await self.d.storage.bucket_usage(bucket)
            except Exception as exc:  # noqa: BLE001 — нет бакета/прав: место неизвестно
                logger.info("bucket_usage_failed", bucket=bucket, error=type(exc).__name__)
                continue
            out[f"bucket.{bucket}.bytes"] = size
            out[f"bucket.{bucket}.objects"] = objects
        return out

    async def docling(self) -> CheckResult:
        base = str(self.d.config.docling_url).rstrip("/")
        return rules.docling(await probes.http_health(self.http, f"{base}/health"))

    async def backup(self) -> CheckResult:
        if self.d.backups is None:
            facts = system_status.BackupFacts(False, False, None, None)
            return rules.backup(system_status.backup(self.now, facts), None)
        state = await self.d.backups.status(limit=0)
        facts = backup_rules.facts(state, self.now)
        hours = (
            round((self.now - facts.last_success).total_seconds() / 3600, 1)
            if facts.last_success
            else None
        )
        return rules.backup(system_status.backup(self.now, facts), hours, facts)

    async def tls(self, name: str) -> CheckResult:
        url = await self._tls_url(name)
        host, not_applicable = rules.tls_target(url)
        if host is None:
            return rules.tls(rules.TlsFacts(name, None, not_applicable=not_applicable))
        p = await self.d.tls_probe(host)
        days = rules.tls_days_left(p.not_after, self.now) if p.not_after else None
        return rules.tls(rules.TlsFacts(name, host, None, days, p.not_after, p.error, p.detail))

    async def _tls_url(self, name: str) -> str:
        if name == "crm":
            return (await self.d.settings.get()).company.crm_base_url
        if name == "erp":
            return await self.d.erp_url()
        origins = self.d.config.cabinet_origins
        return origins[0] if origins else ""


@dataclass(frozen=True, slots=True)
class _VendorData:
    window: dict[str, vendor_rules.VendorStats] | None
    day: dict[str, vendor_rules.VendorStats] | None
    budgets: Mapping[str, ProviderBudget]


def _with_metrics(result: CheckResult, extra: Mapping[str, Metric]) -> CheckResult:
    return CheckResult(
        result.key,
        result.status,
        result.summary,
        result.error,
        result.hint,
        result.latency_ms,
        {**result.metrics, **extra},
    )


def _str(raw: object) -> str | None:
    return raw if isinstance(raw, str) and raw and raw != "ok" else None


__all__ = ["Collector", "Deps", "HttpFacts", "Run"]
