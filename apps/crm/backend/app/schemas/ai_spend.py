"""DTO экрана «Расходы» по ансамблю (M3-CRM-09): журнал LiteLLM по системам, функциям, моделям."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

AiSpendGroup = Literal["day", "system", "feature", "model"]


class AiSpendSystemCost(BaseModel):
    system: str = Field(description="`crm`, `erp` или `other` — вызов без тега системы")
    cost_usd: float
    calls: int


class AiSpendRow(BaseModel):
    key: str = Field(description="День `YYYY-MM-DD`, система, функция или алиас — по `group`")
    calls: int = Field(description="Строк журнала LiteLLM (вызовов), включая неуспешные")
    failed_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    fallback_calls: int = Field(description="Деградации: успешные вызовы через fallback-model")
    by_system: list[AiSpendSystemCost]


class AiSpendTotals(BaseModel):
    calls: int
    failed_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    fallback_calls: int


class AiSystemBudget(BaseModel):
    system: str
    daily_usd: float = Field(description="Бюджет на день; 0 — без лимита")
    today_usd: float
    today_calls: int
    over_today: bool
    period_usd: float
    period_calls: int
    fallback_calls: int
    days_over: int = Field(description="Дней периода с расходом ≥ бюджета")
    connected: bool = Field(description="За период есть вызовы с тегом этой системы")


class AiBudgetOverrun(BaseModel):
    system: str
    day: date
    cost_usd: float
    daily_usd: float


class AiSpendReport(BaseModel):
    date_from: date
    date_to: date
    group: AiSpendGroup
    timezone: str
    rows: list[AiSpendRow]
    totals: AiSpendTotals
    systems: list[AiSystemBudget]
    overruns: list[AiBudgetOverrun]
    erp_connected: bool = Field(description="ERP ходит в шлюз: есть строки `system=erp` за период")
    truncated: bool = Field(description="Журнал LiteLLM отдал не все строки (потолок выборки)")
    fetched_at: datetime
