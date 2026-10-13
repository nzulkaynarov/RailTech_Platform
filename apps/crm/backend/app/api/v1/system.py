"""Резервные копии (admin): статус и «Сделать сейчас» — ADR-0013, runbook backup-restore.md.

Восстановления в интерфейсе нет и не будет: оно разрушительно, его выполняет администратор
сервера по runbook (`scripts/restore.sh`).
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import ContainerDep, require
from app.domain.errors import ConflictError
from app.domain.system_status import request_unanswered
from app.schemas.setup import BackupItem, BackupsOut
from app.security import audit
from app.security.principal import Principal
from app.services.backups import STALE_AFTER_HOURS, BackupStatus, facts

router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _out(state: BackupStatus, now: datetime) -> BackupsOut:
    last = state.last_success_at
    known = facts(state, now)
    stuck = request_unanswered(now, known)
    return BackupsOut(
        available=state.available,
        last_success_at=last,
        stale=last is None or now - last > timedelta(hours=STALE_AFTER_HOURS),
        requested_at=None if stuck else state.requested_at,
        daemon_alive=known.daemon_alive,
        request_stuck=stuck,
        items=[BackupItem(name=i.name, at=i.at, size_bytes=i.size_bytes) for i in state.items],
    )


@router.get("/backups", response_model=BackupsOut)
async def list_backups(
    _: Annotated[Principal, Depends(require("backups", "read"))], container: ContainerDep
) -> BackupsOut:
    """Последние бэкапы из тома `backups` (каталоги `<UTC-штамп>`), время последнего успеха."""
    return _out(await container.backup_service.status(), datetime.now(UTC))


@router.post("/backups", response_model=BackupsOut, status_code=status.HTTP_202_ACCEPTED)
async def request_backup(
    principal: Annotated[Principal, Depends(require("backups", "write"))],
    container: ContainerDep,
) -> BackupsOut:
    """Запросить бэкап вне расписания: сервис бэкапа начнёт его в течение ~30 с.

    409, если том бэкапов не смонтирован в api. Повторный запрос до начала — без изменений;
    запрос, который сервис не забрал за 2 мин, ставится заново.
    """
    service = container.backup_service
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
    return _out(await service.status(), now)
