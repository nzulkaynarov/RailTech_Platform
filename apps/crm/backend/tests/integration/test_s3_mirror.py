"""Бэкап бакетов (ADR-0013): выгрузка в каталог и восстановление в пустой бакет."""

import uuid
from pathlib import Path

import pytest
from aiobotocore.session import get_session

from app.cli.s3_mirror import export, restore
from app.config import Settings
from app.integrations.s3 import ObjectStorage

pytestmark = pytest.mark.integration


async def make_bucket(settings: Settings, name: str) -> None:
    async with get_session().create_client(
        "s3",
        endpoint_url=str(settings.s3_endpoint).rstrip("/"),
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
    ) as client:
        await client.create_bucket(Bucket=name)


async def test_export_and_restore_roundtrip(live_settings: Settings, tmp_path: Path) -> None:
    if not live_settings.s3_access_key.get_secret_value():
        pytest.fail("S3_ACCESS_KEY/S3_SECRET_KEY не заданы для integration")
    source, target = f"src-{uuid.uuid4().hex[:8]}", f"dst-{uuid.uuid4().hex[:8]}"
    await make_bucket(live_settings, source)
    await make_bucket(live_settings, target)
    storage = ObjectStorage(live_settings)
    await storage.put(source, "kb/1/doc.md", "# Документ".encode(), "text/markdown")
    await storage.put(source, "top.pdf", b"%PDF", "application/pdf")

    assert await export(storage, tmp_path, [source]) == 2
    assert (tmp_path / source / "kb" / "1" / "doc.md").read_text("utf-8") == "# Документ"

    (tmp_path / source).rename(tmp_path / target)
    assert await restore(storage, tmp_path, [target]) == 2
    assert sorted(await storage.list_keys(target)) == ["kb/1/doc.md", "top.pdf"]
    assert await storage.get(target, "top.pdf") == b"%PDF"
