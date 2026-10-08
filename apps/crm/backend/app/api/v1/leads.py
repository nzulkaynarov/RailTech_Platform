"""REST по лидам. Фаза 3: лента решений для отладки (до RBAC — только не в prod)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.container import Container
from app.repositories import decisions as repo
from app.repositories.leads import get_lead
from app.schemas.decisions import (
    DecisionsResponse,
    QualifierRunItem,
    TransitionItem,
    qualifier_summary,
)

router = APIRouter(prefix="/api/v1/leads", tags=["leads"])


def get_sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    container: Container = request.app.state.container
    if container.settings.app_env == "prod":
        # Временный отладочный эндпоинт (PLAN Фаза 3); с Фазы 4 — под RBAC.
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return container.session_factory


@router.get("/{lead_id}/decisions", response_model=DecisionsResponse)
async def lead_decisions(
    lead_id: int,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DecisionsResponse:
    async with sessions() as session:
        lead = await get_lead(session, lead_id)
        if lead is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "lead not found")
        runs = await repo.qualifier_runs(session, lead_id, limit)
        moves = await repo.transitions(session, lead_id, limit)
    items: list[QualifierRunItem | TransitionItem] = [
        QualifierRunItem(
            id=r.id,
            at=r.created_at,
            proposed_stage=r.proposed_stage,
            applied_stage=r.applied_stage,
            rejected_reason=r.rejected_reason,
            score_before=r.score_before,
            score_after=r.score_after,
            triggers_fired=list(r.triggers_fired or []),
            escalated=r.escalated,
            error=r.error,
            model=r.model,
            cost_usd=r.cost_usd,
            trace_id=r.trace_id,
            **qualifier_summary(r.output),
        )
        for r in runs
    ]
    items += [
        TransitionItem(
            id=t.id,
            at=t.created_at,
            from_stage=t.from_stage,
            to_stage=t.to_stage,
            source=t.source,
            actor_user_id=t.actor_user_id,
            reason=t.reason,
        )
        for t in moves
    ]
    items.sort(key=lambda i: i.at, reverse=True)
    return DecisionsResponse(
        lead_id=lead.id,
        stage=lead.stage,
        score=lead.score,
        owner_mode=lead.owner_mode,
        items=items[:limit],
    )
