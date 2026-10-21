"""Статус бэкапов и запрос «сделать сейчас» (ADR-0013, runbook backup-restore.md).

Источник статуса выбирает `Settings.backup_source` (M5-CRM-01): том backup-контейнера (этот
модуль, dev) или бакет `backups` RustFS, куда пишет VPS 2 (`services/backups_rustfs.py`, прод).

Бэкапы пишет контейнер `backup` (`ops/backup.sh`) в том `backups`: каталоги
`<UTC-штамп>/` и файл `last_success`. api смонтирован в тот же том и только читает его,
а «сделать сейчас» — файл-флаг `request_now`, который демон бэкапа проверяет раз в 30 с.
Демон раз в 30 с обновляет `heartbeat` (epoch): свежее 2 мин — сервис жив; файла нет
вовсе — демон на этом сервере не развёрнут (dev), это предупреждение, а не авария.
pg_dump в образе api нет (он только в образе backup), поэтому сам бэкап api не запускает.
Восстановление — только с сервера (`scripts/restore.sh`), в интерфейсе его нет.
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.domain.system_status import DAEMON_SILENT_AFTER, REQUEST_UNANSWERED_AFTER, BackupFacts

REQUEST_FILE = "request_now"
LAST_SUCCESS_FILE = "last_success"
HEARTBEAT_FILE = "heartbeat"
STAMP = re.compile(r"^\d{8}T\d{6}Z$")
STALE_AFTER_HOURS = 26


@dataclass(frozen=True, slots=True)
class BackupEntry:
    name: str
    at: datetime
    size_bytes: int


@dataclass(frozen=True, slots=True)
class BackupStatus:
    available: bool
    last_success_at: datetime | None
    requested_at: datetime | None
    items: list[BackupEntry]
    heartbeat_at: datetime | None = None
    # Файл heartbeat существует (пусть и устаревший/битый): демон здесь развёрнут.
    heartbeat_seen: bool = False
    source: str = "volume"
    # Только для `rustfs`: код ошибки чтения бакета и база → время последней копии.
    error: str | None = None
    error_detail: str | None = None
    databases: dict[str, datetime | None] = field(default_factory=dict)


class BackupReader(Protocol):
    """Источник статуса бэкапов: том (`BackupService`) или бакет RustFS (`RustfsBackupService`)."""

    can_request: bool

    async def status(self, limit: int = 30) -> BackupStatus: ...

    async def request_now(self, now: datetime) -> datetime: ...


class BackupService:
    can_request = True

    def __init__(self, root: Path) -> None:
        self._root = root

    async def status(self, limit: int = 30) -> BackupStatus:
        return await asyncio.to_thread(self._status, limit)

    async def request_now(self, now: datetime) -> datetime:
        """Поставить флаг; повторный запрос до начала бэкапа ничего не меняет.

        Флаг старше 2 мин (демон его не забрал) ставится заново с новым временем.
        """
        return await asyncio.to_thread(self._request, now)

    def _status(self, limit: int) -> BackupStatus:
        if not self._root.is_dir():
            return BackupStatus(False, None, None, [], None)
        entries = [
            BackupEntry(path.name, parse_stamp(path.name), _size(path))
            for path in sorted(self._root.iterdir(), reverse=True)
            if path.is_dir() and STAMP.match(path.name)
        ][:limit]
        return BackupStatus(
            True,
            _epoch_file(self._root / LAST_SUCCESS_FILE),
            self._requested(),
            entries,
            _epoch_file(self._root / HEARTBEAT_FILE),
            (self._root / HEARTBEAT_FILE).exists(),
        )

    def _requested(self) -> datetime | None:
        return _epoch_file(self._root / REQUEST_FILE)

    def _request(self, now: datetime) -> datetime:
        existing = self._requested()
        if existing is not None and now - existing <= REQUEST_UNANSWERED_AFTER:
            return existing
        tmp = self._root / f".{REQUEST_FILE}.tmp"
        tmp.write_text(str(int(now.timestamp())), encoding="utf-8")
        tmp.replace(self._root / REQUEST_FILE)
        return now


def parse_stamp(name: str) -> datetime:
    return datetime.strptime(name, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _epoch_file(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(path.read_text(encoding="utf-8").strip()), UTC)
    except (OSError, ValueError):
        return None


def daemon_alive(state: BackupStatus, now: datetime) -> bool:
    """Демон бэкапа жив: heartbeat свежее 2 минут (он обновляется раз в 30 с)."""
    beat = state.heartbeat_at
    return beat is not None and now - beat <= DAEMON_SILENT_AFTER


def facts(state: BackupStatus, now: datetime) -> BackupFacts:
    if state.source == "rustfs":
        # Демона на этом сервере нет: бэкап делает VPS 2, CRM видит только его результат в бакете.
        return BackupFacts(
            mounted=state.available,
            daemon_alive=True,
            last_success=state.last_success_at,
            requested_at=None,
            daemon_seen=True,
            source="rustfs",
            error=state.error,
            error_detail=state.error_detail,
            databases=state.databases,
        )
    return BackupFacts(
        mounted=state.available,
        daemon_alive=daemon_alive(state, now),
        last_success=state.last_success_at,
        requested_at=state.requested_at,
        daemon_seen=state.heartbeat_seen,
    )
