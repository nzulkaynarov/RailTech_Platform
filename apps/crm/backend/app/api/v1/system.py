"""Резервные копии (admin): статус и «Сделать сейчас» — ADR-0013, runbook backup-restore.md.

Восстановления в интерфейсе нет и не будет: оно разрушительно, его выполняет администратор
сервера по runbook (`scripts/restore.sh`).
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status

from app.api.deps import ContainerDep, require
from app.domain.errors import ConflictError
from app.domain.system_status import STALE_BACKUP_HOURS, request_unanswered
from app.schemas.setup import BackupDatabase, BackupItem, BackupsOut
from app.security import audit
from app.security.principal import Principal
from app.services.backups import BackupReader, BackupStatus, facts

router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _out(state: BackupStatus, now: datetime, service: BackupReader) -> BackupsOut:
    last = state.last_success_at
    known = facts(state, now)
    stuck = request_unanswered(now, known)
    return BackupsOut(
        available=state.available,
        source="rustfs" if state.source == "rustfs" else "volume",
        can_request=service.can_request,
        error=_error(state.error),
        databases=[BackupDatabase(name=n, last_success_at=at) for n, at in state.databases.items()],
        last_success_at=last,
        stale=last is None or now - last > timedelta(hours=STALE_BACKUP_HOURS),
        requested_at=None if stuck else state.requested_at,
        daemon_alive=known.daemon_alive,
        request_stuck=stuck,
        items=[BackupItem(name=i.name, at=i.at, size_bytes=i.size_bytes) for i in state.items],
    )


def _error(code: str | None) -> Literal["bucket_missing", "access_denied", "unreachable"] | None:
    if code is None:
        return None
    return (
        "bucket_missing"
        if code == "bucket_missing"
        else ("access_denied" if code == "access_denied" else "unreachable")
    )


@router.get("/backups", response_model=BackupsOut)
async def list_backups(
    _: Annotated[Principal, Depends(require("backups", "read"))], container: ContainerDep
) -> BackupsOut:
    """Последние бэкапы: том `backups` (dev) или бакет `backups` RustFS (прод, M5-CRM-01)."""
    service = container.backup_service
    return _out(await service.status(), datetime.now(UTC), service)


@router.post("/backups", response_model=BackupsOut, status_code=status.HTTP_202_ACCEPTED)
async def request_backup(
    principal: Annotated[Principal, Depends(require("backups", "write"))],
    container: ContainerDep,
) -> BackupsOut:
    """Запросить бэкап вне расписания: сервис бэкапа начнёт его в течение ~30 с.

    409, если том бэкапов не смонтирован в api или бэкап делает VPS 2 (источник — бакет RustFS:
    запускать на сервере базы, `infra/deploy/backup-now.sh`). Повторный запрос до начала — без
    изменений; запрос, который сервис не забрал за 2 мин, ставится заново.
    """
    service = container.backup_service
    if not service.can_request:
        raise ConflictError("backups are made on the database server (VPS 2)")
    if not (await service.status(limit=0)).available:
        raise ConflictError("backup volume is not mounted")
    now = datetime.now(UTC)
    requested = await service.request_now(now)
    async with container.session_factory() as session, session.begin():
        await audit.record(
            session,
            principal.actor,
            "system.backup_requested",
            "system",
            "backups",
            after={"requested_at": requested.isoformat()},
        )
    return _out(await service.status(), now, service)
