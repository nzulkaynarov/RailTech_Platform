"""Статус бэкапов из бакета `backups` RustFS (M5-CRM-01, Q-M5-2, runbook backup-restore.md).

На проде бэкап делает контейнер `backup` на VPS 2 и выгружает каждый прогон в бакет `backups`
(`infra/db/backup.sh`); тома `/backups` у CRM нет. CRM только читает бакет (S3 API, тот же клиент
`ObjectStorage`) и ничего не пишет. Формат — `domain/backup_objects.py`. «Сделать сейчас» отсюда
невозможно: бэкап запускают на VPS 2 (`infra/deploy/backup-now.sh`).
"""

import asyncio
import time
from dataclasses import replace
from datetime import datetime
from typing import Protocol

import structlog
from botocore.exceptions import ClientError

from app.domain import backup_objects as layout
from app.integrations.s3 import StoredObject
from app.services.backups import BackupEntry, BackupStatus

logger = structlog.get_logger(__name__)
READ_TIMEOUT_S = 10.0
CACHE_S = 30.0
# Ошибка чтения бакета тоже помнится недолго: недоступный S3 не держит каждый запрос по 10 с.
ERROR_CACHE_S = 10.0
_DENIED = frozenset(
    {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "AllAccessDisabled", "403"}
)


class BackupBucket(Protocol):
    async def list_objects(self, bucket: str, prefix: str = "") -> list[StoredObject]: ...

    async def get(self, bucket: str, key: str) -> bytes: ...


def classify(exc: BaseException) -> tuple[str, str]:
    """(код ошибки для правил, техдеталь без адресов и ключей)."""
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code == "NoSuchBucket":
            return "bucket_missing", code
        if code in _DENIED:
            return "access_denied", code
        return "unreachable", code or type(exc).__name__
    return "unreachable", type(exc).__name__


class RustfsBackupService:
    can_request = False

    def __init__(
        self,
        storage: BackupBucket,
        bucket: str = "backups",
        *,
        cache_s: float = CACHE_S,
        error_cache_s: float = ERROR_CACHE_S,
    ) -> None:
        self._storage = storage
        self._bucket = bucket
        self._cache_s = cache_s
        self._error_cache_s = error_cache_s
        self._cached: tuple[float, BackupStatus] | None = None

    async def request_now(self, now: datetime) -> datetime:
        raise NotImplementedError("backups are made on the database server (VPS 2)")

    async def status(self, limit: int = 30) -> BackupStatus:
        state = await self._state()
        return replace(state, items=state.items[:limit])

    async def _state(self) -> BackupStatus:
        cached = self._cached
        if cached is not None:
            ttl = self._cache_s if cached[1].error is None else self._error_cache_s
            if time.monotonic() - cached[0] < ttl:
                return cached[1]
        try:
            state = await asyncio.wait_for(self._read(), READ_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — любая ошибка чтения бакета = понятный код ошибки
            code, detail = classify(exc)
            logger.warning("backup_bucket_read_failed", bucket=self._bucket, error=detail)
            failed = BackupStatus(
                False, None, None, [], source="rustfs", error=code, error_detail=detail
            )
            self._cached = (time.monotonic(), failed)
            return failed
        self._cached = (time.monotonic(), state)
        return state

    async def _read(self) -> BackupStatus:
        sets = layout.backup_sets(await self._storage.list_objects(self._bucket))
        expected = await self._expected(sets[0]) if sets else []
        databases = layout.last_per_database(sets, expected)
        dates = list(databases.values())
        # Последний успех — копия самой «отстающей» базы: все базы имеют копию не старее этого.
        last = None if not dates or None in dates else min(d for d in dates if d is not None)
        items = [BackupEntry(s.name, s.at, s.size_bytes) for s in sets]
        return BackupStatus(True, last, None, items, source="rustfs", databases=databases)

    async def _expected(self, newest: layout.BackupSet) -> list[str]:
        """Базы из SHA256SUMS свежего каталога; не прочитался — то, что реально легло в каталог."""
        try:
            raw = await self._storage.get(self._bucket, f"{newest.name}/{layout.SUMS_NAME}")
            names = layout.parse_sums(raw.decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001 — SHA256SUMS нужен только для полноты списка баз
            logger.info("backup_sums_unreadable", error=type(exc).__name__)
            names = []
        return names or sorted(newest.databases)
