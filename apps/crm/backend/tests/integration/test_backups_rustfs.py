"""Статус бэкапов из бакета `backups` RustFS (M5-CRM-01, Q-M5-2) на реальном RustFS и Postgres.

Бакет наполняется так же, как это делает `infra/db/backup.sh` на VPS 2: `<штамп>/<база>.dump`
и `<штамп>/SHA256SUMS`. Проверяются API «Резервные копии», строка «backup» центра внешних
сервисов, инцидент «нет копии за сутки» с одним оповещением и закрытие, ошибки бакета.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiobotocore.session import get_session
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.integrations.s3 import ObjectStorage
from app.main import create_app
from app.services.external_services.wiring import build_checks
from tests.integration.test_external_services import URL, FakeAlerts, headers

pytestmark = pytest.mark.integration

DBS = ("crm", "erp", "litellm", "langfuse")


async def make_bucket(settings: Settings, name: str) -> None:
    async with get_session().create_client(
        "s3",
        endpoint_url=str(settings.s3_endpoint).rstrip("/"),
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
    ) as client:
        await client.create_bucket(Bucket=name)


async def upload_backup(storage: ObjectStorage, bucket: str, hours_ago: float) -> str:
    stamp = (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime("%Y%m%dT%H%M%SZ")
    for db in DBS:
        await storage.put(
            bucket, f"{stamp}/{db}.dump", b"PGDMP" + db.encode(), "application/octet-stream"
        )
    sums = "".join(f"{'a' * 64}  {db}.dump\n" for db in DBS)
    await storage.put(bucket, f"{stamp}/SHA256SUMS", sums.encode(), "text/plain")
    return stamp


@pytest.fixture
async def bucket(live_settings: Settings) -> str:
    name = f"backups-{uuid.uuid4().hex[:8]}"
    await make_bucket(live_settings, name)
    return name


@pytest.fixture
def alerts() -> FakeAlerts:
    return FakeAlerts()


def serve(settings: Settings, alerts: FakeAlerts) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        app.state.bot = None
        container = app.state.container
        checks = build_checks(container)
        checks._alerts = alerts  # type: ignore[assignment]
        container.__dict__["external_checks"] = checks
        yield test_client


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    bucket: str,
    alerts: FakeAlerts,
) -> Iterator[TestClient]:
    settings = live_settings.model_copy(
        update={"backup_source": "rustfs", "s3_bucket_backups": bucket}
    )
    yield from serve(settings, alerts)


def check(client: TestClient, auth: dict[str, str]) -> dict[str, Any]:
    response = client.post(f"{URL}/backup/check", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def test_api_lists_copies_from_the_bucket(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    live_settings: Settings,
    bucket: str,
) -> None:
    auth = await headers(sessions, client, "admin")
    empty = client.get("/api/v1/system/backups", headers=auth).json()
    assert (empty["source"], empty["available"], empty["error"]) == ("rustfs", True, None)
    assert empty["items"] == []
    assert empty["stale"]
    assert not empty["can_request"]

    stamp = await upload_backup(ObjectStorage(live_settings), bucket, 3)
    client.app.state.container.backup_service._cached = None  # type: ignore[attr-defined]
    body = client.get("/api/v1/system/backups", headers=auth).json()
    assert [i["name"] for i in body["items"]] == [stamp]
    assert not body["stale"]
    assert {d["name"] for d in body["databases"]} == set(DBS)
    assert body["daemon_alive"]
    # «Сделать сейчас» отсюда невозможно: бэкап запускают на VPS 2.
    assert client.post("/api/v1/system/backups", headers=auth).status_code == 409


async def test_no_copy_for_a_day_opens_one_incident_and_fresh_copy_closes_it(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    live_settings: Settings,
    bucket: str,
    alerts: FakeAlerts,
) -> None:
    auth = await headers(sessions, client, "admin")
    storage = ObjectStorage(live_settings)
    service = client.app.state.container.backup_service  # type: ignore[attr-defined]
    await upload_backup(storage, bucket, 30)

    failed = check(client, auth)
    assert failed["service"]["status"] == "fail"
    assert "за сутки" in failed["service"]["summary"]
    assert failed["service"]["hint"]
    assert failed["service"]["incident"]["ended_at"] is None
    metrics = failed["service"]["metrics"]
    assert metrics["backup_source"] == "rustfs"
    assert metrics["last_copy_at"]
    check(client, auth)  # повтор — тот же инцидент; «Сломано» меньше 15 минут — без оповещения
    assert alerts.sent == []

    await upload_backup(storage, bucket, 1)
    service._cached = None
    recovered = check(client, auth)
    assert recovered["service"]["status"] == "ok"
    assert recovered["service"]["incident"] is None
    assert alerts.sent == []  # о сбое не сообщали — «восстановлено» не нужно


async def test_missing_bucket_is_explained(
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    alerts: FakeAlerts,
) -> None:
    settings = live_settings.model_copy(
        update={"backup_source": "rustfs", "s3_bucket_backups": f"absent-{uuid.uuid4().hex[:8]}"}
    )
    for client in serve(settings, alerts):
        auth = await headers(sessions, client, "admin")
        body = client.get("/api/v1/system/backups", headers=auth).json()
        assert (body["available"], body["error"]) == (False, "bucket_missing")
        result = check(client, auth)["service"]
        assert result["status"] == "fail"
        assert "Бакет" in result["summary"]
        assert "backups" in result["hint"]


async def test_unreachable_storage_is_unknown_not_an_incident(
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    alerts: FakeAlerts,
) -> None:
    settings = live_settings.model_copy(
        update={"backup_source": "rustfs", "s3_endpoint": "http://127.0.0.1:1"}
    )
    for client in serve(settings, alerts):
        auth = await headers(sessions, client, "admin")
        body = client.get("/api/v1/system/backups", headers=auth).json()
        assert (body["available"], body["error"]) == (False, "unreachable")
        result = check(client, auth)["service"]
        assert result["status"] == "unknown"
        assert result["hint"]
        assert result["incident"] is None
        assert alerts.sent == []
