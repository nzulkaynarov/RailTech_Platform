"""Проход проверок внешних сервисов (M3-CRM-12, ADR-0024; W15-H3): факты → строки проверок →
инциденты → причины и оповещения.

Запись проверок и переходы инцидентов — в одной транзакции под advisory-блокировкой (фоновая задача
и «Проверить сейчас» не открывают два инцидента). Сломанное перепроверяется с затуханием
(`external_cause.recheck_due`: 1, 2, 5, 15 мин, дальше раз в 15) и снимается само, когда проверка
проходит. Оповещения — по причине, не по сервису: одно «сломано» после 15 минут и одно
«восстановлено»; отметка `alerted_at` ставится в транзакции до отправки, поэтому параллельный
проход (кнопка «Проверить» рядом с минутной задачей) не пришлёт второе сообщение, а рестарт процесса
не обнуляет состояние. Недоступный Telegram или релей не откатывает записанное.
"""

from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import external_cause as cause
from app.domain import external_incidents as inc
from app.domain.external_registry import registry
from app.domain.external_status import CAUSE_METRIC, CheckResult
from app.models.external_services import (
    ExternalCauseAlert,
    ExternalServiceCheck,
    ExternalServiceIncident,
)
from app.repositories import external_services as repo
from app.services.external_services.alerts import AlertSender
from app.services.external_services.collector import Collector, Run
from app.services.service_switches import SwitchBoard
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)
CHECKS_RETENTION = timedelta(days=8)
INCIDENTS_RETENTION = timedelta(days=90)
Reconcile = Callable[[], Awaitable[object]]
Causes = Callable[[datetime], Awaitable[tuple[list[cause.Group], dict[str, cause.State]]]]


