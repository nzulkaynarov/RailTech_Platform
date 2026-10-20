"""Сделки: создание, изменение, итог при закрытии лида, сводка для дашборда (ADR-0019).

Решения о переходах — `domain/deals.py`; здесь — чтение/запись и аудит. Функции принимают
открытую сессию: закрытие лида и его сделки — одна транзакция (данные согласованы).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.deals import (
    DealStage,
    deal_title,
    erp_owned_changes,
    lost_reason,
    may_edit,
    may_transition,
    plan_lead_outcome,
)
from app.domain.errors import ConflictError, NotFoundError, Reason, ValidationFailedError
from app.models.auth import User
from app.models.clients import Client
from app.models.deals import Deal
from app.models.kb import Product
from app.models.leads import Lead, Setting
from app.schemas.deals import (
    CurrencySum,
    DealCreate,
    DealDay,
    DealsSummary,
    DealUpdate,
    ReasonCount,
)
from app.schemas.settings_deals import DealsSettings
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


async def title_for(session: AsyncSession, lead: Lead) -> str:
    """«<Клиент или имя лида> — <продукт>»: имя продукта из `products` (аудит P1-5)."""
    client = await session.get(Client, lead.client_id) if lead.client_id is not None else None
    key = lead.product_interest[0] if lead.product_interest else None
    product = await session.get(Product, key) if key else None
    return deal_title(
        client_name=client.name if client is not None else None,
        lead_name=lead.display_name,
        product_name=product.name if product is not None else key,
        lead_id=lead.id,
    )


async def default_currency(session: AsyncSession) -> str:
    """Валюта новых сделок из настройки `deals` (без кэша сервиса настроек — внутри транзакции)."""
    row = await session.get(Setting, "deals")
    try:
        return DealsSettings.model_validate(row.value if row is not None else {}).currency
    except ValidationError:
        return DealsSettings().currency


async def ensure_open_deal(
    session: AsyncSession, lead: Lead, *, actor: Principal | None = None
) -> Deal:
    """Открытая сделка лида (Q-021): «Квалифицирован» и «Новая сделка». Идемпотентно —
    одна открытая сделка на лида; повторный вызов возвращает существующую."""
    deal = await open_deal(session, lead.id)
    if deal is not None:
        return deal
    deal = Deal(
        lead_id=lead.id,
        client_id=lead.client_id,
        title=await title_for(session, lead),
        product_key=lead.product_interest[0] if lead.product_interest else None,
        currency=await default_currency(session),
        owner_user_id=lead.assigned_user_id,
        stage=DealStage.OPEN.value,
    )
    session.add(deal)
    await session.flush()
    await audit.record(
        session,
        actor.actor if actor is not None else audit.Actor.system(),
        "deal.open",
        "deal",
        deal.id,
        after=snapshot(deal),
    )
    return deal


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
            title=await title_for(session, lead),
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
        if client_id is not None and lead.client_id not in (None, client_id):
            raise ValidationFailedError("lead belongs to another client", field="client_id")
        client_id = client_id or lead.client_id
    if client_id is not None and await session.get(Client, client_id) is None:
        raise NotFoundError("client not found")
    await _check_owner(session, body.owner_user_id)
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
    fields = body.model_dump(exclude_unset=True)
    if deal.erp_deal_id is not None:
        # Зеркало заявки ERP: название, сумму, валюту, стадию и причину отказа ведёт бэк-офис
        # (приёмник событий перезапишет правку); в CRM — ответственный, срок и продукт (I-26).
        current = {
            "title": deal.title,
            "amount": deal.amount,
            "currency": deal.currency,
            "stage": deal.stage,
            "lost_reason": deal.lost_reason,
        }
        owned = erp_owned_changes(current, fields)
        if owned:
            raise ConflictError(
                "deal is managed by the back office (ERP)",
                reason=Reason.DEAL_OWNED_BY_ERP,
                fields=owned,
            )
    if not may_edit(DealStage(deal.stage), is_admin=who.is_admin):
        # Выигранная сделка — финал: сумму, валюту, владельца меняет только админ (аудит P0-3).
        raise ConflictError("won deal is final", reason=Reason.DEAL_WON_FINAL)
    before = snapshot(deal)
    if "owner_user_id" in fields:
        await _check_owner(session, fields["owner_user_id"])
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


async def _check_owner(session: AsyncSession, user_id: int | None) -> None:
    if user_id is None:
        return
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise ValidationFailedError(
            "choose an active colleague", reason=Reason.INACTIVE_COLLEAGUE, field="owner_user_id"
        )


async def summary(
    session: AsyncSession, days: int, now: datetime, tz: str = "Asia/Tashkent"
) -> DealsSummary:
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
        daily=await _daily(session, since, now, tz),
    )


async def _daily(session: AsyncSession, since: datetime, now: datetime, tz: str) -> list[DealDay]:
    day = func.date(func.timezone(tz, Deal.closed_at)).label("day")
    rows = await session.execute(
        select(day, Deal.stage, func.count())
        .where(Deal.stage.in_((DealStage.WON.value, DealStage.LOST.value)), Deal.closed_at >= since)
        .group_by(day, Deal.stage)
    )
    counts = {(r[0], r[1]): int(r[2]) for r in rows.all()}
    return fill_days(
        counts, since.astimezone(ZoneInfo(tz)).date(), now.astimezone(ZoneInfo(tz)).date()
    )


def fill_days(counts: dict[tuple[date, str], int], first: date, last: date) -> list[DealDay]:
    """Ряд по дням без пропусков (график не должен «склеивать» дни без сделок)."""
    out = []
    day = first
    while day <= last:
        out.append(
            DealDay(
                day=day,
                won=counts.get((day, DealStage.WON.value), 0),
                lost=counts.get((day, DealStage.LOST.value), 0),
            )
        )
        day += timedelta(days=1)
    return out
