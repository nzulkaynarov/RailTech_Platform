"""Схемы центра внешних сервисов (M3-CRM-12, ADR-0024)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

ServiceStatus = Literal["ok", "warn", "fail", "unknown", "off"]
ServiceState = Literal[
    "ok", "broken", "unstable", "degraded", "not_configured", "disabled", "expected", "not_checked"
]
ServiceOwner = Literal["admin", "owner", "hosting", "provider"]
ServiceAction = Literal[
    "enter_key",
    "enter_token",
    "recheck",
    "reconnect",
    "open_settings",
    "write_owner",
    "write_hosting",
    "disable_provider",
    "open_bus",
]
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
    state: ServiceState = Field(
        description="Состояние словом: сломано, работает с перебоями, не настроено, выключено "
        "намеренно, ожидаемо на стенде, не проверено, работает"
    )
    cause_key: str = Field(description="Корень причины; у сервисов с общей причиной он общий")
    owner: ServiceOwner | None = Field(description="Кто исправляет; нет — исправлять нечего")
    action: ServiceAction | None = Field(description="Главное действие по смыслу")
    more_actions: list[ServiceAction] = Field(description="Запасные действия")
    since: datetime | None = Field(description="Когда впервые обнаружено (не в порядке с …)")
    flaps_24h: int = Field(
        description="Провалов (полос сбоя) за сутки: «Нестабильно», когда их много"
    )
    last_recovered_at: datetime | None = Field(
        description="Когда восстановился после последнего сбоя за 30 дней (журнал инцидентов)"
    )


class ServiceGroupOut(BaseModel):
    """Одна причина — одна строка «Требует внимания»: сервисы с общим корнем свёрнуты вместе."""

    id: str = Field(description="Корень причины (`cause_key`), стабильный ключ строки")
    state: ServiceState
    owner: ServiceOwner | None
    action: ServiceAction | None
    more_actions: list[ServiceAction]
    headline: str = Field(description="Что случилось одной фразой, без сырых ответов провайдера")
    detail: str | None = Field(description="Что сделать и кому передать")
    affected: list[str] = Field(description="Что перестало работать — функции списком")
    service_keys: list[str]
    titles: list[str]
    since: datetime | None
    technical: list[str] = Field(
        description="Сырой текст проверки, секреты замаскированы; показывается свёрнутым"
    )
    message: str | None = Field(
        description="Готовый текст владельцу или хостингу — копируется, сам не отправляется"
    )
    flaps_24h: int = Field(description="Провалов за сутки по сервисам причины (наибольшее)")


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
    stand: bool = Field(description="Тестовый стенд (не прод): часть причин «ожидаема»")
    groups: list[ServiceGroupOut] = Field(description="Не-`ok` сервисы, свёрнутые по причине")


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
