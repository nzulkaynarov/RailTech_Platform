"""Чтение каталога архива WAL: инкрементально и без чтения содержимого (W15-H8b, B-004)."""

from datetime import UTC, datetime, timedelta

from app.integrations.s3 import StoredObject
from app.services.external_services import wal

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
BUCKET, PREFIX = "wal", "pg17"


def seg(n: int, at: datetime) -> StoredObject:
    return StoredObject(f"pg17/wal_005/{n:024X}.zst.enc", 16, at)


def sentinel(name: str, at: datetime) -> StoredObject:
    return StoredObject(f"pg17/basebackups_005/{name}_backup_stop_sentinel.json", 2, at)


class Storage:
    def __init__(self, objects: list[StoredObject]) -> None:
        self.objects = objects
        self.calls: list[tuple[str, str, str]] = []
        self.error: Exception | None = None

    async def list_objects(
        self, bucket: str, prefix: str = "", start_after: str = ""
    ) -> list[StoredObject]:
        self.calls.append((bucket, prefix, start_after))
        if self.error is not None:
            raise self.error
        return sorted(
            (o for o in self.objects if o.key.startswith(prefix) and o.key > start_after),
            key=lambda o: o.key,
        )


async def test_first_pass_reads_everything_and_remembers_where_it_stopped() -> None:
    storage = Storage(
        [
            seg(1, NOW - timedelta(minutes=3)),
            seg(2, NOW - timedelta(minutes=2)),
            StoredObject("pg17/wal_005/00000002.history.zst", 1, NOW),  # не сегмент
            sentinel("base_0001", NOW - timedelta(hours=9)),
            StoredObject("pg17/basebackups_005/base_0001/tar_partitions/part_1.tar", 9, NOW),
        ]
    )
    facts, carry = await wal.read(storage, BUCKET, PREFIX, {}, refresh_base=False)
    assert facts.error is None
    assert facts.last_segment_at == NOW - timedelta(minutes=2)
    assert facts.last_basebackup_at == NOW - timedelta(hours=9)
    assert carry[wal.KEY_METRIC] == f"pg17/wal_005/{2:024X}.zst.enc"
    assert storage.calls[0] == (BUCKET, "pg17/wal_005/", "")


async def test_next_pass_asks_only_for_newer_keys_and_keeps_the_old_state_when_nothing_new() -> (
    None
):
    storage = Storage(
        [seg(1, NOW - timedelta(minutes=3)), sentinel("base_1", NOW - timedelta(hours=9))]
    )
    _, carry = await wal.read(storage, BUCKET, PREFIX, {}, refresh_base=True)
    storage.calls.clear()

    facts, again = await wal.read(storage, BUCKET, PREFIX, carry, refresh_base=False)
    assert storage.calls == [
        (BUCKET, "pg17/wal_005/", carry[wal.KEY_METRIC])
    ]  # базу не перечитывали
    assert facts.last_segment_at == NOW - timedelta(minutes=3)  # нового нет — прежнее время
    assert again == carry

    storage.objects.append(seg(2, NOW))
    fresh, newer = await wal.read(storage, BUCKET, PREFIX, carry, refresh_base=False)
    assert fresh.last_segment_at == NOW
    assert newer[wal.KEY_METRIC] == f"pg17/wal_005/{2:024X}.zst.enc"


async def test_base_backups_are_reread_when_asked() -> None:
    storage = Storage([seg(1, NOW), sentinel("base_1", NOW - timedelta(hours=30))])
    _, carry = await wal.read(storage, BUCKET, PREFIX, {}, refresh_base=False)
    storage.objects.append(sentinel("base_2", NOW - timedelta(hours=1)))
    stale, _ = await wal.read(storage, BUCKET, PREFIX, carry, refresh_base=False)
    assert stale.last_basebackup_at == NOW - timedelta(hours=30)
    fresh, _ = await wal.read(storage, BUCKET, PREFIX, carry, refresh_base=True)
    assert fresh.last_basebackup_at == NOW - timedelta(hours=1)


async def test_unreadable_bucket_is_an_error_not_a_crash() -> None:
    storage = Storage([])
    storage.error = PermissionError("AccessDenied")
    facts, carry = await wal.read(storage, BUCKET, PREFIX, {}, refresh_base=True)
    assert facts.error == "PermissionError"
    assert carry == {}
