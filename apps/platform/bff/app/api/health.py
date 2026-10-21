"""GET /api/v1/health — состояние BFF и источников (контракт: operationId getHealth)."""

import asyncio
from typing import Literal

import structlog
from fastapi import APIRouter
from pydantic import BaseModel
from redis.asyncio import Redis

from app import __version__
from app.clients.base import TIMEOUT_SECONDS
from app.deps import CrmDep, ErpDep, RedisDep

router = APIRouter(tags=["system"])
log = structlog.get_logger()

CheckState = Literal["ok", "fail"]


class Checks(BaseModel):
    redis: CheckState
    crm: CheckState
    erp: CheckState


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    checks: Checks
    version: str = __version__


async def _redis_ok(redis: Redis) -> bool:
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            return bool(await redis.ping())
    except Exception as exc:  # noqa: BLE001 — любая ошибка Redis = «не жив», health не падает
        log.warning("health_redis_failed", error=type(exc).__name__)
        return False


def _state(ok: bool) -> CheckState:
    return "ok" if ok else "fail"


@router.get("/health", response_model=Health, operation_id="getHealth")
async def get_health(redis: RedisDep, crm: CrmDep, erp: ErpDep) -> Health:
    """Всегда 200: недоступный источник даёт `status: degraded`, а не ошибку (liveness BFF)."""
    redis_ok, crm_ok, erp_ok = await asyncio.gather(
        _redis_ok(redis), crm.is_healthy(), erp.is_healthy()
    )
    checks = Checks(redis=_state(redis_ok), crm=_state(crm_ok), erp=_state(erp_ok))
    ok = redis_ok and crm_ok and erp_ok
    return Health(status="ok" if ok else "degraded", checks=checks)
