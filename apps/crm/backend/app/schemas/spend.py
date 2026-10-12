"""DTO экранов «Расходы» и «Модели ИИ» (аудит 2026-10-12 §3 пп. 3–5)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


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
    lead_name: str | None = None
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


class ModelChangeIn(BaseModel):
    """Смена роли (ADR-0020). Ключ без значения — ключ провайдера из env сервера (`.env`)."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["anthropic", "gemini", "openai"]
    model: str = Field(min_length=1, max_length=128)
    api_key: SecretStr | None = Field(default=None, min_length=8, max_length=512)
    api_base: str | None = Field(default=None, max_length=256)
    password: SecretStr = Field(min_length=1, max_length=256)


class ModelResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr = Field(min_length=1, max_length=256)


class ModelChangeResult(BaseModel):
    alias: str
    provider: str
    model: str
    key_source: Literal["crm", "env"]
    reindex_required: bool
    quality_check_recommended: bool
