"""DTO настроек, «сухого прогона», дашборда и аудита (PLAN Фаза 5)."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    values: dict[str, dict[str, Any]]
    schemas: dict[str, dict[str, Any]]


class DryRunRowOut(BaseModel):
    run_id: int
    lead_id: int
    at: datetime
    current: list[str]
    candidate: list[str]


class DryRunResponse(BaseModel):
    dialogs: int
    escalated_current: int
    escalated_candidate: int
    by_code_current: dict[str, int]
    by_code_candidate: dict[str, int]
    changed: list[DryRunRowOut]


class DailyStat(BaseModel):
    day: date
    leads_created: int
    escalations: int
    taken: int
    won: int
    lost: int
    bot_answers: int
    fallbacks: int
    avg_take_minutes: float | None
    cost_usd: float


class ManagerStat(BaseModel):
    """Строка таблицы «Менеджеры» за период (SPEC §10.1)."""

    user_id: int
    name: str
    taken: int = Field(description="Забрал передач за период")
    median_take_minutes: float | None = Field(description="Медиана времени до «Забрать», мин")
    won: int = Field(description="Выиграл сделок за период")
    active_leads: int = Field(description="Ведёт лидов сейчас (кроме выигранных и потерянных)")


class SlaStat(BaseModel):
    """Передачи периода, забранные до `sla_due_at`; ещё не истёкшие открытые не считаются."""

    due: int
    met: int
    share: float | None


class Dashboard(BaseModel):
    days: int
    funnel: dict[str, int]
    totals: DailyStat
    previous: DailyStat | None = Field(
        default=None, description="Итоги прошлого периода той же длины (для тренда KPI)"
    )
    managers: list[ManagerStat] = Field(default_factory=list)
    sla: SlaStat | None = None
    daily: list[DailyStat]
    escalation_reasons: dict[str, int]
    fallback_share: float | None
    open_gaps: int
    open_escalations: int
    refreshed_at: datetime | None


class AuditItem(BaseModel):
    id: int
    actor_user_id: int | None
    actor_type: str
    action: str
    entity_type: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None
    created_at: datetime
    actor_name: str | None = Field(default=None, description="Имя пользователя-автора")


class AuditPage(BaseModel):
    items: list[AuditItem]
    total: int
