"""Архив WAL и Redis в центре внешних сервисов (W15-H8b, B-004): правила статусов без сети."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.external_infra import (
    REDIS_BROKER,
    REDIS_CACHE,
    RedisFacts,
    WalFacts,
    is_segment,
    is_sentinel,
    parse_info,
    redis,
    wal_archive,
)
from app.domain.system_status import HOSTING_WHO

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def ago(**delta: float) -> datetime:
    return NOW - timedelta(**delta)


@pytest.mark.parametrize(
    ("key", "segment"),
    [
        ("pg17/wal_005/000000010000000000000042.zst.enc", True),
        ("pg17/wal_005/000000010000000000000042.00000028.backup.zst", True),
        ("pg17/wal_005/00000002.history.zst", False),
        ("pg17/basebackups_005/base_000000010000000000000040_backup_stop_sentinel.json", False),
        ("pg17/wal_005/readme.txt", False),
    ],
)
def test_segment_names(key: str, segment: bool) -> None:
    assert is_segment(key) is segment


def test_sentinel_names() -> None:
    assert is_sentinel("pg17/basebackups_005/base_0000_backup_stop_sentinel.json")
    assert not is_sentinel("pg17/basebackups_005/base_0000/tar_partitions/part_001.tar.zst")


@pytest.mark.parametrize(
    ("segment_min", "base_h", "status"),
    [
        (1, 5, "ok"),
        (10, 25, "ok"),
        (11, 5, "warn"),  # архив отстаёт
        (29, 5, "warn"),
        (31, 5, "fail"),  # архив стоит
        (1, 27, "warn"),  # копия не делалась больше 26 ч
        (1, 51, "fail"),  # копии нет двое суток
        (11, 51, "fail"),  # худшее из двух
    ],
)
def test_wal_thresholds(segment_min: int, base_h: int, status: str) -> None:
    facts = WalFacts(None, ago(minutes=segment_min), ago(hours=base_h))
    result = wal_archive(facts, NOW)
    assert result.status == status
    assert result.metrics["last_segment_min"] == segment_min
    if status == "ok":
        assert result.cause is None
    else:
        assert result.cause == "server_down"
        assert HOSTING_WHO in (result.hint or "")  # «кто исправляет: хостинг»


def test_wal_stopped_names_the_emergency_switch_honestly() -> None:
    result = wal_archive(WalFacts(None, ago(hours=3), ago(hours=5)), NOW)
    assert result.status == "fail"
    assert "180 мин" in result.summary
    assert result.hint is not None
    assert "rt-archive-off" in result.hint  # выключатель CRM не видит, но называет, где смотреть
    assert "не видит" in result.hint


def test_wal_without_segments_or_base_backups() -> None:
    nothing = wal_archive(WalFacts(None, None, None), NOW)
    assert nothing.status == "fail"
    assert "нет ни одного сегмента" in nothing.summary
    no_base = wal_archive(WalFacts(None, ago(minutes=1), None), NOW)
    assert no_base.status == "fail"
    assert "базовых копий архива нет" in no_base.summary


def test_wal_unreadable_is_not_checked_and_says_who_fixes_it() -> None:
    result = wal_archive(WalFacts(error="AccessDenied"), NOW)
    assert result.status == "unknown"  # «не проверено», а не «сломано»
    assert result.error == "AccessDenied"
    assert HOSTING_WHO in (result.hint or "")
    assert "rt-pitr status" in (result.hint or "")


INFO_OK = "# Memory\r\nused_memory:52428800\r\nmaxmemory:134217728\r\n# Persistence\r\n" + (
    "rdb_last_save_time:{save}\r\nrdb_last_bgsave_status:ok\r\naof_last_write_status:ok\r\n"
)


def info(save: datetime | None = None, **over: str) -> dict[str, str]:
    base = parse_info(INFO_OK.format(save=int((save or ago(minutes=2)).timestamp())))
    return {**base, **over}


def test_parse_info_skips_sections() -> None:
    parsed = parse_info("# Memory\r\nused_memory:10\r\n\r\nrole:master\r\n")
    assert parsed == {"used_memory": "10", "role": "master"}


@pytest.mark.parametrize("key", [REDIS_BROKER, REDIS_CACHE])
def test_redis_ok_reports_memory(key: str) -> None:
    result = redis(RedisFacts(key, latency_ms=3, info=info()), NOW)
    assert result.status == "ok"
    assert result.metrics["memory_pct"] == 39
    assert result.metrics["used_memory_mb"] == 50.0
    assert result.metrics["rdb_last_save_age_s"] == 120


@pytest.mark.parametrize("key", [REDIS_BROKER, REDIS_CACHE])
def test_redis_down_is_a_hosting_failure_with_the_impact(key: str) -> None:
    result = redis(RedisFacts(key, error="ConnectionRefusedError"), NOW)
    assert result.status == "fail"
    assert result.cause == "server_down"
    assert HOSTING_WHO in (result.hint or "")
    assert result.error == "ConnectionRefusedError"
    assert ("Celery" in result.summary) is (key == REDIS_BROKER)
    assert ("сессии Платформы" in result.summary) is (key == REDIS_CACHE)


def test_redis_not_configured_is_not_checked() -> None:
    result = redis(RedisFacts(REDIS_BROKER, configured=False), NOW)
    assert result.status == "unknown"
    assert "REDIS_BROKER_URL" in (result.hint or "")


@pytest.mark.parametrize(
    ("key", "used", "status"),
    [
        (REDIS_BROKER, 100_000_000, "ok"),  # 75 %
        (REDIS_BROKER, 110_000_000, "warn"),  # 82 %
        (REDIS_BROKER, 130_000_000, "fail"),  # 97 %: noeviction, запись встанет
        (REDIS_CACHE, 130_000_000, "warn"),  # кэш вытесняет сам — не авария
    ],
)
def test_redis_memory(key: str, used: int, status: str) -> None:
    result = redis(RedisFacts(key, info=info(used_memory=str(used))), NOW)
    assert result.status == status


def test_redis_persistence_problems() -> None:
    aof = redis(RedisFacts(REDIS_BROKER, info=info(aof_last_write_status="err")), NOW)
    assert aof.status == "fail"
    assert "AOF" in aof.summary
    rdb = redis(RedisFacts(REDIS_CACHE, info=info(rdb_last_bgsave_status="err")), NOW)
    assert rdb.status == "warn"
    stale = redis(RedisFacts(REDIS_CACHE, info=info(save=ago(hours=2))), NOW)
    assert stale.status == "warn"
    assert "RDB" in stale.summary
    # Брокеру снимок RDB не нужен (AOF), возраст снимка его не тревожит.
    assert redis(RedisFacts(REDIS_BROKER, info=info(save=ago(hours=5))), NOW).status == "ok"
