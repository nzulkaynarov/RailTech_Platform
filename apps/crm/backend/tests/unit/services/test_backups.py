"""Статус бэкапов из тома и флаг «сделать сейчас»; чек-лист настройки."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.domain.system_status import Component
from app.services.backups import HEARTBEAT_FILE, REQUEST_FILE, BackupService, daemon_alive, facts
from app.services.setup_checklist import LINKS, SetupFacts, checklist, health_facts

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
    later = await service.request_now(NOW + timedelta(minutes=1))
    assert first == later == NOW
    assert (tmp_path / REQUEST_FILE).read_text() == str(int(NOW.timestamp()))
    assert (await service.status()).requested_at == NOW
    retry = NOW + timedelta(minutes=5)
    assert await service.request_now(retry) == retry


async def test_heartbeat_tells_daemon_alive(tmp_path: Path) -> None:
    service = BackupService(tmp_path)
    assert not daemon_alive(await service.status(), NOW)
    (tmp_path / HEARTBEAT_FILE).write_text(str(int(NOW.timestamp()) - 60))
    assert daemon_alive(await service.status(), NOW)
    (tmp_path / HEARTBEAT_FILE).write_text(str(int(NOW.timestamp()) - 300))
    assert not daemon_alive(await service.status(), NOW)


async def test_heartbeat_never_existed_is_not_seen(tmp_path: Path) -> None:
    """Нет файла heartbeat — демон не развёрнут (warn); был и устарел — fail."""
    service = BackupService(tmp_path)
    assert facts(await service.status(), NOW).daemon_seen is False
    (tmp_path / HEARTBEAT_FILE).write_text(str(int(NOW.timestamp()) - 3600))
    stale = facts(await service.status(), NOW)
    assert stale.daemon_seen is True
    assert stale.daemon_alive is False


ALL_DONE = SetupFacts(
    company_saved=True,
    business_hours_saved=True,
    models_ok=True,
    bot_running=True,
    channel_set=True,
    kb_indexed=True,
    teammate_with_telegram=True,
    lead_message_exists=True,
    erp_connected=True,
    mail_configured=True,
    colleague_exists=True,
)


def test_checklist_all_done_and_links() -> None:
    items = checklist(ALL_DONE)
    assert all(done for _, done in items)
    assert [k for k, _ in items] == list(LINKS)


def test_models_and_bot_flags() -> None:
    assert dict(checklist(replace(ALL_DONE, models_ok=False)))["models"] is False
    assert dict(checklist(replace(ALL_DONE, bot_running=False)))["bot"] is False


def _c(key: str, status: str) -> Component:
    return Component(key, key, status, "", NOW)  # type: ignore[arg-type]


def test_models_are_not_ready_until_the_monitor_checked_them() -> None:
    """O-4: «Готово» без единой проверки — ложь; шаг «Не проверено»."""
    from app.services.setup_checklist import models_checked, unchecked_keys

    never = [_c("litellm", "ok"), _c("models", "unknown"), _c("bot", "ok")]
    assert health_facts(never)[0] is False
    assert models_checked(never) is False
    assert unchecked_keys(replace(ALL_DONE, models_ok=False, models_checked=False)) == {"models"}
    checked = [_c("litellm", "ok"), _c("model:dialog-model", "ok")]
    assert models_checked(checked) is True
    assert unchecked_keys(ALL_DONE) == frozenset()


@pytest.mark.parametrize(
    ("components", "expected"),
    [
        ([_c("litellm", "ok"), _c("model:dialog-model", "ok"), _c("bot", "ok")], (True, True)),
        ([_c("litellm", "ok"), _c("models", "unknown"), _c("bot", "fail")], (False, False)),
        ([_c("litellm", "fail"), _c("model:dialog-model", "ok")], (False, False)),
        ([_c("litellm", "ok"), _c("model:a", "ok"), _c("model:b", "fail")], (False, False)),
    ],
    ids=["healthy", "monitor-not-yet", "gateway-down", "one-model-down"],
)
def test_health_facts_follow_system_status(
    components: list[Component], expected: tuple[bool, bool]
) -> None:
    assert health_facts(components) == expected
