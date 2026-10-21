"""Раскладка бэкапов в бакете `backups` RustFS (M5-CRM-01, Q-M5-2). Чистые функции.

Формат пишет `infra/db/backup.sh` (VPS 2, `rclone copy <каталог> rustfs:backups/<штамп>`):

    <UTC-штамп>/<база>.dump     pg_dump custom, по одному на базу (crm, erp, litellm, langfuse)
    <UTC-штамп>/SHA256SUMS      `<sha256>  <база>.dump` по каждому дампу, после проверки дампов

Отдельного файла статуса нет: «успешный бэкап» — каталог со SHA256SUMS и непустыми дампами.
Порядок выгрузки rclone не гарантирует, поэтому одного SHA256SUMS мало: дамп каждой базы
проверяется отдельно, а список ожидаемых баз берётся из SHA256SUMS самого свежего каталога.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

STAMP: Final = re.compile(r"^\d{8}T\d{6}Z$")
SUMS_NAME: Final = "SHA256SUMS"
DUMP_SUFFIX: Final = ".dump"
_SUM_LINE: Final = re.compile(r"^[0-9a-fA-F]{64}\s+\*?(?P<name>[^\s/]+)\.dump\s*$")


class ObjectLike(Protocol):
    @property
    def key(self) -> str: ...

    @property
    def size(self) -> int: ...


@dataclass(frozen=True, slots=True)
class BackupSet:
    """Один каталог `<штамп>/` бакета: когда сделан, какие базы в нём есть и сколько занимает."""

    name: str
    at: datetime
    databases: frozenset[str]
    size_bytes: int


def parse_stamp(name: str) -> datetime:
    return datetime.strptime(name, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def parse_sums(text: str) -> list[str]:
    """Имена баз из SHA256SUMS (`<sha256>  <база>.dump`); мусорные строки пропускаются."""
    names = (m.group("name") for line in text.splitlines() if (m := _SUM_LINE.match(line.strip())))
    return list(dict.fromkeys(names))


def backup_sets(objects: Iterable[ObjectLike]) -> list[BackupSet]:
    """Завершённые каталоги, свежие первыми: есть SHA256SUMS и хотя бы один непустой дамп."""
    sums: set[str] = set()
    dumps: dict[str, dict[str, int]] = {}
    sizes: dict[str, int] = {}
    for obj in objects:
        stamp, _, file = obj.key.partition("/")
        if not STAMP.match(stamp) or not file or "/" in file:
            continue
        sizes[stamp] = sizes.get(stamp, 0) + obj.size
        if file == SUMS_NAME:
            sums.add(stamp)
        elif file.endswith(DUMP_SUFFIX) and obj.size > 0:
            dumps.setdefault(stamp, {})[file.removesuffix(DUMP_SUFFIX)] = obj.size
    done = [
        BackupSet(s, parse_stamp(s), frozenset(dumps[s]), sizes[s]) for s in sums if dumps.get(s)
    ]
    return sorted(done, key=lambda b: b.name, reverse=True)


def last_per_database(
    sets: Sequence[BackupSet], expected: Iterable[str]
) -> dict[str, datetime | None]:
    """База → время самой свежей копии, где её дамп есть; нет нигде — None."""
    return {db: next((s.at for s in sets if db in s.databases), None) for db in expected}
