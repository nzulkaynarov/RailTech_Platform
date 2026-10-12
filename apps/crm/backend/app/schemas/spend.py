"""DTO экранов «Расходы» и «Модели ИИ» (аудит 2026-10-12 §3 пп. 3–5)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class ProviderToday(BaseModel):
    provider: str
    spent_usd: float
    limit_usd: float  # 0 — без лимита


class SpendDay(BaseModel):
    day: date
    work_usd: float
    test_usd: float


class SpendSlice(BaseModel):
    key: str
    cost_usd: float
    calls: int


class LeadSpend(BaseModel):
    lead_id: int
    cost_usd: float
    calls: int


class SpendReport(BaseModel):
    days: int
    today_usd: float
    daily_usd: float  # мягкий бюджет, 0 — не задан
    providers: list[ProviderToday]
    series: list[SpendDay]
    by_purpose: list[SpendSlice]
    by_kind: list[SpendSlice]
    total_usd: float
    leads: int
    avg_per_lead_usd: float
    top_leads: list[LeadSpend]


class ModelStatus(BaseModel):
    alias: str
    provider: str | None
    model: str | None
    health: Literal["ok", "problem", "unknown"]
    health_detail: str | None
    checked_at: datetime | None
    today_usd: float


class ModelTestResult(BaseModel):
    alias: str
    ok: bool
    detail: str | None
    latency_ms: int
    cost_usd: float | None