@dataclass(frozen=True, slots=True)
class _Pending:
    """Оповещение, которое надо отправить после коммита."""

    kind: str  # alert | restore
    cause_key: str
    row_id: int
    text: inc.AlertText
    service_keys: list[str]


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
        causes: Causes | None = None,
    ) -> None:
        self._sessions = sessions
        self._collector = collector
        self._alerts = alerts
        self._settings = settings
        self._board = board
        self._reconcile = reconcile
        self._on_recorded = on_recorded
        self._causes = causes

    async def run(
        self, run: Run, now: datetime, keys: Collection[str] | None = None
    ) -> list[CheckResult]:
        specs = registry(await self._collector.providers())
        explicit = keys is not None
        if keys is None:
            tier = "heavy" if run == "heavy" else "cheap"
            keys = [s.key for s in specs if tier in s.tiers]
        if run == "cheap" and self._reconcile is not None:
            await self._safe_reconcile()
        async with self._sessions() as session:
            previous = {
                k: dict(r.metrics) for k, r in (await repo.latest_checks(session, "heavy")).items()
            }
        if run == "cheap" and not explicit:
            keys = await self._skip_backing_off(keys, now)
        disabled = await self._board.disabled_keys()
        results = await self._collector.collect(keys, run, now, previous, disabled)
        await self._record(results, run, now)
        if self._on_recorded is not None:
            self._on_recorded()
        await self._notify(now)
        if run == "heavy" and not explicit:
            await self._purge(now)
        return results

    async def recheck_broken(self, now: datetime) -> list[CheckResult]:
        """Перепроверить сломанные сервисы тяжёлого уровня по затуханию (дешёвые — минутный проход).

        Нужен для сервисов вроде сертификатов: без него упавшее «видно» бы только раз в 15 минут.
        """
        specs = registry(await self._collector.providers())
        heavy_only = [s.key for s in specs if "cheap" not in s.tiers]
        due = await self._due_failed(heavy_only, now)
        if not due:
            return []
        return await self.run("heavy", now, keys=due)

    async def _failed_state(self) -> tuple[dict[str, ExternalServiceCheck], dict[str, int]]:
        async with self._sessions() as session:
            return await repo.latest_checks(session), await repo.fail_streaks(session)

    async def _due_failed(self, keys: Collection[str], now: datetime) -> list[str]:
        latest, streaks = await self._failed_state()
        return [
            k
            for k in keys
            if (row := latest.get(k)) is not None
            and row.status == "fail"
            and cause.recheck_due(streaks.get(k, 1), row.checked_at, now)
        ]

    async def _skip_backing_off(self, keys: Collection[str], now: datetime) -> list[str]:
        """Сломанное сервис перепроверяется по затуханию, остальное — каждую минуту."""
        latest, streaks = await self._failed_state()
        out: list[str] = []
        for key in keys:
            row = latest.get(key)
            backing_off = (
                row is not None
                and row.status == "fail"
                and not cause.recheck_due(streaks.get(key, 1), row.checked_at, now)
            )
            if not backing_off:
                out.append(key)
        return out

    async def _safe_reconcile(self) -> None:
        if self._reconcile is None:
            return
        try:
            await self._reconcile()
        except Exception as exc:  # noqa: BLE001 — сверка выключателей не роняет проверки
            logger.warning("external_switch_reconcile_failed", error=type(exc).__name__)

    async def _record(self, results: Sequence[CheckResult], run: Run, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            await repo.lock(session)
            open_ = await repo.open_incidents(session, for_update=True)
            for result in results:
                session.add(_check_row(result, run, now))
                await _apply(session, open_.get(result.key), result, now)

    async def _notify(self, now: datetime) -> None:
        """Журнал причин и оповещения: по одному «сломано» (от 15 мин) и «восстановлено»."""
        if self._causes is None:
            return
        try:
            pending = await self._sync_causes(now)
        except Exception as exc:  # noqa: BLE001 — сбой журнала причин не роняет проход проверок
            logger.warning("external_causes_failed", error=type(exc).__name__)
            return
        for item in pending:
            delivered = await self._alerts.send(item.text, item.cause_key)
            if item.kind == "alert" and not delivered:
                await self._unclaim(item.row_id)
            elif delivered:
                await self._mark_incidents(item, now)

    async def _sync_causes(self, now: datetime) -> list[_Pending]:
        assert self._causes is not None  # noqa: S101 — проверено в `_notify`
        groups, states = await self._causes(now)
        by_id = {g.id: g for g in groups}
        tz = (await self._settings.get()).business_hours.timezone
        pending: list[_Pending] = []
        async with self._sessions() as session, session.begin():
            await repo.lock(session)
            rows = await repo.open_causes(session, for_update=True)
            known = {
                k: cause.OpenCause(k, r.started_at, r.alerted_at, tuple(r.service_keys))
                for k, r in rows.items()
            }
            for step in cause.plan_alerts(groups, known, states, now):
                if step.kind == "open":
                    group = by_id[step.cause_key]
                    row = ExternalCauseAlert(
                        cause_key=step.cause_key,
                        started_at=step.started_at or now,
                        headline=group.headline,
                        service_keys=list(group.service_keys),
                    )
                    session.add(row)
                    await session.flush()
                    rows[step.cause_key] = row
                elif step.kind == "alert":
                    row = rows[step.cause_key]
                    group = by_id[step.cause_key]
                    row.alerted_at = now  # «занято» до отправки: параллельный проход не повторит
                    text = cause.broken_alert(group, row.started_at, now, tz)
                    pending.append(
                        _Pending("alert", step.cause_key, row.id, text, list(row.service_keys))
                    )
                else:
                    row = rows[step.cause_key]
                    row.ended_at = now
                    if step.kind == "restore" and row.alerted_at is not None:
                        row.recovery_alerted_at = now
                        text = cause.restored_alert(row.headline, now - row.started_at)
                        pending.append(
                            _Pending(
                                "restore", step.cause_key, row.id, text, list(row.service_keys)
                            )
                        )
        return pending

    async def _unclaim(self, row_id: int) -> None:
        """Оповещение не дошло ни в Telegram, ни на почту — следующий проход попробует снова."""
        async with self._sessions() as session, session.begin():
            row = await session.get(ExternalCauseAlert, row_id)
            if row is not None:
                row.alerted_at = None

    async def _mark_incidents(self, item: _Pending, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            if item.kind == "alert":
                await repo.mark_incidents(session, item.service_keys, alerted=now)
            else:
                await repo.mark_incidents(session, item.service_keys, recovered=now)

    async def _purge(self, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            removed = await repo.purge(session, now - CHECKS_RETENTION, now - INCIDENTS_RETENTION)
        logger.info("external_checks_purged", removed=removed)


def _check_row(result: CheckResult, run: Run, now: datetime) -> ExternalServiceCheck:
    metrics = dict(result.metrics)
    if result.cause is not None:
        metrics[CAUSE_METRIC] = result.cause
    return ExternalServiceCheck(
        service_key=result.key,
        checked_at=now,
        tier=run,
        status=result.status,
        latency_ms=result.latency_ms,
        summary=result.summary,
        error=result.error,
        hint=result.hint,
        metrics=metrics,
    )


async def _apply(
    session: AsyncSession,
    row: ExternalServiceIncident | None,
    result: CheckResult,
    now: datetime,
) -> None:
    """Инцидент сервиса — журнал «с … по …»: открывает `fail`, закрывает `ok`/`warn`."""
    state = None if row is None else inc.OpenIncident(row.id, row.started_at, row.alerted_at)
    step = inc.transition(state, result.status)
    if step == "open":
        session.add(
            ExternalServiceIncident(
                service_key=result.key,
                started_at=now,
                summary=result.summary,
                last_error=result.error,
            )
        )
        await session.flush()
    elif row is not None and step == "update":
        row.summary = result.summary
        row.last_error = result.error or row.last_error
    elif row is not None and step == "close":
        row.ended_at = now
