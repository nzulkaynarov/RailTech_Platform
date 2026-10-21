"""Схемы центра внешних сервисов (M3-CRM-12, ADR-0024)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

ServiceStatus = Literal["ok", "warn", "fail", "unknown", "off"]
MetricValue = float | int | str | None


class ServiceSwitchOut(BaseModel):
    """Выключатель сервиса: доступен ли, выключен ли вручную, что произойдёт при выключении."""

    kind: Literal["vendor", "langfuse", "mail", "telegram", "erp"]
    available: bool
    disabled: bool
    effect: str
    problem: str | None
    reason: str | None
    changed_at: datetime | None
    changed_by: str | None


class IncidentOut(BaseModel):
    id: int
    started_at: datetime
    ended_at: datetime | None
    duration_s: int | None = Field(description="Длительность закрытого инцидента, секунд")
    summary: str
    last_error: str | None
    alerted: bool
    recovery_alerted: bool


class ExternalServiceOut(BaseModel):
    key: str
    title: str
    purpose: str
    system: Literal["crm", "erp", "ensemble"]
    source: Literal["crm", "erp"] = Field(description="Кто проверяет: CRM сама или передаёт ERP")
    check: str = Field(description="Как проверяется — словами")
    frequency: Literal["minute", "quarter", "erp"]
    status: ServiceStatus
    summary: str
    error: str | None
    hint: str | None = Field(description="Что сделать, если не в норме")
    fix_path: str | None = Field(description="Путь в CRM, где это исправляется")
    checked_at: datetime | None
    stale: bool
    latency_ms: int | None
    metrics: dict[str, MetricValue]
    uptime_24h: float | None
    uptime_7d: float | None
    checks_24h: int
    failures_24h: int
    p95_ms_24h: int | None
    switch: ServiceSwitchOut | None
    incident: IncidentOut | None


class ExternalServicesSummary(BaseModel):
    ok: int
    warn: int
    fail: int
    unknown: int
    off: int
    disabled: int


class ExternalServicesOut(BaseModel):
    checked_at: datetime | None
    summary: ExternalServicesSummary
    services: list[ExternalServiceOut]


class ServiceCheckOut(BaseModel):
    checked_at: datetime
    tier: Literal["cheap", "heavy", "manual"]
    status: ServiceStatus
    latency_ms: int | None
    summary: str
    error: str | None


class ServiceDayOut(BaseModel):
    day: date
    ok: int
    warn: int
    fail: int
    unknown: int
    uptime: float | None


class ExternalServiceDetailOut(BaseModel):
    service: ExternalServiceOut
    checks: list[ServiceCheckOut]
    days: list[ServiceDayOut]
    incidents: list[IncidentOut]


class ServiceSwitchIn(BaseModel):
    password: SecretStr = Field(min_length=1, max_length=256)
    reason: str | None = Field(default=None, max_length=200)


class ServiceEnableIn(BaseModel):
    password: SecretStr = Field(min_length=1, max_length=256)
