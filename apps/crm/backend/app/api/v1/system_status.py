"""«Состояние системы» (admin): зависимости, модели, бюджет ИИ, бот, очередь, ERP, секреты."""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import ContainerDep, require
from app.api.health import get_readiness
from app.container import Container
from app.domain.system_status import BotFacts, Component
from app.integrations.telegram import resolve_token
from app.schemas.system import ComponentStatusOut, SystemStatusOut
from app.security.principal import Principal
from app.services.readiness import ReadinessService
from app.services.system_status import SystemStatusService

router = APIRouter(prefix="/api/v1/system", tags=["system"])

_SEVERITY = ("ok", "unknown", "warn", "fail")


async def collect_components(
    request: Request, container: Container, readiness: ReadinessService, now: datetime
) -> list[Component]:
    """Один источник здоровья для «Состояния», индикатора в шапке и чек-листа настройки."""
    supervisor = getattr(request.app.state, "bot", None)
    bot = (
        None
        if supervisor is None
        else BotFacts(supervisor.running, supervisor.source, supervisor.last_error)
    )
    _, source = await resolve_token(container.secrets_store, container.settings)
    has_token = source in ("db", "env")
    service = SystemStatusService(
        container.session_factory,
        container.settings_service,
        container.settings,
        readiness,
        container.backup_service,
    )
    erp = await container.erp_connector.health_facts()
    ai_budget = await container.ai_spend.today_facts()
    return await service.collect(now, bot, token_configured=has_token, erp=erp, ai_budget=ai_budget)


@router.get("/status", response_model=SystemStatusOut)
async def system_status(
    request: Request,
    _: Annotated[Principal, Depends(require("system", "read"))],
    container: ContainerDep,
    readiness: Annotated[ReadinessService, Depends(get_readiness)],
) -> SystemStatusOut:
    """Только чтение: моделей не вызывает, их здоровье — из последней проверки монитора.

    Компоненты отсортированы: сбой → предупреждение → неизвестно → норма.
    """
    now = datetime.now(UTC)
    components = await collect_components(request, container, readiness, now)
    worst = max((c.status for c in components), key=_SEVERITY.index, default="unknown")
    return SystemStatusOut(
        status=worst,
        checked_at=now,
        components=[ComponentStatusOut(**asdict(c)) for c in components],
    )
