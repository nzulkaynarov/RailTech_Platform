"""Статус бэкапов из тома и флаг «сделать сейчас»; чек-лист настройки."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.services.backups import REQUEST_FILE, BackupService
from app.services.setup_checklist import LINKS, SetupFacts, checklist

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


async def test_missing_volume_is_unavailable(tmp_path: Path) -> None:
    status = await BackupService(tmp_path / "absent").status()
    assert not status.available
    assert status.items == []


async def test_lists_finished_backups_newest_first(tmp_path: Path) -> None:
    for name in ("20261010T220000Z", "20261011T220000Z", "20261012T220000Z.partial", "junk"):
        (tmp_path / name).mkdir()
    (tmp_path / "20261011T220000Z" / "db.dump").write_bytes(b"x" * 10)
    (tmp_path / "20261011T220000Z" / "s3").mkdir()
    (tmp_path / "20261011T220000Z" / "s3" / "obj").write_bytes(b"y" * 5)
    (tmp_path / "last_success").write_text("1791237600\n")
    status = await BackupService(tmp_path).status()
    assert [i.name for i in status.items] == ["20261011T220000Z", "20261010T220000Z"]
    assert status.items[0].size_bytes == 15
    assert status.items[0].at == datetime(2026, 10, 11, 22, 0, tzinfo=UTC)
    assert status.last_success_at == datetime.fromtimestamp(1791237600, UTC)
    assert status.requested_at is None


async def test_request_now_is_idempotent(tmp_path: Path) -> None:
    service = BackupService(tmp_path)
    first = await service.request_now(NOW)
    later = await service.request_now(NOW.replace(hour=10))
    assert first == later == NOW
    assert (tmp_path / REQUEST_FILE).read_text() == str(int(NOW.timestamp()))
    assert (await service.status()).requested_at == NOW


ALL_DONE = SetupFacts(
    company_saved=True,
    business_hours_saved=True,
    litellm_ok=True,
    model_alerts=0,
    bot_configured=True,
    channel_set=True,
    kb_indexed=True,
    teammate_with_telegram=True,
    lead_message_exists=True,
)


def test_checklist_all_done_and_links() -> None:
    items = checklist(ALL_DONE)
    assert all(done for _, done in items)
    assert [k for k, _ in items] == list(LINKS)


def test_models_need_gateway_and_no_alerts() -> None:
    assert dict(checklist(replace(ALL_DONE, litellm_ok=False)))["models"] is False
    assert dict(checklist(replace(ALL_DONE, model_alerts=1)))["models"] is False
