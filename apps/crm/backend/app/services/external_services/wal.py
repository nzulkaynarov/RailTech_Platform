"""Чтение каталога архива WAL для строки «Архив WAL» (W15-H8b, B-004).

CRM читает только список объектов бакета `wal` (ключ сервиса `crm` — чтение): имена и время
последней записи, содержимое зашифровано и не нужно. Сегменты в `wal_005/` названы возрастающими
номерами, поэтому следующая проверка просит у хранилища лишь ключи позже уже виденного
(`StartAfter`): в минуту — один дешёвый запрос, а не листинг двух десятков тысяч объектов. Первая
проверка читает всё. Базовые копии (`basebackups_005/*_backup_stop_sentinel.json`) перечитываются
раз в 15 минут.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

import structlog

from app.domain.external_infra import WalFacts, is_segment, is_sentinel
from app.domain.external_status import Metric
from app.integrations.s3 import StoredObject

logger = structlog.get_logger(__name__)
KEY_METRIC = "_wal_key"
SEGMENT_AT_METRIC = "_wal_at"
BASE_AT_METRIC = "_wal_base_at"


class Lister(Protocol):
    async def list_objects(
        self, bucket: str, prefix: str = "", start_after: str = ""
    ) -> list[StoredObject]: ...


def _when(raw: Metric) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _newest(objects: list[StoredObject]) -> StoredObject | None:
    return max(objects, key=lambda o: o.key, default=None)


async def read(
    storage: Lister,
    bucket: str,
    prefix: str,
    previous: Mapping[str, Metric],
    *,
    refresh_base: bool,
) -> tuple[WalFacts, dict[str, Metric]]:
    """Факты об архиве и то, что надо запомнить до следующей проверки (служебные метрики)."""
    root = prefix.strip("/")
    last_key = previous.get(KEY_METRIC)
    last_key = last_key if isinstance(last_key, str) else ""
    last_at = _when(previous.get(SEGMENT_AT_METRIC))
    base_at = _when(previous.get(BASE_AT_METRIC))
    try:
        fresh = [
            o
            for o in await storage.list_objects(bucket, f"{root}/wal_005/", last_key)
            if is_segment(o.key)
        ]
        newest = _newest(fresh)
        if newest is not None:
            last_key = newest.key
            last_at = newest.modified or last_at
        if refresh_base or base_at is None:
            sentinels = [
                o
                for o in await storage.list_objects(bucket, f"{root}/basebackups_005/")
                if is_sentinel(o.key) and o.modified is not None
            ]
            base_at = max((o.modified for o in sentinels if o.modified), default=None)
    except Exception as exc:  # noqa: BLE001 — нет бакета или права: «не проверено», не авария
        logger.info("wal_archive_unreadable", error=type(exc).__name__)
        return WalFacts(error=type(exc).__name__), {}
    carry: dict[str, Metric] = {
        KEY_METRIC: last_key or None,
        SEGMENT_AT_METRIC: last_at.isoformat() if last_at else None,
        BASE_AT_METRIC: base_at.isoformat() if base_at else None,
    }
    return WalFacts(None, last_at, base_at), carry
