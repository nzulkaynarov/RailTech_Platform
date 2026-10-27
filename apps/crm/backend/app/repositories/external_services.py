"""Запросы центра внешних сервисов (M3-CRM-12, ADR-0024): проверки, агрегаты, инциденты, почта."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.external_erp_events import STUCK_AFTER_MINUTES as EVENTS_STUCK_AFTER_MINUTES
from app.domain.external_erp_events import WINDOW_DAYS as EVENTS_WINDOW_DAYS
from app.domain.external_erp_handoff import STUCK_AFTER_MINUTES
from app.models.auth import User
from app.models.bus import TABLES
from app.models.clients import Client
from app.models.email import EmailLog
from app.models.external_services import (
    ExternalCauseAlert,
    ExternalServiceCheck,
    ExternalServiceIncident,
    ExternalServiceSwitch,
)

LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtext('external_service_checks'))")
LATEST_SQL = text(
    """
    SELECT DISTINCT ON (service_key) id FROM external_service_checks
    WHERE (CAST(:tier AS varchar) IS NULL OR tier = CAST(:tier AS varchar))
    ORDER BY service_key, checked_at DESC, id DESC
    """
)
P95_SQL = text(
    """
    SELECT service_key,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95
    FROM external_service_checks
    WHERE checked_at >= :since AND latency_ms IS NOT NULL AND status IN ('ok', 'warn')
    GROUP BY service_key
    """
)
DAILY_SQL = text(
    """
    SELECT (checked_at AT TIME ZONE :tz)::date AS day, status, count(*) AS n
    FROM external_service_checks
    WHERE service_key = :key AND checked_at >= :since
    GROUP BY 1, 2 ORDER BY 1
    """
)


# «С какого времени не в порядке»: первая не-`ok` проверка после последней `ok` (в пределах срока).
SINCE_SQL = text(
    """
    SELECT c.service_key, min(c.checked_at) AS since
    FROM external_service_checks c
    WHERE c.status <> 'ok'
      AND c.checked_at > COALESCE(
        (SELECT max(o.checked_at) FROM external_service_checks o
         WHERE o.service_key = c.service_key AND o.status = 'ok'),
        '-infinity'::timestamptz)
    GROUP BY c.service_key
    """
)
# Сколько `fail` подряд у сервиса (после последней не-`fail` проверки) — основа затухания повторов.
FAIL_STREAK_SQL = text(
    """
    SELECT c.service_key, count(*) AS n
    FROM external_service_checks c
    WHERE c.status = 'fail'
      AND c.checked_at > COALESCE(
        (SELECT max(o.checked_at) FROM external_service_checks o
         WHERE o.service_key = c.service_key AND o.status <> 'fail'),
        '-infinity'::timestamptz)
    GROUP BY c.service_key
    """
)


async def lock(session: AsyncSession) -> None:
    """Один писатель проверок за раз (фоновая задача и «Проверить сейчас»)."""
    await session.execute(LOCK_SQL)


async def latest_checks(
    session: AsyncSession, tier: str | None = None
) -> dict[str, ExternalServiceCheck]:
    ids = [row.id for row in (await session.execute(LATEST_SQL, {"tier": tier})).all()]
    if not ids:
        return {}
    rows = await session.scalars(
        select(ExternalServiceCheck).where(ExternalServiceCheck.id.in_(ids))
    )
    return {r.service_key: r for r in rows}


async def status_counts(session: AsyncSession, since: datetime) -> dict[str, dict[str, int]]:
    stmt = (
        select(ExternalServiceCheck.service_key, ExternalServiceCheck.status, func.count())
        .where(ExternalServiceCheck.checked_at >= since)
        .group_by(ExternalServiceCheck.service_key, ExternalServiceCheck.status)
    )
    out: dict[str, dict[str, int]] = {}
    for key, status, n in (await session.execute(stmt)).all():
        out.setdefault(key, {})[status] = int(n)
    return out


async def p95_latency(session: AsyncSession, since: datetime) -> dict[str, int]:
    rows = (await session.execute(P95_SQL, {"since": since})).all()
    return {r.service_key: int(r.p95) for r in rows if r.p95 is not None}


async def open_incidents(
    session: AsyncSession, *, for_update: bool = False
) -> dict[str, ExternalServiceIncident]:
    stmt = select(ExternalServiceIncident).where(ExternalServiceIncident.ended_at.is_(None))
    if for_update:
        stmt = stmt.with_for_update()
    return {r.service_key: r for r in await session.scalars(stmt)}


async def unhealthy_since(session: AsyncSession) -> dict[str, datetime]:
    """Сервис → когда впервые обнаружено: первая не-`ok` проверка текущей полосы."""
    return {r.service_key: r.since for r in (await session.execute(SINCE_SQL)).all()}


async def last_recovered(session: AsyncSession, since: datetime) -> dict[str, datetime]:
    """Сервис → когда закрыт последний инцидент за период («восстановлено в …»)."""
    stmt = (
        select(ExternalServiceIncident.service_key, func.max(ExternalServiceIncident.ended_at))
        .where(
            ExternalServiceIncident.ended_at.is_not(None),
            ExternalServiceIncident.ended_at >= since,
        )
        .group_by(ExternalServiceIncident.service_key)
    )
    return {key: at for key, at in (await session.execute(stmt)).all() if at is not None}


async def fail_streaks(session: AsyncSession) -> dict[str, int]:
    """Сервис → сколько проверок `fail` подряд (только сервисы с такой полосой)."""
    return {r.service_key: int(r.n) for r in (await session.execute(FAIL_STREAK_SQL)).all()}


async def open_causes(
    session: AsyncSession, *, for_update: bool = False
) -> dict[str, ExternalCauseAlert]:
    stmt = select(ExternalCauseAlert).where(ExternalCauseAlert.ended_at.is_(None))
    if for_update:
        stmt = stmt.with_for_update()
    return {r.cause_key: r for r in await session.scalars(stmt)}


async def mark_incidents(
    session: AsyncSession,
    service_keys: list[str],
    *,
    alerted: datetime | None = None,
    recovered: datetime | None = None,
) -> None:
    """Отметить оповещение в инцидентах сервисов причины (сбой — открытые, возврат — закрытые)."""
    if not service_keys:
        return
    stmt = select(ExternalServiceIncident).where(
        ExternalServiceIncident.service_key.in_(service_keys)
    )
    if alerted is not None:
        stmt = stmt.where(
            ExternalServiceIncident.ended_at.is_(None), ExternalServiceIncident.alerted_at.is_(None)
        )
    else:
        stmt = stmt.where(
            ExternalServiceIncident.ended_at.is_not(None),
            ExternalServiceIncident.alerted_at.is_not(None),
            ExternalServiceIncident.recovery_alerted_at.is_(None),
        )
    for row in await session.scalars(stmt):
        if alerted is not None:
            row.alerted_at = alerted
        else:
            row.recovery_alerted_at = recovered


async def history(
    session: AsyncSession, key: str, since: datetime, limit: int
) -> list[ExternalServiceCheck]:
    stmt = (
        select(ExternalServiceCheck)
        .where(ExternalServiceCheck.service_key == key, ExternalServiceCheck.checked_at >= since)
        .order_by(ExternalServiceCheck.checked_at.desc(), ExternalServiceCheck.id.desc())
        .limit(limit)
    )
    return list(await session.scalars(stmt))


async def incidents(
    session: AsyncSession, key: str, since: datetime, limit: int
) -> list[ExternalServiceIncident]:
    stmt = (
        select(ExternalServiceIncident)
        .where(
            ExternalServiceIncident.service_key == key,
            (ExternalServiceIncident.ended_at.is_(None))
            | (ExternalServiceIncident.started_at >= since),
        )
        .order_by(ExternalServiceIncident.started_at.desc())
        .limit(limit)
    )
    return list(await session.scalars(stmt))


async def daily(
    session: AsyncSession, key: str, since: datetime, tz: str
) -> dict[Any, dict[str, int]]:
    out: dict[Any, dict[str, int]] = {}
    for row in (await session.execute(DAILY_SQL, {"key": key, "since": since, "tz": tz})).all():
        out.setdefault(row.day, {})[row.status] = int(row.n)
    return out


async def switches(session: AsyncSession) -> dict[str, ExternalServiceSwitch]:
    return {r.service_key: r for r in await session.scalars(select(ExternalServiceSwitch))}


async def purge(session: AsyncSession, checks_before: datetime, incidents_before: datetime) -> int:
    result = await session.execute(
        delete(ExternalServiceCheck).where(ExternalServiceCheck.checked_at < checks_before)
    )
    await session.execute(
        delete(ExternalServiceIncident).where(
            ExternalServiceIncident.ended_at.is_not(None),
            ExternalServiceIncident.ended_at < incidents_before,
        )
    )
    await session.execute(
        delete(ExternalCauseAlert).where(
            ExternalCauseAlert.ended_at.is_not(None),
            ExternalCauseAlert.ended_at < incidents_before,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


@dataclass(frozen=True, slots=True)
class MailLogStats:
    sent: int
    failed: int
    queued: int
    oldest_queued_at: datetime | None
    last_error: str | None
    last_failed_at: datetime | None
    last_sent_at: datetime | None


async def mail_stats(session: AsyncSession, since: datetime) -> MailLogStats:
    """Журнал писем: отправлено/ошибки за окно, письма в очереди, последний сбой (любой даты)."""
    counts = dict(
        (
            await session.execute(
                select(EmailLog.status, func.count())
                .where(EmailLog.created_at >= since)
                .group_by(EmailLog.status)
            )
        ).all()
    )
    queued = await session.execute(
        select(func.count(), func.min(EmailLog.created_at)).where(EmailLog.status == "queued")
    )
    queued_n, oldest = queued.one()
    failed = (
        await session.execute(
            select(EmailLog.error, EmailLog.updated_at)
            .where(EmailLog.status == "failed")
            .order_by(EmailLog.updated_at.desc())
            .limit(1)
        )
    ).first()
    last_sent = await session.scalar(select(func.max(EmailLog.sent_at)))
    return MailLogStats(
        sent=int(counts.get("sent", 0)),
        failed=int(counts.get("failed", 0)),
        queued=int(queued_n or 0),
        oldest_queued_at=oldest,
        last_error=failed.error if failed else None,
        last_failed_at=failed.updated_at if failed else None,
        last_sent_at=last_sent,
    )


async def erp_sync_stats(session: AsyncSession) -> tuple[int, int, str | None]:
    """Синхронизация сотрудников с ERP: (с доступом к ERP, с ошибкой, последняя ошибка)."""
    with_access = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.is_active.is_(True), User.platform_access.contains(["erp"]))
    )
    failed = await session.scalar(
        select(func.count()).select_from(User).where(User.erp_sync_error.is_not(None))
    )
    last_error = await session.scalar(
        select(User.erp_sync_error)
        .where(User.erp_sync_error.is_not(None))
        .order_by(User.updated_at.desc())
        .limit(1)
    )
    return int(with_access or 0), int(failed or 0), last_error


@dataclass(frozen=True, slots=True)
class ErpHandoffStats:
    failed: int
    stuck: int
    pending: int
    last_error: str | None


async def erp_handoff_stats(session: AsyncSession, now: datetime) -> ErpHandoffStats:
    """Передачи клиентов в ERP: с ошибкой, зависшие и текущие, последняя ошибка с именем клиента."""
    stuck_before = now - timedelta(minutes=STUCK_AFTER_MINUTES)
    failed = await session.scalar(
        select(func.count()).select_from(Client).where(Client.erp_handoff_status == "failed")
    )
    pending = await session.scalar(
        select(func.count()).select_from(Client).where(Client.erp_handoff_status == "pending")
    )
    stuck = await session.scalar(
        select(func.count())
        .select_from(Client)
        .where(Client.erp_handoff_status == "pending", Client.updated_at < stuck_before)
    )
    last = (
        await session.execute(
            select(Client.name, Client.erp_handoff_error)
            .where(Client.erp_handoff_status == "failed", Client.erp_handoff_error.is_not(None))
            .order_by(Client.updated_at.desc())
            .limit(1)
        )
    ).first()
    return ErpHandoffStats(
        failed=int(failed or 0),
        stuck=int(stuck or 0),
        pending=int(pending or 0),
        last_error=f"{last[0]}: {last[1]}" if last else None,
    )


@dataclass(frozen=True, slots=True)
class ErpEventsStats:
    dead: int
    failed: int
    stuck: int
    last_error: str | None


async def erp_events_stats(session: AsyncSession, now: datetime) -> ErpEventsStats:
    """Шина rt_bus за неделю: события ERP, не обработанные (`failed`) и зависшие `received`, и
    события CRM, не доставленные ERP (`dead`); последняя ошибка.
    """
    since = now - timedelta(days=EVENTS_WINDOW_DAYS)
    stuck_before = now - timedelta(minutes=EVENTS_STUCK_AFTER_MINUTES)
    inbox, delivery = TABLES.inbox.c, TABLES.delivery.c
    from_erp = (inbox.publisher == "erp", inbox.received_at >= since)

    async def count(table: Any, *conditions: Any) -> int:
        total = await session.scalar(select(func.count()).select_from(table).where(*conditions))
        return int(total or 0)

    last_inbox = (
        await session.execute(
            select(inbox.type, inbox.error)
            .where(*from_erp, inbox.status == "failed", inbox.error.is_not(None))
            .order_by(inbox.received_at.desc())
            .limit(1)
        )
    ).first()
    last_dead = (
        await session.execute(
            select(delivery.event_type, delivery.last_error)
            .where(
                delivery.status == "dead",
                delivery.subscriber == "erp",
                delivery.created_at >= since,
                delivery.last_error.is_not(None),
            )
            .order_by(delivery.updated_at.desc())
            .limit(1)
        )
    ).first()
    last = last_inbox or last_dead
    return ErpEventsStats(
        dead=await count(
            TABLES.delivery,
            delivery.status == "dead",
            delivery.subscriber == "erp",
            delivery.created_at >= since,
        ),
        failed=await count(TABLES.inbox, *from_erp, inbox.status == "failed"),
        stuck=await count(
            TABLES.inbox,
            *from_erp,
            inbox.status == "received",
            inbox.received_at < stuck_before,
            (inbox.next_attempt_at.is_(None)) | (inbox.next_attempt_at < stuck_before),
        ),
        last_error=f"{last[0]}: {last[1]}"[:500] if last else None,
    )
