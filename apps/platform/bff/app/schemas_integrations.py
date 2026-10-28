"""Модели Admin · Внешние интеграции (контракт platform-bff.yaml 0.7.0, тег `integrations`).

Ответы BFF — подмножество ответов CRM (`crm_models`, `make crm-models`): объявлено только то,
что нужно экрану. Значений секретов в ответах CRM нет, а здесь тем более: у моделей нет полей
под токен бота, ключи моделей, пароль SMTP и коды сопряжения — только «задан» и последние
четыре символа. Тела запросов хранят секреты как `SecretStr` (в `repr` и журнале — звёздочки)
и отдают CRM через `secret()`.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

CardKey = Literal["erp", "telegram", "mail", "services", "models", "spend", "storage", "system"]
Level = Literal["ok", "warn", "fail", "unknown", "off"]
Access = Literal["ok", "forbidden", "unavailable"]
Note = Literal[
    "all_ok",
    "problems",
    "not_configured",
    "paused",
    "rotation_pending",
    "backup_stale",
    "no_backups",
    "bot_not_running",
    "budget_near",
    "budget_over",
    "no_data",
]
AttentionKind = Literal[
    "not_configured",
    "service",
    "model_problem",
    "backup_stale",
    "component",
    "budget_over",
    "budget_near",
    "rotation_pending",
    "paused",
    "bot_not_running",
]
Severity = Literal["fail", "warn", "setup"]
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
MailStatus = Literal["queued", "sent", "failed", "skipped_no_smtp"]


def secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


# --- запросы ------------------------------------------------------------------------------------


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PasswordConfirm(_In):
    password: SecretStr = Field(min_length=1, max_length=256)


class ErpPairIn(_In):
    base_url: str = Field(min_length=1, max_length=500)
    code: SecretStr | None = Field(default=None, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=256)


class TelegramTokenIn(_In):
    token: SecretStr = Field(min_length=20, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=256)


class SmtpSettingsIn(_In):
    host: str = Field(max_length=253)
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"] = "starttls"
    from_email: str = Field(default="", max_length=255)
    from_name: str = Field(default="", max_length=120)
    username: str | None = Field(default=None, max_length=255)
    smtp_password: SecretStr | None = Field(default=None, min_length=1, max_length=512)
    password: SecretStr = Field(min_length=1, max_length=256)


class OffsiteBackupIn(_In):
    """Внешняя копия бэкапов (OPS-GDRIVE-2): ключ сервисного аккаунта Google (`None` — прежний),
    папка общего диска, пароль администратора. Ключ дальше CRM не уходит и не возвращается."""

    key_json: SecretStr | None = Field(default=None, min_length=1, max_length=16384)
    folder_id: str = Field(min_length=1, max_length=512)
    password: SecretStr = Field(min_length=1, max_length=256)


class ServiceSwitchIn(_In):
    password: SecretStr = Field(min_length=1, max_length=256)
    reason: str | None = Field(default=None, max_length=200)


class AiModelChangeIn(_In):
    provider: Literal["anthropic", "gemini", "openai"]
    model: str = Field(min_length=1, max_length=128)
    api_key: SecretStr | None = Field(default=None, min_length=8, max_length=512)
    api_base: str | None = Field(default=None, max_length=256)
    password: SecretStr = Field(min_length=1, max_length=256)


class ProviderKeyIn(_In):
    api_key: SecretStr = Field(min_length=8, max_length=512)
    password: SecretStr = Field(min_length=1, max_length=256)


class LocalizedText(_In):
    ru: str
    uz: str
    en: str


class BotProfile(_In):
    name: LocalizedText
    short_description: LocalizedText
    description: LocalizedText


# --- ответы -------------------------------------------------------------------------------------


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ErpConnector(_Out):
    base_url: str
    configured: bool
    mode: Literal["local", "erp"]
    paired: bool
    previous_secret_until: datetime | None
    rotation_pending: bool
    secrets_enabled: bool
    suggested_base_url: str
    token_configured: bool
    token_last4: str | None
    token_updated_at: datetime | None
    webhook_secret_configured: bool
    webhook_secret_last4: str | None


class ErpCheck(_Out):
    checked_at: datetime
    latency_ms: int | None
    migrations_applied: bool | None
    queue_alive: bool | None
    retry_after_s: int | None
    status: Literal["ok", "degraded", "rate_limited"]
    version: str | None


class ErpPairing(_Out):
    check: ErpCheck | None
    check_error: str | None
    status: ErpConnector


class TelegramConnector(_Out):
    channel_id: int | None
    channel_title: str | None
    configured: bool
    last4: str | None
    last_error: str | None
    mode: str
    running: bool
    secrets_enabled: bool
    updated_at: datetime | None
    username: str | None


class TelegramChannel(_Out):
    chat_id: int
    chat_type: str
    detected_at: datetime
    title: str


class TelegramChannelList(_Out):
    items: list[TelegramChannel]


class BotProfilePublish(_Out):
    at: datetime
    changed: int
    error: Literal["rate_limited", "telegram_error", "bot_not_running"] | None
    ok: bool
    retry_after: int | None


class BotProfileText(_Out):
    en: str
    ru: str
    uz: str


class BotProfileOut(_Out):
    description: BotProfileText
    name: BotProfileText
    short_description: BotProfileText


class BotProfileState(_Out):
    profile: BotProfileOut
    published: BotProfilePublish | None


class ActionOk(_Out):
    id: int | None
    ok: Literal[True]


class SmtpConnector(_Out):
    configured: bool
    from_email: str
    from_name: str
    host: str
    password_configured: bool
    password_last4: str | None
    password_updated_at: datetime | None
    port: int
    secrets_enabled: bool
    security: Literal["starttls", "ssl", "none"]
    username: str


OffsiteReason = Literal[
    "ok",
    "key_rejected",
    "drive_api_disabled",
    "folder_not_found",
    "not_folder",
    "not_shared_drive",
    "read_only",
    "network",
]


class OffsiteCheck(_Out):
    ok: bool
    reason: OffsiteReason
    folder_name: str | None
    checked_at: datetime


class OffsiteBackup(_Out):
    configured: bool
    folder_id: str
    client_email: str
    key_suffix: str | None
    key_updated_at: datetime | None
    delivered_at: datetime | None
    last_check: OffsiteCheck | None
    secrets_enabled: bool


class SmtpCheck(_Out):
    authenticated: bool
    latency_ms: int
    server: str


class MailLogItem(_Out):
    attempts: int
    created_at: datetime
    error: str | None
    id: int
    sent_at: datetime | None
    status: MailStatus
    subject: str
    template: str
    to_email: str


class MailLog(_Out):
    items: list[MailLogItem]


class MailQueued(_Out):
    email_log_id: int
    status: MailStatus
    to_email: str


class ServiceIncident(_Out):
    duration_s: int | None
    ended_at: datetime | None
    id: int
    last_error: str | None
    started_at: datetime
    summary: str


class ServiceSwitch(_Out):
    available: bool
    changed_at: datetime | None
    changed_by: str | None
    disabled: bool
    effect: str
    kind: Literal["vendor", "langfuse", "mail", "telegram", "erp"]
    problem: str | None
    reason: str | None


class ServiceGroup(_Out):
    """Одна причина — одна строка: сервисы с общим корнем (W15-H3, CRM `ServiceGroupOut`)."""

    action: ServiceAction | None
    affected: list[str]
    detail: str | None
    fix_card: CardKey | None
    flaps_24h: int
    headline: str
    id: str
    message: str | None
    more_actions: list[ServiceAction]
    owner: ServiceOwner | None
    service_keys: list[str]
    since: datetime | None
    state: ServiceState
    technical: list[str]
    titles: list[str]


class ExternalService(_Out):
    action: ServiceAction | None
    cause_key: str
    flaps_24h: int
    last_recovered_at: datetime | None
    more_actions: list[ServiceAction]
    owner: ServiceOwner | None
    since: datetime | None
    state: ServiceState
    check: str
    checked_at: datetime | None
    checks_24h: int
    error: str | None
    failures_24h: int
    fix_card: CardKey | None
    frequency: Literal["minute", "quarter", "erp"]
    hint: str | None
    incident: ServiceIncident | None
    key: str
    latency_ms: int | None
    p95_ms_24h: int | None
    purpose: str
    source: Literal["crm", "erp"]
    stale: bool
    status: Level
    summary: str
    switch: ServiceSwitch | None
    system: Literal["crm", "erp", "ensemble"]
    title: str
    uptime_24h: float | None
    uptime_7d: float | None


class ServicesSummary(_Out):
    disabled: int
    fail: int
    off: int
    ok: int
    unknown: int
    warn: int


class ExternalServiceList(_Out):
    checked_at: datetime | None
    groups: list[ServiceGroup]
    stand: bool
    summary: ServicesSummary
    items: list[ExternalService]


class ServiceCheck(_Out):
    checked_at: datetime
    error: str | None
    latency_ms: int | None
    status: Level
    summary: str
    tier: Literal["cheap", "heavy", "manual"]


class ServiceDay(_Out):
    day: date
    fail: int
    ok: int
    unknown: int
    uptime: float | None
    warn: int


class ExternalServiceDetail(_Out):
    checks: list[ServiceCheck]
    days: list[ServiceDay]
    incidents: list[ServiceIncident]
    service: ExternalService


class AiModel(_Out):
    alias: str
    checked_at: datetime | None
    health: Literal["ok", "problem", "unknown"]
    health_detail: str | None
    model: str | None
    provider: str | None
    today_usd: float
    key_last4: str | None
    key_source: Literal["crm", "env"] | None


class AiModelList(_Out):
    items: list[AiModel]


class AiModelChange(_Out):
    alias: str
    key_source: Literal["crm", "env"]
    model: str
    provider: str
    quality_check_recommended: bool
    reindex_required: bool


class ProviderKeyResult(_Out):
    provider: str
    roles: list[AiModelChange]
    checked: bool


class AiModelTest(_Out):
    alias: str
    cost_usd: float | None
    detail: str | None
    latency_ms: int
    ok: bool


class SpendSlice(_Out):
    calls: int
    cost_usd: float
    key: str


class SpendDay(_Out):
    day: date
    test_usd: float
    work_usd: float


class ProviderToday(_Out):
    limit_usd: float
    provider: str
    spent_usd: float


class SpendReport(_Out):
    avg_per_lead_usd: float
    by_kind: list[SpendSlice]
    by_purpose: list[SpendSlice]
    daily_usd: float
    days: int
    leads: int
    providers: list[ProviderToday]
    series: list[SpendDay]
    today_usd: float
    total_usd: float


class AiBudgetOverrun(_Out):
    cost_usd: float
    daily_usd: float
    day: date
    system: str


class AiSpendRow(_Out):
    calls: int
    cost_usd: float
    failed_calls: int
    fallback_calls: int
    input_tokens: int
    key: str
    output_tokens: int


class AiSpendTotals(_Out):
    calls: int
    cost_usd: float
    failed_calls: int
    fallback_calls: int
    input_tokens: int
    output_tokens: int


class AiSystemBudget(_Out):
    connected: bool
    daily_usd: float
    days_over: int
    fallback_calls: int
    over_today: bool
    period_calls: int
    period_usd: float
    system: str
    today_calls: int
    today_usd: float


class AiSpendReportOut(_Out):
    date_from: date
    date_to: date
    erp_connected: bool
    fetched_at: datetime
    group: Literal["day", "system", "feature", "model"]
    overruns: list[AiBudgetOverrun]
    rows: list[AiSpendRow]
    systems: list[AiSystemBudget]
    timezone: str
    totals: AiSpendTotals
    truncated: bool


class BackupItem(_Out):
    at: datetime
    name: str
    size_bytes: int


class BackupDatabase(_Out):
    last_success_at: datetime | None
    name: str


class BackupsStatus(_Out):
    available: bool
    can_request: bool
    daemon_alive: bool
    databases: list[BackupDatabase]
    error: Literal["bucket_missing", "access_denied", "unreachable"] | None
    items: list[BackupItem]
    last_success_at: datetime | None
    request_stuck: bool
    requested_at: datetime | None
    source: Literal["volume", "rustfs"]
    stale: bool


class SystemComponent(_Out):
    checked_at: datetime | None
    expected_on_stand: bool = False
    key: str
    reason: str
    status: Literal["ok", "warn", "fail", "unknown"]
    title: str


class SystemStatus(_Out):
    checked_at: datetime
    components: list[SystemComponent]
    status: Literal["ok", "warn", "fail", "unknown"]


# --- обзор --------------------------------------------------------------------------------------


class IntegrationCard(_Out):
    key: CardKey
    status: Level
    access: Access
    note: Note
    count: int | None
    amount_usd: float | None
    last_activity_at: datetime | None


class AttentionItem(_Out):
    id: str
    card: CardKey
    severity: Severity
    kind: AttentionKind
    subject: str | None
    detail: str | None
    group: ServiceGroup | None = None
    technical: str | None = None


class IntegrationsOverview(_Out):
    checked_at: datetime
    cards: list[IntegrationCard]
    attention: list[AttentionItem]
