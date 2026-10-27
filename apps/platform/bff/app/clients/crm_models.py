# Сгенерировано apps/platform/scripts/gen_crm_models.py из packages/contracts/openapi/crm.yaml — не править руками (make -C apps/platform crm-models).

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Action(StrEnum):
    """
    Главное действие по смыслу
    """

    enter_key = "enter_key"
    enter_token = "enter_token"
    recheck = "recheck"
    reconnect = "reconnect"
    open_settings = "open_settings"
    write_owner = "write_owner"
    write_hosting = "write_hosting"
    disable_provider = "disable_provider"


class Action1(StrEnum):
    enter_key = "enter_key"
    enter_token = "enter_token"
    recheck = "recheck"
    reconnect = "reconnect"
    open_settings = "open_settings"
    write_owner = "write_owner"
    write_hosting = "write_hosting"
    disable_provider = "disable_provider"


class ActionResult(BaseModel):
    id: Annotated[int | None, Field(title="Id")] = None
    ok: Annotated[Literal[True], Field(title="Ok")] = True


class AiBudgetOverrun(BaseModel):
    cost_usd: Annotated[float, Field(title="Cost Usd")]
    daily_usd: Annotated[float, Field(title="Daily Usd")]
    day: Annotated[date, Field(title="Day")]
    system: Annotated[str, Field(title="System")]


class AiSpendReport(BaseModel):
    date_from: Annotated[date, Field(title="Date From")]
    date_to: Annotated[date, Field(title="Date To")]
    erp_connected: Annotated[bool, Field(title="Erp Connected")]
    """
    ERP ходит в шлюз: есть строки `system=erp` за период
    """
    fetched_at: Annotated[AwareDatetime, Field(title="Fetched At")]
    group: Annotated[Group, Field(title="Group")]
    overruns: Annotated[list[AiBudgetOverrun], Field(title="Overruns")]
    rows: Annotated[list[AiSpendRow], Field(title="Rows")]
    systems: Annotated[list[AiSystemBudget], Field(title="Systems")]
    timezone: Annotated[str, Field(title="Timezone")]
    totals: AiSpendTotals
    truncated: Annotated[bool, Field(title="Truncated")]
    """
    Журнал LiteLLM отдал не все строки (потолок выборки)
    """


class AiSpendRow(BaseModel):
    by_system: Annotated[list[AiSpendSystemCost], Field(title="By System")]
    calls: Annotated[int, Field(title="Calls")]
    """
    Строк журнала LiteLLM (вызовов), включая неуспешные
    """
    cost_usd: Annotated[float, Field(title="Cost Usd")]
    failed_calls: Annotated[int, Field(title="Failed Calls")]
    fallback_calls: Annotated[int, Field(title="Fallback Calls")]
    """
    Деградации: успешные вызовы через fallback-model
    """
    input_tokens: Annotated[int, Field(title="Input Tokens")]
    key: Annotated[str, Field(title="Key")]
    """
    День `YYYY-MM-DD`, система, функция или алиас — по `group`
    """
    output_tokens: Annotated[int, Field(title="Output Tokens")]


class AiSpendSystemCost(BaseModel):
    calls: Annotated[int, Field(title="Calls")]
    cost_usd: Annotated[float, Field(title="Cost Usd")]
    system: Annotated[str, Field(title="System")]
    """
    `crm`, `erp` или `other` — вызов без тега системы
    """


class AiSpendTotals(BaseModel):
    calls: Annotated[int, Field(title="Calls")]
    cost_usd: Annotated[float, Field(title="Cost Usd")]
    failed_calls: Annotated[int, Field(title="Failed Calls")]
    fallback_calls: Annotated[int, Field(title="Fallback Calls")]
    input_tokens: Annotated[int, Field(title="Input Tokens")]
    output_tokens: Annotated[int, Field(title="Output Tokens")]


class AiSystemBudget(BaseModel):
    connected: Annotated[bool, Field(title="Connected")]
    """
    За период есть вызовы с тегом этой системы
    """
    daily_usd: Annotated[float, Field(title="Daily Usd")]
    """
    Бюджет на день; 0 — без лимита
    """
    days_over: Annotated[int, Field(title="Days Over")]
    """
    Дней периода с расходом ≥ бюджета
    """
    fallback_calls: Annotated[int, Field(title="Fallback Calls")]
    over_today: Annotated[bool, Field(title="Over Today")]
    period_calls: Annotated[int, Field(title="Period Calls")]
    period_usd: Annotated[float, Field(title="Period Usd")]
    system: Annotated[str, Field(title="System")]
    today_calls: Annotated[int, Field(title="Today Calls")]
    today_usd: Annotated[float, Field(title="Today Usd")]


class BackupDatabase(BaseModel):
    last_success_at: Annotated[AwareDatetime | None, Field(title="Last Success At")]
    """
    Последняя копия базы; нет — None
    """
    name: Annotated[str, Field(title="Name")]


