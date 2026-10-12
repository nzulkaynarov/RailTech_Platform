"""«Расходы» и «Модели ИИ» (admin, аудит 2026-10-12 §3 пп. 3–5).

Модели — только чтение; «Проверить» — один минимальный платный запрос по нажатию админа,
с записью в аудит. Ключи провайдеров не читаются и не отдаются.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select

from app.api.deps import ContainerDep, require
from app.domain.budget import day_start
from app.domain.errors import NotFoundError
from app.models.system import SystemAlert
from app.repositories import spend as spend_repo
from app.schemas.spend import ModelStatus, ModelTestResult, SpendReport
from app.security import audit
from app.security.principal import Principal
from app.services import models_status, spend

router = APIRouter(prefix="/api/v1", tags=["spend"])


@router.get("/spend", response_model=SpendReport)
async def get_spend(
    _: Annotated[Principal, Depends(require("spend", "read"))],
    container: ContainerDep,
    days: Annotated[int, Query(ge=1, le=180)] = 30,
) -> SpendReport:
    cfg = await container.settings_service.get()
    async with container.session_factory() as session:
        return await spend.build(session, cfg, days, datetime.now(UTC))


@router.get("/models", response_model=list[ModelStatus])
async def list_models(
    _: Annotated[Principal, Depends(require("models", "read"))], container: ContainerDep
) -> list[ModelStatus]:
    cfg = await container.settings_service.get()
    since = day_start(datetime.now(UTC), cfg.business_hours.timezone)
    entries = await container.model_catalog.entries()
    async with container.session_factory() as session:
        rows = await session.scalars(select(SystemAlert).where(SystemAlert.key.like("model:%")))
        alerts = {row.key: row for row in rows}
        today = {alias: usd for alias, usd, _ in await spend_repo.grouped(session, since, "alias")}
    return models_status.statuses(entries, alerts, today)


@router.post("/models/{alias}/test", response_model=ModelTestResult)
async def test_model(
    alias: Annotated[str, Path(max_length=64)],
    who: Annotated[Principal, Depends(require("models", "test"))],
    container: ContainerDep,
) -> ModelTestResult:
    known = set(models_status.ALIASES) | set(await container.model_catalog.entries())
    if alias not in known:
        raise NotFoundError("unknown model alias")
    result = await models_status.probe(container.llm, alias, container.usage_recorder)
    async with container.session_factory() as session, session.begin():
        await audit.record(
            session,
            who.actor,
            "model.test",
            "model",
            alias,
            after={"ok": result.ok, "cost_usd": result.cost_usd},
        )
    return result
