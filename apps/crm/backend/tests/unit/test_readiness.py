import asyncio

import pytest

from app.services.readiness import Probe, ReadinessService


async def ok() -> None:
    return None


async def boom() -> None:
    raise ConnectionError("down")


async def hang() -> None:
    await asyncio.sleep(10)


@pytest.mark.parametrize(
    ("probes", "expected_checks", "expected_ok"),
    [
        ({"database": ok, "minio": ok}, {"database": True, "minio": True}, True),
        ({"database": ok, "minio": boom}, {"database": True, "minio": False}, False),
        ({"database": hang, "minio": ok}, {"database": False, "minio": True}, False),
        ({}, {}, True),
    ],
    ids=["all-ok", "one-fails", "one-times-out", "no-probes"],
)
async def test_check(
    probes: dict[str, Probe], expected_checks: dict[str, bool], expected_ok: bool
) -> None:
    report = await ReadinessService(probes, timeout_s=0.05).check()
    assert dict(report.checks) == expected_checks
    assert report.ok is expected_ok


async def test_probes_run_concurrently() -> None:
    async def slow() -> None:
        await asyncio.sleep(0.1)

    service = ReadinessService({f"p{i}": slow for i in range(5)}, timeout_s=1)
    started = asyncio.get_running_loop().time()
    await service.check()
    assert asyncio.get_running_loop().time() - started < 0.4