class BackupItem(BaseModel):
    at: Annotated[AwareDatetime, Field(title="At")]
    name: Annotated[str, Field(title="Name")]
    size_bytes: Annotated[int, Field(title="Size Bytes")]


class BackupsOut(BaseModel):
    available: Annotated[bool, Field(title="Available")]
    """
    Том бэкапов смонтирован в api / бакет `backups` читается
    """
    can_request: Annotated[bool, Field(title="Can Request")]
    """
    «Сделать сейчас» доступно (только для тома)
    """
    daemon_alive: Annotated[bool, Field(title="Daemon Alive")]
    """
    Сервис бэкапа отвечает: heartbeat свежее 2 мин
    """
    databases: Annotated[list[BackupDatabase], Field(title="Databases")]
    """
    Последняя копия по каждой базе (бакет)
    """
    error: Annotated[Error | None, Field(title="Error")]
    """
    Почему бакет не прочитан; None — прочитан
    """
    items: Annotated[list[BackupItem], Field(title="Items")]
    last_success_at: Annotated[AwareDatetime | None, Field(title="Last Success At")]
    request_stuck: Annotated[bool, Field(title="Request Stuck")]
    """
    Запрос «Сделать сейчас» старше 2 мин без новой копии — можно повторить
    """
    requested_at: Annotated[AwareDatetime | None, Field(title="Requested At")]
    """
    «Сделать сейчас» ждёт сервис бэкапа
    """
    source: Annotated[Source, Field(title="Source")]
    """
    Откуда статус: том backup-контейнера (dev) или бакет `backups` RustFS (прод)
    """
    stale: Annotated[bool, Field(title="Stale")]
    """
    Последний успешный бэкап старше 26 ч или его нет
    """


class BaseUrlSource(StrEnum):
    db = "db"
    env = "env"
    none = "none"


class BotProfileOut(BaseModel):
    profile: BotProfileSettings
    published: ProfilePublishOut | None


class BotProfileSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: LocalizedText | None = None
    """
    «Что умеет этот бот?» — видно до /start, до 512 символов
    """
    name: LocalizedText | None = None
    """
    Имя бота в Telegram, до 64 символов
    """
    short_description: LocalizedText | None = None
    """
    Краткое описание в профиле бота и при пересылке, до 120 символов
    """


class ChatCandidateOut(BaseModel):
    chat_id: Annotated[int, Field(title="Chat Id")]
    chat_type: Annotated[str, Field(title="Chat Type")]
    detected_at: Annotated[AwareDatetime, Field(title="Detected At")]
    title: Annotated[str, Field(title="Title")]


class ChecklistItem(BaseModel):
    done: Annotated[bool, Field(title="Done")]
    key: Annotated[Key, Field(title="Key")]
    link: Annotated[str, Field(title="Link")]
    unchecked: Annotated[bool | None, Field(title="Unchecked")] = False
    """
    Проверка не выполнялась: шаг не «Готово» и не «Не сделано» — «Не проверено»
    """


class ComponentStatusOut(BaseModel):
    checked_at: Annotated[AwareDatetime | None, Field(title="Checked At")]
    expected_on_stand: Annotated[bool | None, Field(title="Expected On Stand")] = False
    """
    Тестовый стенд: здесь это ожидаемо (секреты сервера, адрес CRM, бот)
    """
    key: Annotated[str, Field(title="Key")]
    reason: Annotated[str, Field(title="Reason")]
    status: Annotated[Status, Field(title="Status")]
    title: Annotated[str, Field(title="Title")]


class Created(BaseModel):
    id: Annotated[int, Field(title="Id")]


class DryRunResponse(BaseModel):
    by_code_candidate: Annotated[dict[str, int], Field(title="By Code Candidate")]
    by_code_current: Annotated[dict[str, int], Field(title="By Code Current")]
    changed: Annotated[list[DryRunRowOut], Field(title="Changed")]
    dialogs: Annotated[int, Field(title="Dialogs")]
    escalated_candidate: Annotated[int, Field(title="Escalated Candidate")]
    escalated_current: Annotated[int, Field(title="Escalated Current")]


class DryRunRowOut(BaseModel):
    at: Annotated[AwareDatetime, Field(title="At")]
    candidate: Annotated[list[str], Field(title="Candidate")]
    current: Annotated[list[str], Field(title="Current")]
    lead_id: Annotated[int, Field(title="Lead Id")]
    run_id: Annotated[int, Field(title="Run Id")]


