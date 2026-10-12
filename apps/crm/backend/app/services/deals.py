"""Сделки: создание, изменение, итог при закрытии лида, сводка для дашборда (ADR-0019).

Решения о переходах — `domain/deals.py`; здесь — чтение/запись и аудит. Функции принимают
открытую сессию: закрытие лида и его сделки — одна транзакция (данные согласованы).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.deals import DealStage, lost_reason, may_transition, plan_lead_outcome
from app.domain.errors import ConflictError, NotFoundError, Reason
from app.models.clients import Client
from app.models.deals import Deal
from app.models.leads import Lead
from app.schemas.deals import CurrencySum, DealCreate, DealsSummary, DealUpdate, ReasonCount
from app.schemas.settings import DealsSettings
from app.security import audit
from app.security.principal import Principal

REQUIRED_FIELDS = frozenset({"title", "currency"})


def snapshot(deal: Deal) -> dict[str, Any]:
    return {
        "stage": deal.stage,
        "amount": str(deal.amount) if deal.amount is not None else None,
        "currency": deal.currency,
        "lost_reason": deal.lost_reason,
        "owner_user_id": deal.owner_user_id,
        "expected_close_date": deal.expected_close_date.isoformat()
        if deal.expected_close_date
        else None,
    }


def _set_stage(deal: Deal, stage: DealStage, reason: str | None, now: datetime) -> None:
    deal.stage = stage.value
    deal.closed_at = None if stage == DealStage.OPEN else now
    deal.lost_reason = reason if stage == DealStage.LOST else None


async def open_deal(session: AsyncSession, lead_id: int) -> Deal | None:
    stmt = (
        select(Deal)
        .where(Deal.lead_id == lead_id, Deal.stage == DealStage.OPEN.value)
        .order_by(Deal.id.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).first()


async def apply_lead_outcome(
    session: AsyncSession,
    who: Principal,
    lead: Lead,
    outcome: str,
    cfg: DealsSettings,
    *,
    reason_code: str | None = None,
    amount: Decimal | None = None,
) -> Deal | None:
    """Закрытие лида → сделка (в той же транзакции, что и переход стадии лида)."""
    deal = await open_deal(session, lead.id)
    plan = plan_lead_outcome(outcome, deal is not None, reason_code, cfg.lost_reasons)
    if plan is None:
        return None
    before = snapshot(deal) if deal is not None else None
    if deal is None:
        deal = Deal(
            lead_id=lead.id,
            client_id=lead.client_id,
            title=lead.display_name or f"#{lead.id}",
            product_key=lead.product_interest[0] if lead.product_interest else None,
            currency=cfg.currency,
            owner_user_id=lead.assigned_user_id,
        )
        session.add(deal)
    if amount is not None:
        deal.amount = amount
    _set_stage(deal, plan.stage, plan.lost_reason, datetime.now(UTC))
    await session.flush()
    action = f"deal.{plan.stage.value}"
    await audit.record(
        session, who.actor, action, "deal", deal.id, before=before, after=snapshot(deal)
    )
    return deal


async def create(
    session: AsyncSession, who: Principal, body: DealCreate, cfg: DealsSettings
) -> int:
    client_id = body.client_id
    if body.lead_id is not None:
        lead = await session.get(Lead, body.lead_id)
        if lead is None:
            raise NotFoundError("lead not found")
        client_id = client_id or lead.client_id
    if client_id is not None and await session.get(Client, client_id) is None:
        raise NotFoundError("client not found")
    deal = Deal(
        title=body.title.strip(),
        client_id=client_id,
        lead_id=body.lead_id,
        product_key=body.product_key,
        amount=body.amount,
        currency=body.currency or cfg.currency,
        expected_close_date=body.expected_close_date,
        owner_user_id=body.owner_user_id or who.user_id,
    )
    session.add(deal)
    await session.flush()
    await audit.record(session, who.actor, "deal.create", "deal", deal.id, after=snapshot(deal))
    return deal.id


async def update(
    session: AsyncSession, who: Principal, deal_id: int, body: DealUpdate, cfg: DealsSettings
) -> None:
    deal = await session.get(Deal, deal_id)
    if deal is None:
        raise NotFoundError("deal not found")
    before = snapshot(deal)
    fields = body.model_dump(exclude_unset=True)
    stage = fields.pop("stage", None)
    reason = fields.pop("lost_reason", None)
    for key, value in fields.items():
        if key in REQUIRED_FIELDS and value is None:
            continue  # обязательные поля нельзя очистить — пустое значение = «не менять»
        setattr(deal, key, value.strip() if key == "title" else value)
    if stage is not None and stage != deal.stage:
        target = DealStage(stage)
        if not may_transition(DealStage(deal.stage), target, is_admin=who.is_admin):
            raise ConflictError("won deal is final", reason=Reason.DEAL_WON_FINAL)
        _set_stage(deal, target, lost_reason(reason, cfg.lost_reasons), datetime.now(UTC))
    elif reason is not None and deal.stage == DealStage.LOST:
        deal.lost_reason = lost_reason(reason, cfg.lost_reasons)
    await session.flush()
    await audit.record(
        session, who.actor, "deal.update", "deal", deal.id, before=before, after=snapshot(deal)
    )


async def summary(session: AsyncSession, days: int, now: datetime) -> DealsSummary:
    since = now - timedelta(days=days)
    closed = (Deal.closed_at >= since,)
    won = await session.execute(
        select(
            Deal.currency,
            func.count(),
            func.coalesce(func.sum(Deal.amount), 0),
            func.count(Deal.amount),
        )
        .where(Deal.stage == DealStage.WON.value, *closed)
        .group_by(Deal.currency)
        .order_by(Deal.currency)
    )
    won_rows = won.all()
    # Одно выражение в SELECT и GROUP BY: два `coalesce(..., "—")` — два разных параметра,
    # и PostgreSQL считает их разными выражениями (GroupingError).
    reason = func.coalesce(Deal.lost_reason, literal_column("'—'")).label("reason")
    lost = await session.execute(
        select(reason, func.count(), func.coalesce(func.sum(Deal.amount), 0))
        .where(Deal.stage == DealStage.LOST.value, *closed)
        .group_by(reason)
        .order_by(func.count().desc())
    )
    lost_rows = lost.all()
    open_count = await session.scalar(
        select(func.count()).select_from(Deal).where(Deal.stage == DealStage.OPEN.value)
    )
    return DealsSummary(
        days=days,
        won_count=sum(int(r[1]) for r in won_rows),
        won_amounts=[CurrencySum(currency=r[0], amount=Decimal(r[2] or 0)) for r in won_rows],
        won_without_amount=sum(int(r[1]) - int(r[3]) for r in won_rows),
        lost_count=sum(int(r[1]) for r in lost_rows),
        lost_by_reason=[
            ReasonCount(reason=r[0], count=int(r[1]), amount=Decimal(r[2] or 0)) for r in lost_rows
        ],
        open_count=int(open_count or 0),
    )
