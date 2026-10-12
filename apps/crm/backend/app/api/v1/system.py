"""«Состояние системы» (admin): зависимости, модели по данным монитора, бот, очередь, секреты."""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import ContainerDep, require
from app.api.health import get_readiness
from app.schemas.system import ComponentStatusOut, SystemStatusOut
from app.security.principal import Principal
from app.services.readiness import ReadinessService
from app.services.system_status import SystemStatusService

router = APIRouter(prefix="/api/v1/system", tags=["system"])

_SEVERITY = ("ok", "unknown", "warn", "fail")


@router.get("/status", response_model=SystemStatusOut)
async def system_status(
    request: Request,
    _: Annotated[Principal, Depends(require("system", "read"))],
    container: ContainerDep,
    readiness: Annotated[ReadinessService, Depends(get_readiness)],
) -> SystemStatusOut:
    """Только чтение: моделей не вызывает, их здоровье — из последней проверки монитора."""
    bot = getattr(request.app.state, "bot", None)
    service = SystemStatusService(
        container.session_factory, container.settings_service, container.settings, readiness
    )
    now = datetime.now(UTC)
    components = await service.collect(now, bot.running if bot is not None else None)
    worst = max((c.status for c in components), key=_SEVERITY.index, default="unknown")
    return SystemStatusOut(
        status=worst,
        checked_at=now,
        components=[ComponentStatusOut(**asdict(c)) for c in components],
    )