class EmailLogItem(BaseModel):
    """
    Строка журнала писем; тела письма (временного пароля) в журнале нет.
    """

    attempts: Annotated[int, Field(title="Attempts")]
    created_at: Annotated[AwareDatetime, Field(title="Created At")]
    error: Annotated[str | None, Field(title="Error")]
    id: Annotated[int, Field(title="Id")]
    lang: Annotated[str, Field(title="Lang")]
    requested_by: Annotated[int | None, Field(title="Requested By")]
    sent_at: Annotated[AwareDatetime | None, Field(title="Sent At")]
    status: Annotated[Status1, Field(title="Status")]
    subject: Annotated[str, Field(title="Subject")]
    template: Annotated[str, Field(title="Template")]
    to_email: Annotated[str, Field(title="To Email")]
    user_id: Annotated[int | None, Field(title="User Id")]


class EmailQueuedOut(BaseModel):
    """
    Письмо поставлено в очередь: номер строки журнала, адрес получателя, статус.
    """

    email_log_id: Annotated[int, Field(title="Email Log Id")]
    status: Annotated[Status1, Field(title="Status")]
    to_email: Annotated[str, Field(title="To Email")]


class ErpCheckOut(BaseModel):
    """
    Итог «Проверить связь»: ответ ERP `GET /api/integration/v1/health` (схема `Health`) и время.

    `rate_limited` — ERP ответила 429 (лимит сервисного токена, шов 0.3.0): это статус, не ошибка;
    `retry_after_s` — через сколько секунд повторить, остальные поля пробы тогда пусты.
    """

    checked_at: Annotated[AwareDatetime, Field(title="Checked At")]
    latency_ms: Annotated[int | None, Field(title="Latency Ms")] = None
    migrations_applied: Annotated[bool | None, Field(title="Migrations Applied")] = None
    queue_alive: Annotated[bool | None, Field(title="Queue Alive")] = None
    retry_after_s: Annotated[int | None, Field(title="Retry After S")] = None
    status: Annotated[Status3, Field(title="Status")]
    version: Annotated[str | None, Field(title="Version")] = None


class ErpPairingOut(BaseModel):
    """
    Итог сопряжения или ротации: состояние коннектора и «Проверить связь», сделанная сразу после.

    Сопряжение удалось, даже если проверка не прошла: тогда `check` пуст, а `check_error` — подкод
    причины (`erp_unauthorized`, `erp_unavailable`, …) для понятной подсказки.
    """

    check: ErpCheckOut | None
    check_error: Annotated[str | None, Field(title="Check Error")]
    status: ErpStatusOut


class ErpStatusOut(BaseModel):
    """
    Коннектор «ERP» (M3-CRM-02): значения секретов не возвращаются — только «задан» и `last4`.
    """

    base_url: Annotated[str, Field(title="Base Url")]
    base_url_source: Annotated[BaseUrlSource, Field(title="Base Url Source")]
    bootstrap_available: Annotated[bool | None, Field(title="Bootstrap Available")] = (
        False
    )
    configured: Annotated[bool, Field(title="Configured")]
    inbound_token_configured: Annotated[
        bool | None, Field(title="Inbound Token Configured")
    ] = False
    inbound_token_last4: Annotated[str | None, Field(title="Inbound Token Last4")] = (
        None
    )
    mode: Annotated[Mode, Field(title="Mode")]
    paired: Annotated[bool | None, Field(title="Paired")] = False
    previous_secret_until: Annotated[
        AwareDatetime | None, Field(title="Previous Secret Until")
    ] = None
    rotation_pending: Annotated[bool | None, Field(title="Rotation Pending")] = False
    secrets_enabled: Annotated[bool, Field(title="Secrets Enabled")]
    suggested_base_url: Annotated[str | None, Field(title="Suggested Base Url")] = (
        "http://erp-backend:8000"
    )
    token_configured: Annotated[bool, Field(title="Token Configured")]
    token_last4: Annotated[str | None, Field(title="Token Last4")]
    token_source: Annotated[TokenSource, Field(title="Token Source")]
    token_updated_at: Annotated[AwareDatetime | None, Field(title="Token Updated At")]
    webhook_secret_configured: Annotated[bool, Field(title="Webhook Secret Configured")]
    webhook_secret_last4: Annotated[str | None, Field(title="Webhook Secret Last4")]
    webhook_secret_previous_configured: Annotated[
        bool, Field(title="Webhook Secret Previous Configured")
    ]
    webhook_secret_previous_last4: Annotated[
        str | None, Field(title="Webhook Secret Previous Last4")
    ]
    webhook_secret_previous_source: Annotated[
        WebhookSecretPreviousSource, Field(title="Webhook Secret Previous Source")
    ]
    webhook_secret_previous_updated_at: Annotated[
        AwareDatetime | None, Field(title="Webhook Secret Previous Updated At")
    ]
    webhook_secret_source: Annotated[
        WebhookSecretSource, Field(title="Webhook Secret Source")
    ]
    webhook_secret_updated_at: Annotated[
        AwareDatetime | None, Field(title="Webhook Secret Updated At")
    ]


