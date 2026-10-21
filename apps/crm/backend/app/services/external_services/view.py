"""Чтение центра внешних сервисов (M3-CRM-12, ADR-0024): реестр + последние проверки + агрегаты.

Только чтение из БД, без проб: список строится из последней проверки каждого сервиса, агрегатов
за 24 ч / 7 дней, открытых инцидентов и выключателей. Кэш списка 15 с; проход проверок и
выключатель сбрасывают его. Сервисы ERP — «нет данных», пока ERP не передаёт (M3-ERP-06).
"""

import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import external_incidents as inc
from app.domain import external_registry as reg
from app.domain import external_status as rules
from app.domain.errors import NotFoundError
from app.domain.system_status import Component
from app.integrations.litellm_catalog import ModelCatalog
from app.models.auth import User
from app.models.external_services import (
    ExternalServiceCheck,
    ExternalServiceIncident,
    ExternalServiceSwitch,
)
from app.repositories import external_services as repo
from app.schemas.external_services import (
    ExternalServiceDetailOut,
    ExternalServiceOut,
    ExternalServicesOut,
    ExternalServicesSummary,
    IncidentOut,
    ServiceCheckOut,
    ServiceDayOut,
    ServiceSwitchOut,
)
from app.services.external_services.providers import providers as alias_providers
from app.services.service_switches import SwitchBoard
from app.services.settings import SettingsService

HISTORY_LIMIT = 300
INCIDENTS_LIMIT = 50


class ExternalServicesView:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        catalog: ModelCatalog,
        settings: SettingsService,
        board: SwitchBoard,
        defaults: Path | None = None,
        ttl_s: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = sessions
        self._catalog = catalog
        self._settings = settings
        self._board = board
        self._defaults = defaults
        self._ttl_s = ttl_s
        self._clock = clock
        self._cache: tuple[float, ExternalServicesOut] | None = None

    def invalidate(self) -> None:
        self._cache = None

    async def list(self, now: datetime) -> ExternalServicesOut:
        if self._cache is not None and self._clock() < self._cache[0]:
            return self._cache[1]
        providers = await self._providers()
        specs = reg.registry(providers)
        async with self._sessions() as session:
            ctx = await _Context.load(session, now)
        ctx.providers = providers
        services = [ctx.service(spec, now) for spec in specs]
        counts = inc.count((s.status, bool(s.switch and s.switch.disabled)) for s in services)
        checked = max((s.checked_at for s in services if s.checked_at), default=None)
        out = ExternalServicesOut(
            checked_at=checked,
            summary=_summary(counts),
            services=services,
        )
        self._cache = (self._clock() + self._ttl_s, out)
        return out

    async def get(self, key: str, now: datetime) -> ExternalServiceOut:
        found = next((s for s in (await self.list(now)).services if s.key == key), None)
        if found is None:
            raise NotFoundError("unknown external service")
        return found

    async def detail(self, key: str, now: datetime) -> ExternalServiceDetailOut:
        self.invalidate()
        service = await self.get(key, now)
        tz = (await self._settings.get()).business_hours.timezone
        async with self._sessions() as session:
            checks = await repo.history(session, key, now - timedelta(hours=24), HISTORY_LIMIT)
            incidents = await repo.incidents(
                session, key, now - timedelta(days=30), INCIDENTS_LIMIT
            )
            days = await repo.daily(session, key, now - timedelta(days=7), tz)
        return ExternalServiceDetailOut(
            service=service,
            checks=[_check_out(c) for c in checks],
            days=_days(days, now, tz),
            incidents=[_incident_out(i) for i in incidents],
        )

    async def summary(self, now: datetime) -> Component:
        """Строка «Внешние сервисы» на «Состоянии системы»."""
        data = await self.list(now)
        fails = [s.title for s in data.services if s.status == "fail"]
        warns = [s.title for s in data.services if s.status == "warn"]
        s = data.summary
        counts = inc.Counts(s.ok, s.warn, s.fail, s.unknown, s.off, s.disabled)
        return inc.summary_component(counts, fails, warns, now, checked=data.checked_at is not None)

    async def _providers(self) -> dict[str, str | None]:
        return await alias_providers(self._catalog, self._defaults)


def _summary(counts: inc.Counts) -> ExternalServicesSummary:
    return ExternalServicesSummary(
        ok=counts.ok,
        warn=counts.warn,
        fail=counts.fail,
        unknown=counts.unknown,
        off=counts.off,
        disabled=counts.disabled,
    )


