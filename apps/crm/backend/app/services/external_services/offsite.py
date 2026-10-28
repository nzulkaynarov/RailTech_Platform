"""Чтение отметки внешней копии бэкапов для строки «Внешняя копия бэкапов» (OPS-GDRIVE).

Сервис `offsite-backup` (VPS 1) пишет итог каждой попытки копирования в `status.json` бакета
`offsite`; ключ CRM читает этот бакет и только его из всего, что связано с копией (ни архива WAL, ни
Google Drive). Сначала — список (нет файла — «ещё не отметился», это не ошибка), затем сам файл
(сотни байт). Дешёвый проход раз в минуту: два запроса к RustFS внутри сети.
"""

from typing import Protocol

import structlog

from app.domain.external_offsite import STATUS_KEY, OffsiteFacts, parse
from app.integrations.s3 import StoredObject

logger = structlog.get_logger(__name__)


class Reader(Protocol):
    async def list_objects(
        self, bucket: str, prefix: str = "", start_after: str = ""
    ) -> list[StoredObject]: ...

    async def get(self, bucket: str, key: str) -> bytes: ...


async def read(storage: Reader, bucket: str) -> OffsiteFacts:
    try:
        found = await storage.list_objects(bucket, STATUS_KEY)
        if not any(o.key == STATUS_KEY for o in found):
            return OffsiteFacts(missing=True)
        raw = await storage.get(bucket, STATUS_KEY)
    except Exception as exc:  # noqa: BLE001 — нет бакета или права: «не проверено», не авария
        logger.info("offsite_status_unreadable", error=type(exc).__name__)
        return OffsiteFacts(error=type(exc).__name__)
    return parse(raw)
