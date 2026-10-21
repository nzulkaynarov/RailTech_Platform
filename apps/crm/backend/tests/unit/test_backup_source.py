"""Выбор источника статуса бэкапов (M5-CRM-01): том (dev) или бакет RustFS (прод)."""

from pathlib import Path

import pytest

from app.config import Settings
from app.container import Container
from app.services.backups import BackupService
from app.services.backups_rustfs import RustfsBackupService


def make(**kw: object) -> Settings:
    return Settings(_env_file=None, app_env="test", s3_endpoint="http://s3.invalid:9000", **kw)  # type: ignore[arg-type]


def test_auto_takes_the_volume_when_it_is_mounted(tmp_path: Path) -> None:
    assert make(backup_dir=tmp_path).backup_source_resolved == "volume"


def test_auto_takes_the_bucket_when_there_is_no_volume(tmp_path: Path) -> None:
    assert make(backup_dir=tmp_path / "absent").backup_source_resolved == "rustfs"


@pytest.mark.parametrize("source", ["volume", "rustfs"])
def test_explicit_source_wins_over_the_volume(tmp_path: Path, source: str) -> None:
    assert make(backup_dir=tmp_path, backup_source=source).backup_source_resolved == source


def test_container_builds_the_matching_reader(tmp_path: Path) -> None:
    volume = Container(make(backup_dir=tmp_path)).backup_service
    bucket = Container(make(backup_dir=tmp_path / "absent")).backup_service
    assert isinstance(volume, BackupService)
    assert volume.can_request
    assert isinstance(bucket, RustfsBackupService)
    assert not bucket.can_request
