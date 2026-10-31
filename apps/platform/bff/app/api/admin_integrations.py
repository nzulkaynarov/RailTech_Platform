"""Admin · Внешние интеграции (SPEC-v3 §7.6, контракт: tag `integrations`, 0.7.0).

BFF только проксирует к CRM с токеном сотрудника и проверяет раздел каталога: чтение — `admin`
от `read` (директор видит экран без кнопок), всё изменяющее и каждая проба связи — `admin: full`
(директору — 403 ещё в BFF, до CRM). Право на операцию, пароль администратора, шифрование
секретов и сами проверки решает CRM (`integrations:*`, `external_services:*`, `models:*`,
`backups:*`, `spend:read`, `system:read`). Секреты (токен бота, ключи моделей, пароль SMTP, код
сопряжения, пароль администратора) BFF только передаёт и не возвращает: у моделей ответов нет для
них полей, в ответах — маски `*_last4`.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel

from app.clients import crm_models as crm
from app.clients.crm_integrations import CrmIntegrations, fix_card_of
from app.deps import Authed, require
from app.errors import PlatformError, backend_unavailable
from app.integrations_overview import Part, Parts, build_overview
from app.schemas_integrations import (
    ActionOk,
    AiModelChange,
    AiModelChangeIn,
    AiModelList,
    AiModelTest,
    AiSpendReportOut,
    BackupsStatus,
    BotProfile,
    BotProfileState,
    CardKey,
    ErpCheck,
    ErpConnector,
    ErpPairIn,
    ErpPairing,
    ExternalService,
    ExternalServiceDetail,
    ExternalServiceList,
    IntegrationsOverview,
    MailLog,
    MailQueued,
    MailStatus,
    OffsiteBackup,
    OffsiteBackupIn,
    OffsiteCheck,
    PasswordConfirm,
    ProviderKeyIn,
    ProviderKeyResult,
    ServiceSwitchIn,
    SmtpCheck,
    SmtpConnector,
    SmtpSettingsIn,
    SpendReport,
    SystemStatus,
    TelegramChannelList,
    TelegramConnector,
    TelegramTokenIn,
    secret,
)

router = APIRouter(prefix="/admin/integrations", tags=["integrations"])

Reader = Annotated[Authed, Depends(require("admin", "read"))]
Admin = Annotated[Authed, Depends(require("admin", "full"))]
ServiceKey = Annotated[str, Path(max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
Alias = Annotated[str, Path(max_length=64)]

API = "/api/v1"


def _crm(authed: Authed) -> CrmIntegrations:
    return CrmIntegrations(authed.call)


def _to[T: BaseModel](model: type[T], source: BaseModel, **extra: Any) -> T:
    """Ответ CRM -> модель BFF: остаются только объявленные поля, остальное отбрасывается."""
    return model.model_validate({**source.model_dump(mode="json"), **extra})


def _service(source: crm.ExternalServiceOut) -> ExternalService:
    return _to(ExternalService, source, fix_card=fix_card_of(source.fix_path))


def _service_detail(source: crm.ExternalServiceDetailOut) -> ExternalServiceDetail:
    return _to(
        ExternalServiceDetail, source, service=_service(source.service).model_dump(mode="json")
    )


def _pairing(source: crm.ErpPairingOut) -> ErpPairing:
    return _to(ErpPairing, source)


# --- обзор --------------------------------------------------------------------------------------


async def _part[T: BaseModel](fetch: Callable[[], Awaitable[T]]) -> Part[T]:
    """Одна часть обзора. Нет права в CRM — `forbidden`; CRM не ответила или ответила не так —
    `unavailable`; сессия истекла — ошибка уходит наверх (401)."""
    try:
        return Part("ok", await fetch())
    except PlatformError as exc:
        if exc.status_code == 401:
            raise
        if exc.status_code == 403:
            return Part("forbidden")
        return Part("unavailable")


@router.get(
    "",
    response_model=IntegrationsOverview,
    operation_id="getIntegrationsOverview",
)
async def get_overview(authed: Reader) -> IntegrationsOverview:
    api = _crm(authed)

    async def services() -> ExternalServiceList:
        out = await api.get_model(crm.ExternalServicesOut, "GET", f"{API}/admin/external-services")
        return _services_list(out)

    async def system() -> SystemStatus:
        return _to(
            SystemStatus, await api.get_model(crm.SystemStatusOut, "GET", f"{API}/system/status")
        )

    async def erp() -> ErpConnector:
        return _to(
            ErpConnector, await api.get_model(crm.ErpStatusOut, "GET", f"{API}/integrations/erp")
        )

    async def telegram() -> TelegramConnector:
        return _to(
            TelegramConnector,
            await api.get_model(crm.TelegramStatusOut, "GET", f"{API}/integrations/telegram"),
        )

    async def models() -> AiModelList:
        return await _models(api)

    async def backups() -> BackupsStatus:
        return _to(
            BackupsStatus, await api.get_model(crm.BackupsOut, "GET", f"{API}/system/backups")
        )

    async def spend() -> SpendReport:
        return _to(
            SpendReport,
            await api.get_model(crm.SpendReport, "GET", f"{API}/spend", params={"days": 7}),
        )

    first, second = await asyncio.gather(
        asyncio.gather(_part(services), _part(system), _part(erp), _part(telegram)),
        asyncio.gather(_part(models), _part(backups), _part(spend)),
    )
    parts = Parts(
        services=first[0],
        system=first[1],
        erp=first[2],
        telegram=first[3],
        models=second[0],
        backups=second[1],
        spend=second[2],
    )
    states = {p.state for p in parts.all()}
    if "ok" not in states and "unavailable" in states:
        raise backend_unavailable("crm", "overview")
    return build_overview(parts)


def _group_card(group: crm.ServiceGroupOut, cards: dict[str, CardKey | None]) -> CardKey | None:
    """Карточка исправления группы: ключ — «Модели», токен — «Telegram», иначе по её сервисам."""
    action = group.action.value if group.action is not None else None
    if action == "enter_key":
        return "models"
    if action == "enter_token":
        return "telegram"
    return next((card for key in group.service_keys if (card := cards.get(key))), None)


def _services_list(out: crm.ExternalServicesOut) -> ExternalServiceList:
    items = [_service(s) for s in out.services]
    cards: dict[str, CardKey | None] = {s.key: s.fix_card for s in items}
    return ExternalServiceList.model_validate(
        {
            "checked_at": out.checked_at,
            "summary": out.summary.model_dump(mode="json"),
            "items": [s.model_dump(mode="json") for s in items],
            "stand": out.stand,
            "groups": [
                {**g.model_dump(mode="json"), "fix_card": _group_card(g, cards)} for g in out.groups
            ],
        }
    )


async def _models(api: CrmIntegrations) -> AiModelList:
    rows = await api.get_list(crm.ModelStatus, f"{API}/models")
    return AiModelList.model_validate({"items": [r.model_dump(mode="json") for r in rows]})


# --- ERP ----------------------------------------------------------------------------------------


@router.get("/erp", response_model=ErpConnector, operation_id="getErpConnector")
async def get_erp(authed: Reader) -> ErpConnector:
    out = await _crm(authed).get_model(crm.ErpStatusOut, "GET", f"{API}/integrations/erp")
    return _to(ErpConnector, out)


@router.post("/erp/check", response_model=ErpCheck, operation_id="checkErpConnector")
async def check_erp(authed: Admin) -> ErpCheck:
    out = await _crm(authed).get_model(
        crm.ErpCheckOut, "POST", f"{API}/integrations/erp/check", probe=True
    )
    return _to(ErpCheck, out)


@router.post("/erp/pair", response_model=ErpPairing, operation_id="pairErp")
async def pair_erp(body: ErpPairIn, authed: Admin) -> ErpPairing:
    out = await _crm(authed).get_model(
        crm.ErpPairingOut,
        "POST",
        f"{API}/integrations/erp/pair",
        json={
            "base_url": body.base_url.strip(),
            "code": secret(body.code),
            "password": secret(body.password),
        },
        probe=True,
    )
    return _pairing(out)


@router.post("/erp/rotate", response_model=ErpPairing, operation_id="rotateErpKeys")
async def rotate_erp(body: PasswordConfirm, authed: Admin) -> ErpPairing:
    out = await _crm(authed).get_model(
        crm.ErpPairingOut,
        "POST",
        f"{API}/integrations/erp/rotate",
        json={"password": secret(body.password)},
        probe=True,
    )
    return _pairing(out)


# --- Telegram -----------------------------------------------------------------------------------


@router.get("/telegram", response_model=TelegramConnector, operation_id="getTelegramConnector")
async def get_telegram(authed: Reader) -> TelegramConnector:
    out = await _crm(authed).get_model(crm.TelegramStatusOut, "GET", f"{API}/integrations/telegram")
    return _to(TelegramConnector, out)


@router.put("/telegram/token", response_model=TelegramConnector, operation_id="setTelegramToken")
async def set_telegram_token(body: TelegramTokenIn, authed: Admin) -> TelegramConnector:
    out = await _crm(authed).get_model(
        crm.TelegramStatusOut,
        "PUT",
        f"{API}/integrations/telegram/token",
        json={"token": secret(body.token), "password": secret(body.password)},
        probe=True,
    )
    return _to(TelegramConnector, out)


@router.get(
    "/telegram/channels", response_model=TelegramChannelList, operation_id="listTelegramChannels"
)
async def list_telegram_channels(authed: Reader) -> TelegramChannelList:
    rows = await _crm(authed).get_list(
        crm.ChatCandidateOut, f"{API}/integrations/telegram/channels"
    )
    return TelegramChannelList.model_validate({"items": [r.model_dump(mode="json") for r in rows]})


@router.post(
    "/telegram/channels/{chat_id}/connect",
    response_model=ActionOk,
    operation_id="connectTelegramChannel",
)
async def connect_telegram_channel(chat_id: int, authed: Admin) -> ActionOk:
    out = await _crm(authed).get_model(
        crm.ActionResult,
        "POST",
        f"{API}/integrations/telegram/channels/{chat_id}/connect",
        probe=True,
    )
    return _to(ActionOk, out)


@router.post("/telegram/channel/test", response_model=ActionOk, operation_id="testTelegramChannel")
async def test_telegram_channel(authed: Admin) -> ActionOk:
    out = await _crm(authed).get_model(
        crm.ActionResult, "POST", f"{API}/integrations/telegram/channel/test", probe=True
    )
    return _to(ActionOk, out)


@router.get("/telegram/profile", response_model=BotProfileState, operation_id="getBotProfile")
async def get_bot_profile(authed: Reader) -> BotProfileState:
    out = await _crm(authed).get_model(
        crm.BotProfileOut, "GET", f"{API}/integrations/telegram/profile"
    )
    return _to(BotProfileState, out)


@router.put("/telegram/profile", response_model=BotProfileState, operation_id="saveBotProfile")
async def save_bot_profile(body: BotProfile, authed: Admin) -> BotProfileState:
    out = await _crm(authed).get_model(
        crm.BotProfileOut,
        "PUT",
        f"{API}/integrations/telegram/profile",
        json=body.model_dump(),
        probe=True,
    )
    return _to(BotProfileState, out)


# --- Внешняя копия бэкапов (OPS-GDRIVE-2) -------------------------------------------------------


@router.get("/offsite", response_model=OffsiteBackup, operation_id="getOffsiteBackup")
async def get_offsite(authed: Reader) -> OffsiteBackup:
    out = await _crm(authed).get_model(crm.OffsiteStatusOut, "GET", f"{API}/integrations/offsite")
    return _to(OffsiteBackup, out)


@router.put("/offsite", response_model=OffsiteBackup, operation_id="saveOffsiteBackup")
async def save_offsite(body: OffsiteBackupIn, authed: Admin) -> OffsiteBackup:
    """Ключ Google и пароль приложения Яндекса — только на запись: уходят в CRM и не возвращаются.
    Поля другого провайдера в CRM не передаются."""
    fields: dict[str, Any] = (
        {
            "provider": "yandex",
            "login": body.login.strip(),
            "folder_path": body.folder_path.strip(),
            "app_password": secret(body.app_password),
        }
        if body.provider == "yandex"
        else {"key_json": secret(body.key_json), "folder_id": body.folder_id.strip()}
    )
    out = await _crm(authed).get_model(
        crm.OffsiteStatusOut,
        "PUT",
        f"{API}/integrations/offsite",
        json={**fields, "password": secret(body.password)},
        probe=True,
    )
    return _to(OffsiteBackup, out)


@router.post("/offsite/check", response_model=OffsiteCheck, operation_id="checkOffsiteBackup")
async def check_offsite(authed: Admin) -> OffsiteCheck:
    out = await _crm(authed).get_model(
        crm.OffsiteCheckOut, "POST", f"{API}/integrations/offsite/check", probe=True
    )
    return _to(OffsiteCheck, out)


# --- Почта --------------------------------------------------------------------------------------


@router.get("/smtp", response_model=SmtpConnector, operation_id="getSmtpConnector")
async def get_smtp(authed: Reader) -> SmtpConnector:
    out = await _crm(authed).get_model(crm.SmtpStatusOut, "GET", f"{API}/integrations/smtp")
    return _to(SmtpConnector, out)


@router.put("/smtp", response_model=SmtpConnector, operation_id="saveSmtpConnector")
async def save_smtp(body: SmtpSettingsIn, authed: Admin) -> SmtpConnector:
    out = await _crm(authed).get_model(
        crm.SmtpStatusOut,
        "PUT",
        f"{API}/integrations/smtp",
        json={
            "host": body.host.strip(),
            "port": body.port,
            "security": body.security,
            "from_email": body.from_email.strip(),
            "from_name": body.from_name.strip(),
            "username": body.username,
            "smtp_password": secret(body.smtp_password),
            "password": secret(body.password),
        },
    )
    return _to(SmtpConnector, out)


@router.post("/smtp/check", response_model=SmtpCheck, operation_id="checkSmtp")
async def check_smtp(authed: Admin) -> SmtpCheck:
    out = await _crm(authed).get_model(
        crm.SmtpCheckOut, "POST", f"{API}/integrations/smtp/check", probe=True
    )
    return _to(SmtpCheck, out)


@router.post("/smtp/test-send", response_model=MailQueued, operation_id="sendSmtpTest")
async def send_smtp_test(authed: Admin) -> MailQueued:
    out = await _crm(authed).get_model(
        crm.EmailQueuedOut, "POST", f"{API}/integrations/smtp/test-send", probe=True
    )
    return _to(MailQueued, out)


@router.get("/smtp/log", response_model=MailLog, operation_id="listMailLog")
async def list_mail_log(
    authed: Reader,
    status: Annotated[MailStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MailLog:
    params: dict[str, Any] = {"limit": limit}
    if status is not None:
        params["status"] = status
    rows = await _crm(authed).get_list(
        crm.EmailLogItem, f"{API}/integrations/smtp/log", params=params
    )
    return MailLog.model_validate({"items": [r.model_dump(mode="json") for r in rows]})


# --- Внешние сервисы ----------------------------------------------------------------------------


@router.get("/services", response_model=ExternalServiceList, operation_id="listExternalServices")
async def list_services(authed: Reader) -> ExternalServiceList:
    out = await _crm(authed).get_model(
        crm.ExternalServicesOut, "GET", f"{API}/admin/external-services"
    )
    return _services_list(out)


@router.get(
    "/services/{key}", response_model=ExternalServiceDetail, operation_id="getExternalService"
)
async def get_service(key: ServiceKey, authed: Reader) -> ExternalServiceDetail:
    out = await _crm(authed).get_model(
        crm.ExternalServiceDetailOut, "GET", f"{API}/admin/external-services/{key}"
    )
    return _service_detail(out)


@router.post(
    "/services/{key}/check",
    response_model=ExternalServiceDetail,
    operation_id="checkExternalService",
)
async def check_service(key: ServiceKey, authed: Admin) -> ExternalServiceDetail:
    out = await _crm(authed).get_model(
        crm.ExternalServiceDetailOut,
        "POST",
        f"{API}/admin/external-services/{key}/check",
        probe=True,
    )
    return _service_detail(out)


@router.post(
    "/services/{key}/disable", response_model=ExternalService, operation_id="disableExternalService"
)
async def disable_service(key: ServiceKey, body: ServiceSwitchIn, authed: Admin) -> ExternalService:
    out = await _crm(authed).get_model(
        crm.ExternalServiceOut,
        "POST",
        f"{API}/admin/external-services/{key}/disable",
        json={"password": secret(body.password), "reason": body.reason},
        probe=True,
    )
    return _service(out)


@router.post(
    "/services/{key}/enable", response_model=ExternalService, operation_id="enableExternalService"
)
async def enable_service(key: ServiceKey, body: PasswordConfirm, authed: Admin) -> ExternalService:
    out = await _crm(authed).get_model(
        crm.ExternalServiceOut,
        "POST",
        f"{API}/admin/external-services/{key}/enable",
        json={"password": secret(body.password)},
        probe=True,
    )
    return _service(out)


# --- Модели ИИ ----------------------------------------------------------------------------------


@router.get("/models", response_model=AiModelList, operation_id="listAiModels")
async def list_models(authed: Reader) -> AiModelList:
    return await _models(_crm(authed))


@router.put("/models/{alias}", response_model=AiModelChange, operation_id="changeAiModel")
async def change_model(alias: Alias, body: AiModelChangeIn, authed: Admin) -> AiModelChange:
    out = await _crm(authed).get_model(
        crm.ModelChangeResult,
        "PUT",
        f"{API}/models/{alias}",
        json={
            "provider": body.provider,
            "model": body.model.strip(),
            "api_key": secret(body.api_key),
            "api_base": body.api_base,
            "password": secret(body.password),
        },
        probe=True,
    )
    return _to(AiModelChange, out)


@router.put(
    "/models/providers/{provider}/key",
    response_model=ProviderKeyResult,
    operation_id="changeProviderKey",
)
async def change_provider_key(
    provider: Annotated[Literal["anthropic", "gemini", "openai"], Path()],
    body: ProviderKeyIn,
    authed: Admin,
) -> ProviderKeyResult:
    out = await _crm(authed).get_model(
        crm.ProviderKeyResult,
        "PUT",
        f"{API}/models/providers/{provider}/key",
        json={"api_key": secret(body.api_key), "password": secret(body.password)},
        probe=True,
    )
    return _to(ProviderKeyResult, out)


@router.post("/models/{alias}/reset", response_model=AiModelChange, operation_id="resetAiModel")
async def reset_model(alias: Alias, body: PasswordConfirm, authed: Admin) -> AiModelChange:
    out = await _crm(authed).get_model(
        crm.ModelChangeResult,
        "POST",
        f"{API}/models/{alias}/reset",
        json={"password": secret(body.password)},
        probe=True,
    )
    return _to(AiModelChange, out)


@router.post("/models/{alias}/test", response_model=AiModelTest, operation_id="testAiModel")
async def test_model(alias: Alias, authed: Admin) -> AiModelTest:
    out = await _crm(authed).get_model(
        crm.ModelTestResult, "POST", f"{API}/models/{alias}/test", probe=True
    )
    return _to(AiModelTest, out)


# --- Расходы ------------------------------------------------------------------------------------


@router.get("/spend", response_model=SpendReport, operation_id="getSpendReport")
async def get_spend(authed: Reader, days: Annotated[int, Query(ge=1, le=180)] = 30) -> SpendReport:
    out = await _crm(authed).get_model(
        crm.SpendReport, "GET", f"{API}/spend", params={"days": days}
    )
    return _to(SpendReport, out)


@router.get("/ai-spend", response_model=AiSpendReportOut, operation_id="getAiSpendReport")
async def get_ai_spend(
    authed: Reader,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
    group: Annotated[Literal["day", "system", "feature", "model"], Query()] = "day",
) -> AiSpendReportOut:
    params: dict[str, Any] = {"group": group}
    if from_ is not None:
        params["from"] = from_.isoformat()
    if to is not None:
        params["to"] = to.isoformat()
    out = await _crm(authed).get_model(
        crm.AiSpendReport, "GET", f"{API}/admin/ai-spend", params=params, probe=True
    )
    return _to(AiSpendReportOut, out)


# --- Хранилище, бэкапы, состояние системы -------------------------------------------------------


@router.get("/backups", response_model=BackupsStatus, operation_id="getBackups")
async def get_backups(authed: Reader) -> BackupsStatus:
    out = await _crm(authed).get_model(crm.BackupsOut, "GET", f"{API}/system/backups")
    return _to(BackupsStatus, out)


@router.post(
    "/backups", response_model=BackupsStatus, status_code=202, operation_id="requestBackup"
)
async def request_backup(authed: Admin) -> BackupsStatus:
    out = await _crm(authed).get_model(
        crm.BackupsOut, "POST", f"{API}/system/backups", expected=202
    )
    return _to(BackupsStatus, out)


@router.get("/system", response_model=SystemStatus, operation_id="getSystemStatus")
async def get_system(authed: Reader) -> SystemStatus:
    out = await _crm(authed).get_model(crm.SystemStatusOut, "GET", f"{API}/system/status")
    return _to(SystemStatus, out)
