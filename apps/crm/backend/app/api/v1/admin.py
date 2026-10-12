"""Дашборд (все роли) и журнал аудита (admin) — PLAN Фаза 5."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContainerDep, require
from app.models.auth import AuditLog, User
from app.schemas.admin import AuditItem, AuditPage, Dashboard
from app.schemas.leads import ActionResult
from app.security.principal import Principal
from app.services import dashboard

router = APIRouter(prefix="/api/v1", tags=["admin"])


@router.get("/dashboard", response_model=Dashboard)
async def get_dashboard(
    _: Annotated[Principal, Depends(require("dashboard", "read"))],
    container: ContainerDep,
    days: Annotated[int, Query(ge=1, le=180)] = 30,
) -> Dashboard:
    cfg = await container.settings_service.get()
    today = datetime.now(ZoneInfo(cfg.business_hours.timezone)).date()
    async with container.session_factory() as session:
        return await dashboard.build(session, days, today)


@router.post("/dashboard/refresh", response_model=ActionResult)
async def refresh_dashboard(
    _: Annotated[Principal, Depends(require("settings", "write"))], container: ContainerDep
) -> ActionResult:
    async with container.session_factory() as session, session.begin():
        await dashboard.refresh(session)
    return ActionResult()


@router.get("/audit", response_model=AuditPage)
async def list_audit(
    _: Annotated[Principal, Depends(require("audit", "read"))],
    container: ContainerDep,
    actor_user_id: int | None = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_type: Annotated[str | None, Query(max_length=32)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    exclude_actions: Annotated[
        list[str] | None,
        Query(max_length=64, description="Скрыть действия с этими префиксами (напр. auth.login)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    stmt = select(AuditLog)
    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    for prefix in exclude_actions or []:
        stmt = stmt.where(~AuditLog.action.startswith(prefix))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if created_from:
        stmt = stmt.where(AuditLog.created_at >= created_from)
    if created_to:
        stmt = stmt.where(AuditLog.created_at < created_to)
    async with container.session_factory() as session:
        total = int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = (
            await session.scalars(stmt.order_by(AuditLog.id.desc()).limit(limit).offset(offset))
        ).all()
        ids = {r.actor_user_id for r in rows if r.actor_user_id is not None}
        names = (
            dict(
                (await session.execute(select(User.id, User.full_name).where(User.id.in_(ids))))
                .tuples()
                .all()
            )
            if ids
            else {}
        )
    items = [
        AuditItem.model_validate(
            {
                **{c: getattr(r, c) for c in AuditItem.model_fields if c != "actor_name"},
                "ip": str(r.ip) if r.ip else None,
                "actor_name": names.get(r.actor_user_id) if r.actor_user_id else None,
            }
        )
        for r in rows
    ]
    return AuditPage(items=items, total=total)


async def _actor_names(session: AsyncSession, ids: set[int | None]) -> dict[int, str]:
    """Имена авторов записей журнала — вместо «Пользователь #5» на экране «Аудит»."""
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(wanted)))
    return dict(rows.tuples().all())
