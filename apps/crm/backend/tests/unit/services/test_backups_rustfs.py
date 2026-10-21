"""Статус бэкапов из бакета `backups` RustFS (M5-CRM-01, Q-M5-2): свежий, старый, пусто, сбой."""

from datetime import UTC, datetime, timedelta

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.domain import system_status as rules
from app.domain.backup_objects import parse_sums
from app.integrations.s3 import StoredObject
from app.services import backups as backup_rules
from app.services.backups_rustfs import RustfsBackupService

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
DBS = ("crm", "erp", "litellm", "langfuse")


def stamp(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y%m%dT%H%M%SZ")


class FakeBucket:
    """Бакет `backups`, как его наполняет `infra/db/backup.sh`: `<штамп>/<база>.dump`."""

    def __init__(self, error: Exception | None = None) -> None:
        self.objects: dict[str, bytes] = {}
        self.error = error
        self.listed = 0

    def add(self, hours_ago: float, dbs: tuple[str, ...] = DBS, *, sums: bool = True) -> str:
        name = stamp(hours_ago)
        for db in dbs:
            self.objects[f"{name}/{db}.dump"] = b"x" * 100
        if sums:
            body = "".join(f"{'a' * 64}  {db}.dump\n" for db in DBS)
            self.objects[f"{name}/SHA256SUMS"] = body.encode()
        return name

    async def list_objects(self, bucket: str, prefix: str = "") -> list[StoredObject]:
        self.listed += 1
        if self.error:
            raise self.error
        assert bucket == "backups"
        return [StoredObject(k, len(v), NOW) for k, v in sorted(self.objects.items())]

    async def get(self, bucket: str, key: str) -> bytes:
        return self.objects[key]


def service(bucket: FakeBucket) -> RustfsBackupService:
    return RustfsBackupService(bucket, "backups", cache_s=0)


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "ListObjectsV2")


async def test_fresh_backup_reports_time_and_every_database() -> None:
    bucket = FakeBucket()
    newest = bucket.add(3)
    bucket.add(27)
    state = await service(bucket).status()
    assert state.source == "rustfs"
    assert state.available
    assert state.error is None
    assert state.last_success_at == datetime.strptime(newest, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    assert set(state.databases) == set(DBS)
    assert [i.name for i in state.items] == [newest, stamp(27)]
    assert state.items[0].size_bytes == 400 + len(bucket.objects[f"{newest}/SHA256SUMS"])
    component = rules.backup(NOW, backup_rules.facts(state, NOW))
    assert component.status == "ok"


async def test_older_than_a_day_is_a_failure_that_opens_an_incident() -> None:
    bucket = FakeBucket()
    bucket.add(30)
    state = await service(bucket).status()
    component = rules.backup(NOW, backup_rules.facts(state, NOW))
    assert component.status == "fail"  # `fail` открывает инцидент в центре внешних сервисов
    assert "за сутки" in component.reason
    assert "30" in component.reason


async def test_upload_in_progress_keeps_previous_copy_as_the_last_success() -> None:
    bucket = FakeBucket()
    bucket.add(2, dbs=("crm", "erp"))  # выгрузка идёт: litellm и langfuse ещё не легли
    previous = bucket.add(25)
    state = await service(bucket).status()
    assert (
        state.databases["crm"]
        == state.databases["erp"]
        == datetime.strptime(stamp(2), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    )
    assert state.last_success_at == datetime.strptime(previous, "%Y%m%dT%H%M%SZ").replace(
        tzinfo=UTC
    )
    assert rules.backup(NOW, backup_rules.facts(state, NOW)).status == "ok"  # 25 ч < 26 ч


async def test_missing_database_dump_is_named_in_the_reason() -> None:
    bucket = FakeBucket()
    bucket.add(3, dbs=("crm", "erp", "litellm"))  # langfuse так и не выгружена, старых копий нет
    state = await service(bucket).status()
    assert state.databases["langfuse"] is None
    assert state.last_success_at is None
    component = rules.backup(NOW, backup_rules.facts(state, NOW))
    assert component.status == "fail"
    assert "langfuse" in component.reason


async def test_empty_bucket_has_no_success() -> None:
    state = await service(FakeBucket()).status()
    assert state.available
    assert state.error is None
    assert state.last_success_at is None
    assert state.items == []
    component = rules.backup(NOW, backup_rules.facts(state, NOW))
    assert component.status == "fail"
    assert "нет ни одной" in component.reason


async def test_files_without_sums_or_empty_dumps_do_not_count() -> None:
    bucket = FakeBucket()
    bucket.add(1, sums=False)  # SHA256SUMS нет — выгрузка не завершена
    empty = bucket.add(2, dbs=())
    bucket.objects[f"{empty}/crm.dump"] = b""
    bucket.objects["junk/readme.txt"] = b"x"
    state = await service(bucket).status()
    assert state.items == []
    assert state.last_success_at is None


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (client_error("NoSuchBucket"), "bucket_missing"),
        (client_error("AccessDenied"), "access_denied"),
        (client_error("InvalidAccessKeyId"), "access_denied"),
        (EndpointConnectionError(endpoint_url="http://rustfs:9000"), "unreachable"),
        (TimeoutError(), "unreachable"),
    ],
)
async def test_unreachable_bucket_gives_an_actionable_error(error: Exception, code: str) -> None:
    state = await service(FakeBucket(error)).status()
    assert not state.available
    assert state.error == code
    component = rules.backup(NOW, backup_rules.facts(state, NOW))
    assert component.status == ("unknown" if code == "unreachable" else "fail")
    assert rules.backup_hint(backup_rules.facts(state, NOW))  # «что сделать» есть всегда
    assert "http" not in component.reason  # адреса и ключи в текст не попадают


async def test_request_now_is_not_available_for_rustfs() -> None:
    assert not RustfsBackupService.can_request
    with pytest.raises(NotImplementedError):
        await service(FakeBucket()).request_now(NOW)


async def test_status_is_cached_between_polls() -> None:
    bucket = FakeBucket()
    bucket.add(3)
    cached = RustfsBackupService(bucket, "backups", cache_s=30)
    await cached.status()
    await cached.status()
    assert bucket.listed == 1


def test_parse_sums_reads_names_and_ignores_garbage() -> None:
    body = f"{'a' * 64}  crm.dump\n{'b' * 64} *erp.dump\nnot a sum line\n\n"
    assert parse_sums(body) == ["crm", "erp"]
