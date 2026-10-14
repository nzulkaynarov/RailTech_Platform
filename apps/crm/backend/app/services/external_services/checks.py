"""Проход проверок внешних сервисов (M3-CRM-12, ADR-0024): факты → строки проверок → инциденты →
оповещения.

Запись проверок и переходы инцидентов — в одной транзакции под advisory-блокировкой (фоновая задача
и «Проверить сейчас» не открывают два инцидента). Оповещения — после коммита: недоступный Telegram
или релей не откатывает состояние; отметка `alerted_at` ставится только после доставки.
"""

from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import external_incidents as inc
from app.domain.external_registry import ServiceSpec, find, registry
from app.domain.external_status import CheckResult
from app.models.external_services import ExternalServiceCheck, ExternalServiceIncident
from app.repositories import external_services as repo
from app.services.external_services.alerts import AlertSender
from app.services.external_services.collector import Collector, Run
from app.services.service_switches import SwitchBoard
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)
CHECKS_RETENTION = timedelta(days=8)
INCIDENTS_RETENTION = timedelta(days=90)
Reconcile = Callable[[], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class _Event:
    kind: str  # open | close
    key: str
    incident_id: int
    started_at: datetime
    ended_at: datetime | None
    result: CheckResult
    alerted_at: datetime | None
    last_alert_at: datetime | None


class ExternalChecks:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        collector: Collector,
        alerts: AlertSender,
        settings: SettingsService,
        board: SwitchBoard,
        reconcile: Reconcile | None = None,
        on_recorded: Callable[[], None] | None = None,
    ) -> None:
        self._sessions = sessions
        self._collector = collector
        self._alerts = alerts
        self._settings = settings
        self._board = board
        self._reconcile = reconcile
        self._on_recorded = on_recorded

    async def run(
        self, run: Run, now: datetime, keys: Collection[str] | None = None
    ) -> list[CheckResult]:
        specs = registry(await self._collector.providers())
        if keys is None:
            tier = "heavy" if run == "heavy" else "cheap"
            keys = [s.key for s in specs if tier in s.tiers]
        if run == "cheap" and self._reconcile is not None:
            await self._safe_reconcile()
        async with self._sessions() as session:
            previous = {
                k: dict(r.metrics) for k, r in (await repo.latest_checks(session, "heavy")).items()
            }
        disabled = await self._board.disabled_keys()
        results = await self._collector.collect(keys, run, now, previous, disabled)
        events = await self._record(results, run, now)
        if self._on_recorded is not None:
            self._on_recorded()
        await self._notify(events, specs, now)
        if run == "heavy":
            await self._purge(now)
        return results

    async def _safe_reconcile(self) -> None:
        if self._reconcile is None:
            return
        try:
            await self._reconcile()
        except Exception as exc:  # noqa: BLE001 — сверка выключателей не роняет проверки
            logger.warning("external_switch_reconcile_failed", error=type(exc).__name__)

    async def _record(
        self, results: Sequence[CheckResult], run: Run, now: datetime
    ) -> list[_Event]:
        events: list[_Event] = []
        async with self._sessions() as session, session.begin():
            await repo.lock(session)
            open_ = await repo.open_incidents(session, for_update=True)
            last_alerts = await repo.last_alerts(session)
            for result in results:
                session.add(_check_row(result, run, now))
                event = await _apply(session, open_.get(result.key), result, now)
                if event is not None:
                    events.append(_with_last_alert(event, last_alerts.get(result.key)))
        return events

    async def _notify(self, events: list[_Event], specs: list[ServiceSpec], now: datetime) -> None:
        cfg = await self._settings.get()
        repeat = timedelta(minutes=cfg.service_alerts.repeat_minutes)
        base = cfg.company.crm_base_url.rstrip("/")
        for event in events:
            spec = find(specs, event.key)
            title = spec.title if spec else event.key
            url = f"{base}/external-services/{event.key}"
            if event.kind == "open" and inc.failure_alert_due(event.last_alert_at, now, repeat):
                r = event.result
                text = inc.failure_alert(title, r.summary, r.error, r.hint, url)
                if await self._alerts.send(text, event.key):
                    await self._mark(event.incident_id, alerted=now)
            elif event.kind == "close" and inc.recovery_alert_due(event.alerted_at):
                lasted = (event.ended_at or now) - event.started_at
                if await self._alerts.send(inc.recovery_alert(title, lasted, url), event.key):
                    await self._mark(event.incident_id, recovered=now)

    async def _mark(
        self,
        incident_id: int,
        *,
        alerted: datetime | None = None,
        recovered: datetime | None = None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(ExternalServiceIncident, incident_id)
            if row is None:
                return
            if alerted is not None:
                row.alerted_at = alerted
            if recovered is not None:
                row.recovery_alerted_at = recovered

    async def _purge(self, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            removed = await repo.purge(session, now - CHECKS_RETENTION, now - INCIDENTS_RETENTION)
        logger.info("external_checks_purged", removed=removed)


def _check_row(result: CheckResult, run: Run, now: datetime) -> ExternalServiceCheck:
    return ExternalServiceCheck(
        service_key=result.key,
        checked_at=now,
        tier=run,
        status=result.status,
        latency_ms=result.latency_ms,
        summary=result.summary,
        error=result.error,
        hint=result.hint,
        metrics=dict(result.metrics),
    )


async def _apply(
    session: AsyncSession,
    row: ExternalServiceIncident | None,
    result: CheckResult,
    now: datetime,
) -> _Event | None:
    state = None if row is None else inc.OpenIncident(row.id, row.started_at, row.alerted_at)
    step = inc.transition(state, result.status)
    if step == "open":
        row = ExternalServiceIncident(
            service_key=result.key, started_at=now, summary=result.summary, last_error=result.error
        )
        session.add(row)
        await session.flush()
        return _Event("open", result.key, row.id, now, None, result, None, None)
    if row is None:
        return None
    if step == "update":
        row.summary = result.summary
        row.last_error = result.error or row.last_error
        return None
    if step == "close":
        row.ended_at = now
        return _Event(
            "close", result.key, row.id, row.started_at, now, result, row.alerted_at, None
        )
    return None


def _with_last_alert(event: _Event, last: datetime | None) -> _Event:
    return replace(event, last_alert_at=last)
