"""DTO сделок (Q-013, ADR-0019)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

DealStageName = Literal["open", "won", "lost"]


class DealOut(BaseModel):
    id: int
    client_id: int | None
    client_name: str | None = None
    lead_id: int | None
    title: str
    product_key: str | None
    amount: Decimal | None
    currency: str
    stage: DealStageName
    expected_close_date: date | None
    closed_at: datetime | None
    lost_reason: str | None
    owner_user_id: int | None
    owner_name: str | None = None
    created_at: datetime
    erp_deal_id: int | None = None
    external_stage: str | None = None


class DealCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    client_id: int | None = None
    lead_id: int | None = None
    product_key: str | None = Field(default=None, max_length=64)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    expected_close_date: date | None = None
    owner_user_id: int | None = None


class DealUpdate(BaseModel):
    """Только переданные поля меняются; `stage=lost` без причины → «Другое»."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    product_key: str | None = Field(default=None, max_length=64)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    stage: DealStageName | None = None
    expected_close_date: date | None = None
    lost_reason: str | None = Field(default=None, max_length=120)
    owner_user_id: int | None = None


class ReasonCount(BaseModel):
    reason: str
    count: int
    amount: Decimal


class CurrencySum(BaseModel):
    currency: str
    amount: Decimal


class DealDay(BaseModel):
    """Сделок закрыто за день (по часовому поясу команды): выиграно и проиграно."""

    day: date
    won: int
    lost: int


class DealsSummary(BaseModel):
    days: int
    won_count: int
    won_amounts: list[CurrencySum]
    won_without_amount: int = 0
    """Выигранные сделки без суммы: дашборд не выдаёт частичную сумму за полную."""
    lost_count: int
    lost_by_reason: list[ReasonCount]
    open_count: int
    daily: list[DealDay] = Field(
        default_factory=list, description="Выиграно/проиграно по дням периода, без пропусков"
    )


class DealOptions(BaseModel):
    """Справочник для форм: причины отказа и валюта по умолчанию из настройки `deals`."""

    lost_reasons: list[str]
    currency: str