class Error(StrEnum):
    """
    Почему бакет не прочитан; None — прочитан
    """

    bucket_missing = "bucket_missing"
    access_denied = "access_denied"
    unreachable = "unreachable"


class Error1(StrEnum):
    rate_limited = "rate_limited"
    telegram_error = "telegram_error"
    bot_not_running = "bot_not_running"


class ExternalServiceDetailOut(BaseModel):
    checks: Annotated[list[ServiceCheckOut], Field(title="Checks")]
    days: Annotated[list[ServiceDayOut], Field(title="Days")]
    incidents: Annotated[list[IncidentOut], Field(title="Incidents")]
    service: ExternalServiceOut


class ExternalServiceOut(BaseModel):
    action: Annotated[Action | None, Field(title="Action")]
    """
    Главное действие по смыслу
    """
    cause_key: Annotated[str, Field(title="Cause Key")]
    """
    Корень причины; у сервисов с общей причиной он общий
    """
    check: Annotated[str, Field(title="Check")]
    """
    Как проверяется — словами
    """
    checked_at: Annotated[AwareDatetime | None, Field(title="Checked At")]
    checks_24h: Annotated[int, Field(title="Checks 24H")]
    error: Annotated[str | None, Field(title="Error")]
    failures_24h: Annotated[int, Field(title="Failures 24H")]
    fix_path: Annotated[str | None, Field(title="Fix Path")]
    """
    Путь в CRM, где это исправляется
    """
    flaps_24h: Annotated[int, Field(title="Flaps 24H")]
    """
    Провалов (полос сбоя) за сутки: «Нестабильно», когда их много
    """
    frequency: Annotated[Frequency, Field(title="Frequency")]
    hint: Annotated[str | None, Field(title="Hint")]
    """
    Что сделать, если не в норме
    """
    incident: IncidentOut | None
    key: Annotated[str, Field(title="Key")]
    last_recovered_at: Annotated[AwareDatetime | None, Field(title="Last Recovered At")]
    """
    Когда восстановился после последнего сбоя за 30 дней (журнал инцидентов)
    """
    latency_ms: Annotated[int | None, Field(title="Latency Ms")]
    metrics: Annotated[dict[str, float | int | str | None], Field(title="Metrics")]
    more_actions: Annotated[list[MoreAction], Field(title="More Actions")]
    """
    Запасные действия
    """
    owner: Annotated[Owner | None, Field(title="Owner")]
    """
    Кто исправляет; нет — исправлять нечего
    """
    p95_ms_24h: Annotated[int | None, Field(title="P95 Ms 24H")]
    purpose: Annotated[str, Field(title="Purpose")]
    since: Annotated[AwareDatetime | None, Field(title="Since")]
    """
    Когда впервые обнаружено (не в порядке с …)
    """
    source: Annotated[Source1, Field(title="Source")]
    """
    Кто проверяет: CRM сама или передаёт ERP
    """
    stale: Annotated[bool, Field(title="Stale")]
    state: Annotated[State, Field(title="State")]
    """
    Состояние словом: сломано, работает с перебоями, не настроено, выключено намеренно, ожидаемо на стенде, не проверено, работает
    """
    status: Annotated[Status4, Field(title="Status")]
    summary: Annotated[str, Field(title="Summary")]
    switch: ServiceSwitchOut | None
    system: Annotated[System, Field(title="System")]
    title: Annotated[str, Field(title="Title")]
    uptime_24h: Annotated[float | None, Field(title="Uptime 24H")]
    uptime_7d: Annotated[float | None, Field(title="Uptime 7D")]


class ExternalServicesOut(BaseModel):
    checked_at: Annotated[AwareDatetime | None, Field(title="Checked At")]
    groups: Annotated[list[ServiceGroupOut], Field(title="Groups")]
    """
    Не-`ok` сервисы, свёрнутые по причине
    """
    services: Annotated[list[ExternalServiceOut], Field(title="Services")]
    stand: Annotated[bool, Field(title="Stand")]
    """
    Тестовый стенд (не прод): часть причин «ожидаема»
    """
    summary: ExternalServicesSummary


class ExternalServicesSummary(BaseModel):
    disabled: Annotated[int, Field(title="Disabled")]
    fail: Annotated[int, Field(title="Fail")]
    off: Annotated[int, Field(title="Off")]
    ok: Annotated[int, Field(title="Ok")]
    unknown: Annotated[int, Field(title="Unknown")]
    warn: Annotated[int, Field(title="Warn")]


class Frequency(StrEnum):
    minute = "minute"
    quarter = "quarter"
    erp = "erp"


class Group(StrEnum):
    day = "day"
    system = "system"
    feature = "feature"
    model = "model"


class Health(StrEnum):
    ok = "ok"
    problem = "problem"
    unknown = "unknown"


