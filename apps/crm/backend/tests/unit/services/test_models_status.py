"""«Проверить» модель обновляет состояние монитора — один источник здоровья."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import SystemAlert
from app.services.models_status import record_probe

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


class FakeSession:
    def __init__(self) -> None:
        self.rows: dict[str, SystemAlert] = {}

    async def get(self, _model: Any, key: str) -> SystemAlert | None:
        return self.rows.get(key)

    def add(self, row: SystemAlert) -> None:
        self.rows[row.key] = row


async def test_failed_probe_opens_alert_and_success_resolves_it() -> None:
    fake = FakeSession()
    session = cast(AsyncSession, fake)
    await record_probe(session, "dialog-model", False, "402: no credits", NOW)
    row = fake.rows["model:dialog-model"]
    assert row.active
    assert row.detail == "402: no credits"
    assert row.first_seen_at == NOW
    later = NOW + timedelta(minutes=5)
    await record_probe(session, "dialog-model", True, None, later)
    assert not row.active
    assert row.resolved_at == later
    assert row.detail is None
    assert row.updated_at == later


async def test_successful_probe_creates_ok_row() -> None:
    fake = FakeSession()
    await record_probe(cast(AsyncSession, fake), "embed-model", True, None, NOW)
    row = fake.rows["model:embed-model"]
    assert not row.active
    assert row.updated_at == NOW
