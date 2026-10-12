"""Сделки клиента: список, карточка, создание, изменение, сводка (Q-013, ADR-0019)."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContainerDep, require
from app.domain.errors import NotFoundError
from app.models.auth import User
from app.models.clients import Client
from app.models.deals import Deal
from app.schemas.deals import (
    DealCreate,
    DealOptions,
    DealOut,
    DealsSummary,
    DealStageName,
    DealUpdate,
)
from app.schemas.kb_admin import Created
from app.schemas.leads import ActionResult
from app.security.principal import Principal
from app.services import deals

router = APIRouter(prefix="/api/v1", tags=["deals"])

DealReader = Annotated[Principal, Depends(require("deals", "read"))]
DealWriter = Annotated[Principal, Depends(require("deals", "write"))]


def _joined() -> Select[Deal, str, str]:
    return (
        select(Deal, Client.name, User.full_name)
        .outerjoin(Client, Client.id == Deal.client_id)
        .outerjoin(User, User.id == Deal.owner_user_id)
    )


def filtered(
    stage: str | None,
    owner_user_id: int | None,
    client_id: int | None,
    closed_from: date | None,
    closed_to: date | None,
) -> Select[Deal, str, str]:
    """Фильтры списка сделок — общие для экрана и экспорта CSV."""
    stmt = _joined().order_by(Deal.id.desc())
    if stage:
        stmt = stmt.where(Deal.stage == stage)
    if owner_user_id is not None:
        stmt = stmt.where(Deal.owner_user_id == owner_user_id)
    if client_id is not None:
        stmt = stmt.where(Deal.client_id == client_id)
    if closed_from:
        stmt = stmt.where(Deal.closed_at >= datetime.combine(closed_from, time(), UTC))
    if closed_to:
        end = datetime.combine(closed_to + timedelta(days=1), time(), UTC)
        stmt = stmt.where(Deal.closed_at < end)
    return stmt


async def deal_rows(session: AsyncSession, stmt: Select[Deal, str, str]) -> list[DealOut]:
    result = await session.execute(stmt)
    return [
        DealOut.model_validate(deal, from_attributes=True).model_copy(
            update={"client_name": client, "owner_name": owner}
        )
        for deal, client, owner in result.all()
    ]


@router.get("/deals", response_model=list[DealOut])
async def list_deals(
    _: DealReader,
    container: ContainerDep,
    stage: DealStageName | None = None,
    owner_user_id: int | None = None,
    client_id: int | None = None,
    closed_from: date | None = None,
    closed_to: date | None = None,
) -> list[DealOut]:
    """Сделки, новые сверху (до 500). Период закрытия — включительно, по дате UTC."""
    stmt = filtered(stage, owner_user_id, client_id, closed_from, closed_to).limit(500)
    async with container.session_factory() as session:
        return await deal_rows(session, stmt)


@router.get("/deals/summary", response_model=DealsSummary)
async def deals_summary(
    _: DealReader, container: ContainerDep, days: Annotated[int, Query(ge=1, le=365)] = 30
) -> DealsSummary:
    """Выигрыш (число и суммы по валютам) и отказы по причинам за последние `days` дней."""
    tz = (await container.settings_service.get()).business_hours.timezone
    async with container.session_factory() as session:
        return await deals.summary(session, days, datetime.now(UTC), tz)


@router.get("/deals/options", response_model=DealOptions)
async def deal_options(_: DealReader, container: ContainerDep) -> DealOptions:
    """Причины отказа и валюта по умолчанию — для форм сделки и закрытия лида."""
    cfg = (await container.settings_service.get()).deals
    return DealOptions(lost_reasons=cfg.lost_reasons, currency=cfg.currency)


@router.get("/deals/{deal_id}", response_model=DealOut)
async def get_deal(deal_id: int, _: DealReader, container: ContainerDep) -> DealOut:
    async with container.session_factory() as session:
        rows = await deal_rows(session, _joined().where(Deal.id == deal_id))
    if not rows:
        raise NotFoundError("deal not found")
    return rows[0]


@router.post("/deals", response_model=Created, status_code=status.HTTP_201_CREATED)
async def create_deal(body: DealCreate, who: DealWriter, container: ContainerDep) -> Created:
    """Новая сделка; валюта по умолчанию — из настройки `deals.currency`."""
    cfg = await container.settings_service.get()
    async with container.session_factory() as session, session.begin():
        deal_id = await deals.create(session, who, body, cfg.deals)
    return Created(id=deal_id)


@router.patch("/deals/{deal_id}", response_model=ActionResult)
async def update_deal(
    deal_id: int, body: DealUpdate, who: DealWriter, container: ContainerDep
) -> ActionResult:
    """Изменить сделку. Выигранную менять может только админ (409 `deal_won_final`)."""
    cfg = await container.settings_service.get()
    async with container.session_factory() as session, session.begin():
        await deals.update(session, who, deal_id, body, cfg.deals)
    return ActionResult()
