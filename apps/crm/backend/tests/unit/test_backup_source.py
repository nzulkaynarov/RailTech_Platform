"""Выбор источника статуса бэкапов (M5-CRM-01): том (dev) или бакет RustFS (прод)."""

from pathlib import Path

import pytest

from app.config import Settings
from app.container import Container
from app.services.backups import BackupService
from app.services.backups_rustfs import RustfsBackupService


def make(**kw: object) -> Settings:
    kw.setdefault("app_env", "test")
    return Settings(_env_file=None, s3_endpoint="http://s3.invalid:9000", **kw)  # type: ignore[arg-type]


def test_auto_takes_the_volume_when_it_is_mounted(tmp_path: Path) -> None:
    assert make(backup_dir=tmp_path).backup_source_resolved == "volume"


def test_auto_without_volume_outside_prod_keeps_the_old_not_mounted_behaviour(
    tmp_path: Path,
) -> None:
    """dev/test: нет тома — «не подключён» (unknown), а не попытка читать RustFS."""
    assert make(backup_dir=tmp_path / "absent").backup_source_resolved == "volume"


def test_auto_without_volume_in_prod_reads_the_bucket(tmp_path: Path) -> None:
    prod = make(backup_dir=tmp_path / "absent", app_env="prod", platform_sso_secret="k")
    assert prod.backup_source_resolved == "rustfs"


@pytest.mark.parametrize("source", ["volume", "rustfs"])
def test_explicit_source_wins_over_the_volume(tmp_path: Path, source: str) -> None:
    assert make(backup_dir=tmp_path, backup_source=source).backup_source_resolved == source


def test_container_builds_the_matching_reader(tmp_path: Path) -> None:
    volume = Container(make(backup_dir=tmp_path)).backup_service
    bucket = Container(make(backup_dir=tmp_path, backup_source="rustfs")).backup_service
    assert isinstance(volume, BackupService)
    assert volume.can_request
    assert isinstance(bucket, RustfsBackupService)
    assert not bucket.can_request


async def test_dev_without_volume_is_unknown_not_a_failure(tmp_path: Path) -> None:
    """Без тома вне прода сервис отвечает как раньше: «не подключён» → unknown, без инцидента."""
    from datetime import UTC, datetime

    from app.domain import system_status as rules
    from app.services import backups as backup_rules

    service = Container(make(backup_dir=tmp_path / "absent")).backup_service
    now = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    state = await service.status()
    assert not state.available
    assert rules.backup(now, backup_rules.facts(state, now)).status == "unknown"