class _Context:
    """Всё прочитанное из БД для одного построения списка."""

    def __init__(
        self,
        latest: Mapping[str, ExternalServiceCheck],
        day: Mapping[str, Mapping[str, int]],
        week: Mapping[str, Mapping[str, int]],
        p95: Mapping[str, int],
        incidents: Mapping[str, ExternalServiceIncident],
        switches: Mapping[str, ExternalServiceSwitch],
        names: Mapping[int, str],
        providers: Mapping[str, str | None] | None = None,
    ) -> None:
        self.latest, self.day, self.week, self.p95 = latest, day, week, p95
        self.incidents, self.switches, self.names = incidents, switches, names
        self.providers = providers or {}

    @classmethod
    async def load(cls, session: AsyncSession, now: datetime) -> "_Context":
        switches = await repo.switches(session)
        ids = {s.changed_by for s in switches.values() if s.changed_by is not None}
        names: dict[int, str] = {}
        if ids:
            rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
            names = {int(uid): str(name) for uid, name in rows.all()}
        return cls(
            latest=await repo.latest_checks(session),
            day=await repo.status_counts(session, now - timedelta(hours=24)),
            week=await repo.status_counts(session, now - timedelta(days=7)),
            p95=await repo.p95_latency(session, now - timedelta(hours=24)),
            incidents=await repo.open_incidents(session),
            switches=switches,
            names=names,
        )

    def service(self, spec: reg.ServiceSpec, now: datetime) -> ExternalServiceOut:
        result, checked_at, is_stale = self._result(spec, now)
        day = self.day.get(spec.key, {})
        incident = self.incidents.get(spec.key)
        no_fix = bool(result.metrics.get("_no_fix"))
        return ExternalServiceOut(
            key=spec.key,
            title=spec.title,
            purpose=spec.purpose,
            system=spec.system,
            source=spec.source,
            check=spec.check,
            frequency="erp"
            if spec.source == "erp"
            else ("minute" if "cheap" in spec.tiers else "quarter"),
            status=result.status,
            summary=result.summary,
            error=result.error,
            hint=result.hint,
            fix_path="/system" if is_stale else (None if no_fix else spec.fix_path),
            checked_at=checked_at,
            stale=is_stale,
            latency_ms=result.latency_ms,
            metrics={k: v for k, v in result.metrics.items() if not k.startswith("_")},
            uptime_24h=inc.uptime(day),
            uptime_7d=inc.uptime(self.week.get(spec.key, {})),
            checks_24h=sum(day.values()),
            failures_24h=day.get("fail", 0),
            p95_ms_24h=self.p95.get(spec.key),
            switch=self._switch(spec),
            incident=_incident_out(incident) if incident is not None else None,
        )

    def _result(
        self, spec: reg.ServiceSpec, now: datetime
    ) -> tuple[rules.CheckResult, datetime | None, bool]:
        row = self.latest.get(spec.key)
        switch = self.switches.get(spec.key)
        if spec.switch in ("vendor", "erp") and switch is not None and switch.disabled:
            # Выключатель действует сразу — не ждать следующей проверки, чтобы показать «выключен».
            summary = (
                "Выключен вручную — вызовы этого провайдера идут на запасную модель"
                if spec.vendor is not None
                else "Выключен вручную — ERP не обращается к этому сервису"
            )
            metrics = dict(row.metrics or {}) if row is not None else {}
            return (
                rules.CheckResult(spec.key, "off", summary, None, None, None, metrics),
                row.checked_at if row is not None else None,
                False,
            )
        if row is None:
            return (
                rules.CheckResult(spec.key, "unknown", rules.never_checked(spec.tiers)),
                None,
                False,
            )
        result = rules.CheckResult(
            spec.key,
            row.status,  # type: ignore[arg-type]
            row.summary,
            row.error,
            row.hint,
            row.latency_ms,
            dict(row.metrics or {}),
        )
        if rules.stale(row.checked_at, spec.tiers, now):
            summary, hint = rules.stale_summary(row.checked_at, now)
            return (
                rules.CheckResult(spec.key, "unknown", summary, None, hint, None, result.metrics),
                row.checked_at,
                True,
            )
        return result, row.checked_at, False

    def _switch(self, spec: reg.ServiceSpec) -> ServiceSwitchOut | None:
        if spec.switch is None:
            return None
        row = self.switches.get(spec.key)
        disabled = bool(row and row.disabled)
        problem = None
        effect = reg.SWITCH_EFFECTS[spec.switch]
        if spec.switch == "erp":
            effect = reg.ERP_SWITCH_EFFECTS.get(spec.key, effect)
        if spec.vendor is not None:
            effect = reg.switch_effect(spec.vendor, self.providers) if self.providers else effect
            problem = None if disabled else reg.switch_problem(spec.vendor, self.providers or {})
        return ServiceSwitchOut(
            kind=spec.switch,
            available=problem is None,
            disabled=disabled,
            effect=effect,
            problem=problem,
            reason=row.reason if row else None,
            changed_at=row.changed_at if row else None,
            changed_by=self.names.get(row.changed_by) if row and row.changed_by else None,
        )


def _incident_out(row: ExternalServiceIncident) -> IncidentOut:
    duration = int((row.ended_at - row.started_at).total_seconds()) if row.ended_at else None
    return IncidentOut(
        id=row.id,
        started_at=row.started_at,
        ended_at=row.ended_at,
        duration_s=duration,
        summary=row.summary,
        last_error=row.last_error,
        alerted=row.alerted_at is not None,
        recovery_alerted=row.recovery_alerted_at is not None,
    )


def _check_out(row: ExternalServiceCheck) -> ServiceCheckOut:
    return ServiceCheckOut(
        checked_at=row.checked_at,
        tier=row.tier,
        status=row.status,
        latency_ms=row.latency_ms,
        summary=row.summary,
        error=row.error,
    )


def _days(rows: Mapping[date, Mapping[str, int]], now: datetime, tz: str) -> list[ServiceDayOut]:
    today = now.astimezone(ZoneInfo(tz)).date()
    out = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        counts = rows.get(day, {})
        out.append(
            ServiceDayOut(
                day=day,
                ok=counts.get("ok", 0),
                warn=counts.get("warn", 0),
                fail=counts.get("fail", 0),
                unknown=counts.get("unknown", 0) + counts.get("off", 0),
                uptime=inc.uptime(counts),
            )
        )
    return out