class IncidentOut(BaseModel):
    alerted: Annotated[bool, Field(title="Alerted")]
    duration_s: Annotated[int | None, Field(title="Duration S")]
    """
    Длительность закрытого инцидента, секунд
    """
    ended_at: Annotated[AwareDatetime | None, Field(title="Ended At")]
    id: Annotated[int, Field(title="Id")]
    last_error: Annotated[str | None, Field(title="Last Error")]
    recovery_alerted: Annotated[bool, Field(title="Recovery Alerted")]
    started_at: Annotated[AwareDatetime, Field(title="Started At")]
    summary: Annotated[str, Field(title="Summary")]


class KbChunkOut(BaseModel):
    content: Annotated[str, Field(title="Content")]
    heading_path: Annotated[str | None, Field(title="Heading Path")]
    id: Annotated[int, Field(title="Id")]
    position: Annotated[int, Field(title="Position")]
    token_count: Annotated[int, Field(title="Token Count")]


class KbDocumentOut(BaseModel):
    chunk_count: Annotated[int, Field(title="Chunk Count")]
    created_at: Annotated[AwareDatetime, Field(title="Created At")]
    id: Annotated[int, Field(title="Id")]
    ingest_error: Annotated[str | None, Field(title="Ingest Error")]
    ingest_status: Annotated[str, Field(title="Ingest Status")]
    is_active: Annotated[bool, Field(title="Is Active")]
    language: Annotated[str, Field(title="Language")]
    mime: Annotated[str | None, Field(title="Mime")]
    product_key: Annotated[str | None, Field(title="Product Key")]
    source_type: Annotated[str, Field(title="Source Type")]
    title: Annotated[str, Field(title="Title")]
    updated_at: Annotated[AwareDatetime, Field(title="Updated At")]
    version: Annotated[int, Field(title="Version")]


class KbGapOut(BaseModel):
    best_score: Annotated[float | None, Field(title="Best Score")]
    created_at: Annotated[AwareDatetime, Field(title="Created At")]
    id: Annotated[int, Field(title="Id")]
    language: Annotated[str, Field(title="Language")]
    lead_id: Annotated[int | None, Field(title="Lead Id")]
    occurrences: Annotated[int, Field(title="Occurrences")]
    question: Annotated[str, Field(title="Question")]
    resolved_document_id: Annotated[int | None, Field(title="Resolved Document Id")]
    status: Annotated[str, Field(title="Status")]
    updated_at: Annotated[AwareDatetime, Field(title="Updated At")]


class KbGapPage(BaseModel):
    items: Annotated[list[KbGapOut], Field(title="Items")]
    total: Annotated[int, Field(title="Total")]


class Key(StrEnum):
    company = "company"
    business_hours = "business_hours"
    models = "models"
    bot = "bot"
    channel = "channel"
    kb = "kb"
    team = "team"
    test_dialog = "test_dialog"
    erp = "erp"
    mail = "mail"
    first_employee = "first_employee"


class KeySource(StrEnum):
    crm = "crm"
    env = "env"


class Kind(StrEnum):
    vendor = "vendor"
    langfuse = "langfuse"
    mail = "mail"
    telegram = "telegram"
    erp = "erp"


class LeadSpend(BaseModel):
    calls: Annotated[int, Field(title="Calls")]
    cost_usd: Annotated[float, Field(title="Cost Usd")]
    lead_id: Annotated[int, Field(title="Lead Id")]
    lead_name: Annotated[str | None, Field(title="Lead Name")] = None


class LocalizedText(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    en: Annotated[str, Field(title="En")]
    ru: Annotated[str, Field(title="Ru")]
    uz: Annotated[str, Field(title="Uz")]


class Mode(StrEnum):
    local = "local"
    erp = "erp"


class ModelChangeResult(BaseModel):
    alias: Annotated[str, Field(title="Alias")]
    key_source: Annotated[KeySource, Field(title="Key Source")]
    model: Annotated[str, Field(title="Model")]
    provider: Annotated[str, Field(title="Provider")]
    quality_check_recommended: Annotated[bool, Field(title="Quality Check Recommended")]
    reindex_required: Annotated[bool, Field(title="Reindex Required")]


class ModelStatus(BaseModel):
    alias: Annotated[str, Field(title="Alias")]
    checked_at: Annotated[AwareDatetime | None, Field(title="Checked At")]
    health: Annotated[Health, Field(title="Health")]
    health_detail: Annotated[str | None, Field(title="Health Detail")]
    key_last4: Annotated[str | None, Field(title="Key Last4")] = None
    key_source: Annotated[KeySource | None, Field(title="Key Source")] = None
    model: Annotated[str | None, Field(title="Model")]
    provider: Annotated[str | None, Field(title="Provider")]
    today_usd: Annotated[float, Field(title="Today Usd")]


class ModelTestResult(BaseModel):
    alias: Annotated[str, Field(title="Alias")]
    cost_usd: Annotated[float | None, Field(title="Cost Usd")]
    detail: Annotated[str | None, Field(title="Detail")]
    latency_ms: Annotated[int, Field(title="Latency Ms")]
    ok: Annotated[bool, Field(title="Ok")]


class MoreAction(StrEnum):
    enter_key = "enter_key"
    enter_token = "enter_token"
    recheck = "recheck"
    reconnect = "reconnect"
    open_settings = "open_settings"
    write_owner = "write_owner"
    write_hosting = "write_hosting"
    disable_provider = "disable_provider"


class Owner(StrEnum):
    """
    Кто исправляет; нет — исправлять нечего
    """

    admin = "admin"
    owner = "owner"
    hosting = "hosting"
    provider = "provider"


class Owner1(StrEnum):
    admin = "admin"
    owner = "owner"
    hosting = "hosting"
    provider = "provider"


class PasswordReset(BaseModel):
    temporary_password: Annotated[str, Field(title="Temporary Password")]


class PasswordSource(StrEnum):
    db = "db"
    env = "env"
    none = "none"


class ProductOut(BaseModel):
    description: Annotated[str | None, Field(title="Description")]
    is_active: Annotated[bool, Field(title="Is Active")]
    key: Annotated[str, Field(title="Key")]
    name: Annotated[str, Field(title="Name")]


class ProfilePublishOut(BaseModel):
    """
    Итог последней публикации профиля в Telegram; `error` — код, текст — на фронте.
    """

    at: Annotated[AwareDatetime, Field(title="At")]
    changed: Annotated[int, Field(title="Changed")]
    error: Annotated[Error1 | None, Field(title="Error")]
    ok: Annotated[bool, Field(title="Ok")]
    retry_after: Annotated[int | None, Field(title="Retry After")]


class ProviderKeyResult(BaseModel):
    checked: Annotated[bool, Field(title="Checked")]
    """
    Провайдер сразу проверен после смены ключа
    """
    provider: Annotated[str, Field(title="Provider")]
    roles: Annotated[list[ModelChangeResult], Field(title="Roles")]


class ProviderToday(BaseModel):
    limit_usd: Annotated[float, Field(title="Limit Usd")]
    provider: Annotated[str, Field(title="Provider")]
    spent_usd: Annotated[float, Field(title="Spent Usd")]


class ReplyTemplateOut(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[int, Field(title="Id")]
    text: LocalizedText
    title: Annotated[str, Field(max_length=120, min_length=1, title="Title")]
    updated_at: Annotated[AwareDatetime, Field(title="Updated At")]


class SandboxReply(BaseModel):
    buttons: Annotated[list[str], Field(title="Buttons")]
    text: Annotated[str, Field(title="Text")]


class SandboxTurnOut(BaseModel):
    replies: Annotated[list[SandboxReply], Field(title="Replies")]
    why: SandboxWhy


class SandboxWhy(BaseModel):
    """
    Почему бот так ответил: решение, причина, документы базы знаний, сработавшие триггеры.
    """

    best_score: Annotated[float | None, Field(title="Best Score")]
    decision: Annotated[str, Field(title="Decision")]
    documents: Annotated[list[str], Field(title="Documents")]
    priority: Annotated[str | None, Field(title="Priority")]
    reason: Annotated[str | None, Field(title="Reason")]
    triggers: Annotated[list[str], Field(title="Triggers")]


class SearchHitOut(BaseModel):
    chunk_id: Annotated[int, Field(title="Chunk Id")]
    content: Annotated[str, Field(title="Content")]
    document_id: Annotated[int, Field(title="Document Id")]
    document_title: Annotated[str, Field(title="Document Title")]
    heading_path: Annotated[str | None, Field(title="Heading Path")]
    rrf_score: Annotated[float, Field(title="Rrf Score")]
    similarity: Annotated[float | None, Field(title="Similarity")]


class SearchResponse(BaseModel):
    best_score: Annotated[float | None, Field(title="Best Score")]
    confident: Annotated[bool, Field(title="Confident")]
    hits: Annotated[list[SearchHitOut], Field(title="Hits")]
    language: Annotated[str, Field(title="Language")]
    min_score: Annotated[float, Field(title="Min Score")]


class Security(StrEnum):
    starttls = "starttls"
    ssl = "ssl"
    none = "none"


class ServiceCheckOut(BaseModel):
    checked_at: Annotated[AwareDatetime, Field(title="Checked At")]
    error: Annotated[str | None, Field(title="Error")]
    latency_ms: Annotated[int | None, Field(title="Latency Ms")]
    status: Annotated[Status4, Field(title="Status")]
    summary: Annotated[str, Field(title="Summary")]
    tier: Annotated[Tier, Field(title="Tier")]


class ServiceDayOut(BaseModel):
    day: Annotated[date, Field(title="Day")]
    fail: Annotated[int, Field(title="Fail")]
    ok: Annotated[int, Field(title="Ok")]
    unknown: Annotated[int, Field(title="Unknown")]
    uptime: Annotated[float | None, Field(title="Uptime")]
    warn: Annotated[int, Field(title="Warn")]


class ServiceGroupOut(BaseModel):
    """
    Одна причина — одна строка «Требует внимания»: сервисы с общим корнем свёрнуты вместе.
    """

    action: Annotated[Action1 | None, Field(title="Action")]
    affected: Annotated[list[str], Field(title="Affected")]
    """
    Что перестало работать — функции списком
    """
    detail: Annotated[str | None, Field(title="Detail")]
    """
    Что сделать и кому передать
    """
    flaps_24h: Annotated[int, Field(title="Flaps 24H")]
    """
    Провалов за сутки по сервисам причины (наибольшее)
    """
    headline: Annotated[str, Field(title="Headline")]
    """
    Что случилось одной фразой, без сырых ответов провайдера
    """
    id: Annotated[str, Field(title="Id")]
    """
    Корень причины (`cause_key`), стабильный ключ строки
    """
    message: Annotated[str | None, Field(title="Message")]
    """
    Готовый текст владельцу или хостингу — копируется, сам не отправляется
    """
    more_actions: Annotated[list[MoreAction], Field(title="More Actions")]
    owner: Annotated[Owner1 | None, Field(title="Owner")]
    service_keys: Annotated[list[str], Field(title="Service Keys")]
    since: Annotated[AwareDatetime | None, Field(title="Since")]
    state: Annotated[State1, Field(title="State")]
    technical: Annotated[list[str], Field(title="Technical")]
    """
    Сырой текст проверки, секреты замаскированы; показывается свёрнутым
    """
    titles: Annotated[list[str], Field(title="Titles")]


class ServiceSwitchOut(BaseModel):
    """
    Выключатель сервиса: доступен ли, выключен ли вручную, что произойдёт при выключении.
    """

    available: Annotated[bool, Field(title="Available")]
    changed_at: Annotated[AwareDatetime | None, Field(title="Changed At")]
    changed_by: Annotated[str | None, Field(title="Changed By")]
    disabled: Annotated[bool, Field(title="Disabled")]
    effect: Annotated[str, Field(title="Effect")]
    kind: Annotated[Kind, Field(title="Kind")]
    problem: Annotated[str | None, Field(title="Problem")]
    reason: Annotated[str | None, Field(title="Reason")]


class SettingsResponse(BaseModel):
    schemas: Annotated[dict[str, dict[str, Any]], Field(title="Schemas")]
    values: Annotated[dict[str, dict[str, Any]], Field(title="Values")]


class SettingsSource(StrEnum):
    db = "db"
    env = "env"
    none = "none"


class SetupChecklist(BaseModel):
    done: Annotated[int, Field(title="Done")]
    items: Annotated[list[ChecklistItem], Field(title="Items")]
    total: Annotated[int, Field(title="Total")]


class SetupState(BaseModel):
    needs_setup: Annotated[bool, Field(title="Needs Setup")]


class SmtpCheckOut(BaseModel):
    """
    Итог «Проверить связь»: приветствие сервера, выполнен ли вход, время ответа.
    """

    authenticated: Annotated[bool, Field(title="Authenticated")]
    latency_ms: Annotated[int, Field(title="Latency Ms")]
    server: Annotated[str, Field(title="Server")]


class SmtpStatusOut(BaseModel):
    """
    Коннектор «Почта» (M3-CRM-08): пароль не возвращается — только «задан» и `last4`.
    """

    configured: Annotated[bool, Field(title="Configured")]
    from_email: Annotated[str, Field(title="From Email")]
    from_name: Annotated[str, Field(title="From Name")]
    host: Annotated[str, Field(title="Host")]
    password_configured: Annotated[bool, Field(title="Password Configured")]
    password_last4: Annotated[str | None, Field(title="Password Last4")]
    password_source: Annotated[PasswordSource, Field(title="Password Source")]
    password_updated_at: Annotated[
        AwareDatetime | None, Field(title="Password Updated At")
    ]
    port: Annotated[int, Field(title="Port")]
    secrets_enabled: Annotated[bool, Field(title="Secrets Enabled")]
    security: Annotated[Security, Field(title="Security")]
    settings_source: Annotated[SettingsSource, Field(title="Settings Source")]
    username: Annotated[str, Field(title="Username")]
    username_source: Annotated[UsernameSource, Field(title="Username Source")]


class Source(StrEnum):
    """
    Откуда статус: том backup-контейнера (dev) или бакет `backups` RustFS (прод)
    """

    volume = "volume"
    rustfs = "rustfs"


class Source1(StrEnum):
    """
    Кто проверяет: CRM сама или передаёт ERP
    """

    crm = "crm"
    erp = "erp"


class Source2(StrEnum):
    db = "db"
    env = "env"
    none = "none"


class SpendDay(BaseModel):
    day: Annotated[date, Field(title="Day")]
    test_usd: Annotated[float, Field(title="Test Usd")]
    work_usd: Annotated[float, Field(title="Work Usd")]


class SpendReport(BaseModel):
    avg_per_lead_usd: Annotated[float, Field(title="Avg Per Lead Usd")]
    by_kind: Annotated[list[SpendSlice], Field(title="By Kind")]
    by_purpose: Annotated[list[SpendSlice], Field(title="By Purpose")]
    daily_usd: Annotated[float, Field(title="Daily Usd")]
    days: Annotated[int, Field(title="Days")]
    leads: Annotated[int, Field(title="Leads")]
    providers: Annotated[list[ProviderToday], Field(title="Providers")]
    series: Annotated[list[SpendDay], Field(title="Series")]
    today_usd: Annotated[float, Field(title="Today Usd")]
    top_leads: Annotated[list[LeadSpend], Field(title="Top Leads")]
    total_usd: Annotated[float, Field(title="Total Usd")]


class SpendSlice(BaseModel):
    calls: Annotated[int, Field(title="Calls")]
    cost_usd: Annotated[float, Field(title="Cost Usd")]
    key: Annotated[str, Field(title="Key")]


class SsoTokenResponse(BaseModel):
    redirect_url: Annotated[str, Field(title="Redirect Url")]
    token: Annotated[str, Field(title="Token")]


class State(StrEnum):
    """
    Состояние словом: сломано, работает с перебоями, не настроено, выключено намеренно, ожидаемо на стенде, не проверено, работает
    """

    ok = "ok"
    broken = "broken"
    unstable = "unstable"
    degraded = "degraded"
    not_configured = "not_configured"
    disabled = "disabled"
    expected = "expected"
    not_checked = "not_checked"


class State1(StrEnum):
    ok = "ok"
    broken = "broken"
    unstable = "unstable"
    degraded = "degraded"
    not_configured = "not_configured"
    disabled = "disabled"
    expected = "expected"
    not_checked = "not_checked"


class Status(StrEnum):
    ok = "ok"
    warn = "warn"
    fail = "fail"
    unknown = "unknown"


class Status1(StrEnum):
    queued = "queued"
    sent = "sent"
    failed = "failed"
    skipped_no_smtp = "skipped_no_smtp"


class Status3(StrEnum):
    ok = "ok"
    degraded = "degraded"
    rate_limited = "rate_limited"


class Status4(StrEnum):
    ok = "ok"
    warn = "warn"
    fail = "fail"
    unknown = "unknown"
    off = "off"


class Status6(StrEnum):
    ok = "ok"
    warn = "warn"
    fail = "fail"
    unknown = "unknown"


class System(StrEnum):
    crm = "crm"
    erp = "erp"
    ensemble = "ensemble"


class SystemStatusOut(BaseModel):
    checked_at: Annotated[AwareDatetime, Field(title="Checked At")]
    components: Annotated[list[ComponentStatusOut], Field(title="Components")]
    status: Annotated[Status6, Field(title="Status")]


class TelegramStatusOut(BaseModel):
    """
    Значение токена сюда не попадает никогда — только `configured` и `last4`.
    """

    channel_id: Annotated[int | None, Field(title="Channel Id")]
    channel_title: Annotated[str | None, Field(title="Channel Title")]
    configured: Annotated[bool, Field(title="Configured")]
    last4: Annotated[str | None, Field(title="Last4")]
    last_error: Annotated[str | None, Field(title="Last Error")]
    mode: Annotated[str, Field(title="Mode")]
    running: Annotated[bool, Field(title="Running")]
    secrets_enabled: Annotated[bool, Field(title="Secrets Enabled")]
    source: Annotated[Source2, Field(title="Source")]
    updated_at: Annotated[AwareDatetime | None, Field(title="Updated At")]
    username: Annotated[str | None, Field(title="Username")]


class Tier(StrEnum):
    cheap = "cheap"
    heavy = "heavy"
    manual = "manual"


class TokenResponse(BaseModel):
    access_token: Annotated[str, Field(title="Access Token")]
    expires_in: Annotated[int, Field(title="Expires In")]
    must_change_password: Annotated[bool, Field(title="Must Change Password")]
    token_type: Annotated[Literal["bearer"], Field(title="Token Type")] = "bearer"


class TokenSource(StrEnum):
    db = "db"
    env = "env"
    none = "none"


class UsernameSource(StrEnum):
    db = "db"
    env = "env"
    none = "none"


class WebhookSecretPreviousSource(StrEnum):
    db = "db"
    env = "env"
    none = "none"


class WebhookSecretSource(StrEnum):
    db = "db"
    env = "env"
    none = "none"
