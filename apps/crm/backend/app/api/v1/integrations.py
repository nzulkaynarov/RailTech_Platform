"""«Подключения» (admin, аудит 2026-10-12 §3): бот, канал команды, коннекторы ERP и «Почта»."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import ContainerDep, require
from app.bot.profile import ProfilePublish
from app.bot.supervisor import BotSupervisor
from app.integrations.telegram import AiogramProbe
from app.schemas.integrations import (
    BotProfileOut,
    ChatCandidateOut,
    EmailLogItem,
    EmailQueuedOut,
    EmailStatus,
    ErpCheckOut,
    ErpConnectorIn,
    ErpStatusOut,
    ProfilePublishOut,
    SmtpCheckOut,
    SmtpConnectorIn,
    SmtpStatusOut,
    TelegramStatusOut,
    TelegramTokenIn,
)
from app.schemas.leads import ActionResult
from app.schemas.settings_profile import BotProfileSettings
from app.security.principal import Principal
from app.security.reauth import LockoutPolicy
from app.services.erp_connector import ErpConnectorService, ErpStatus
from app.services.integrations import TelegramIntegrationService
from app.services.mail import EmailLogView
from app.services.smtp_connector import SmtpConnectorService

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])

Reader = Annotated[Principal, Depends(require("integrations", "read"))]
Writer = Annotated[Principal, Depends(require("integrations", "write"))]


def get_service(request: Request, container: ContainerDep) -> TelegramIntegrationService:
    """Пробу Telegram тесты подменяют через `app.state.telegram_probe`."""
    supervisor: BotSupervisor | None = getattr(request.app.state, "bot", None)
    probe = getattr(request.app.state, "telegram_probe", None) or AiogramProbe()
    return TelegramIntegrationService(
        container.session_factory,
        container.settings_service,
        container.secrets_store,
        probe,
        supervisor if isinstance(supervisor, BotSupervisor) else None,
        container.telegram_bot,
        mode=container.settings.telegram_mode,
        lockout=LockoutPolicy(
            container.settings.login_max_failures, container.settings.login_lockout_minutes
        ),
    )


ServiceDep = Annotated[TelegramIntegrationService, Depends(get_service)]


@router.get("/telegram", response_model=TelegramStatusOut)
async def get_telegram_status(_: Reader, service: ServiceDep) -> TelegramStatusOut:
    return TelegramStatusOut(**asdict(await service.status()))


@router.put("/telegram/token", response_model=TelegramStatusOut)
async def put_telegram_token(
    body: TelegramTokenIn, who: Writer, service: ServiceDep
) -> TelegramStatusOut:
    """Проверить токен в Telegram (`getMe`), сохранить зашифрованным, перезапустить бота."""
    await service.save_token(who, body.token.get_secret_value(), body.password.get_secret_value())
    return TelegramStatusOut(**asdict(await service.status()))


def _profile_out(profile: BotProfileSettings, result: ProfilePublish | None) -> BotProfileOut:
    published = ProfilePublishOut(**asdict(result)) if result is not None else None
    return BotProfileOut(profile=profile, published=published)


@router.get("/telegram/profile", response_model=BotProfileOut)
async def get_telegram_profile(_: Reader, service: ServiceDep) -> BotProfileOut:
    """Имя, описание и краткое описание бота (ru/uz/en) и статус публикации в Telegram."""
    return _profile_out(*await service.profile())


@router.put("/telegram/profile", response_model=BotProfileOut)
async def put_telegram_profile(
    body: BotProfileSettings, who: Writer, service: ServiceDep
) -> BotProfileOut:
    """Сохранить профиль бота и опубликовать изменения в Telegram (setMyName и т. п.)."""
    return _profile_out(*await service.save_profile(who, body))


@router.get("/telegram/channels", response_model=list[ChatCandidateOut])
async def list_telegram_channels(_: Reader, service: ServiceDep) -> list[ChatCandidateOut]:
    return [ChatCandidateOut(**asdict(c)) for c in await service.candidates()]


@router.post("/telegram/channels/{chat_id}/connect", response_model=ActionResult)
async def connect_telegram_channel(chat_id: int, who: Writer, service: ServiceDep) -> ActionResult:
    await service.connect_channel(who, chat_id)
    return ActionResult()


@router.post("/telegram/channel/test", response_model=ActionResult)
async def send_telegram_channel_test(_: Writer, service: ServiceDep) -> ActionResult:
    await service.send_test()
    return ActionResult()


def get_erp_service(container: ContainerDep) -> ErpConnectorService:
    return container.erp_connector


ErpDep = Annotated[ErpConnectorService, Depends(get_erp_service)]


def _erp_out(status: ErpStatus) -> ErpStatusOut:
    return ErpStatusOut(**{**asdict(status), "mode": status.mode.value})


@router.get("/erp", response_model=ErpStatusOut)
async def get_erp_status(_: Reader, service: ErpDep) -> ErpStatusOut:
    """Коннектор «ERP» (ADR-0018, ADR-0022): адрес, откуда взяты секреты, режим жизненного цикла.

    Значения сервисного токена и секрета вебхуков не возвращаются — только «задан» и `last4`.
    """
    return _erp_out(await service.status())


@router.put("/erp", response_model=ErpStatusOut)
async def put_erp_connector(body: ErpConnectorIn, who: Writer, service: ErpDep) -> ErpStatusOut:
    """Сохранить адрес ERP и секреты (после пароля админа); секрет `null` — оставить прежний.

    Ошибки: `erp_invalid_url` (422, поле `base_url`), `wrong_password` (422),
    `secrets_key_missing` (409 — секреты нельзя сохранить без `SECRETS_KEY`).
    """
    token = body.service_token.get_secret_value() if body.service_token is not None else None
    webhook = body.webhook_secret.get_secret_value() if body.webhook_secret is not None else None
    status = await service.save(
        who,
        base_url=body.base_url,
        service_token=token,
        webhook_secret=webhook,
        password=body.password.get_secret_value(),
    )
    return _erp_out(status)


@router.post("/erp/check", response_model=ErpCheckOut)
async def check_erp_connection(_: Writer, service: ErpDep) -> ErpCheckOut:
    """«Проверить связь»: `GET {base_url}/api/integration/v1/health` с сервисным токеном, 5 с.

    Ошибки (ADR-0017, `details.reason`): `erp_not_configured` (409), `erp_invalid_url` (422),
    `erp_unauthorized` / `erp_unavailable` / `erp_bad_response` (502).
    """
    return ErpCheckOut(**asdict(await service.check()))


def get_smtp_service(container: ContainerDep) -> SmtpConnectorService:
    return container.smtp_connector


SmtpDep = Annotated[SmtpConnectorService, Depends(get_smtp_service)]


def queued_out(view: EmailLogView) -> EmailQueuedOut:
    return EmailQueuedOut.model_validate(
        {"email_log_id": view.id, "to_email": view.to_email, "status": view.status}
    )


@router.get("/smtp", response_model=SmtpStatusOut)
async def get_smtp_status(_: Reader, service: SmtpDep) -> SmtpStatusOut:
    """Коннектор «Почта» (M3-CRM-08, ADR-0018): релей SMTP для писем сотрудникам.

    Пароль SMTP не возвращается — только «задан», источник и `last4`. Коннектор «настроен» =
    есть хост и адрес отправителя (из «Подключений», иначе `SMTP_*` в `.env`).
    """
    return SmtpStatusOut(**asdict(await service.status()))


@router.put("/smtp", response_model=SmtpStatusOut)
async def put_smtp_connector(body: SmtpConnectorIn, who: Writer, service: SmtpDep) -> SmtpStatusOut:
    """Сохранить релей и секреты (после пароля админа); логин/пароль `null` — оставить прежние.

    Ошибки: `smtp_invalid_host` (422, поле `host`), `invalid_email` (422, `from_email`),
    `wrong_password` (422), `secrets_key_missing` (409 — секреты не сохранить без `SECRETS_KEY`).
    """
    secret = body.smtp_password.get_secret_value() if body.smtp_password is not None else None
    status = await service.save(
        who,
        host=body.host,
        port=body.port,
        security=body.security,
        from_email=body.from_email,
        from_name=body.from_name,
        username=body.username,
        password=secret,
        admin_password=body.password.get_secret_value(),
    )
    return SmtpStatusOut(**asdict(status))


@router.post("/smtp/check", response_model=SmtpCheckOut)
async def check_smtp_connection(_: Writer, service: SmtpDep) -> SmtpCheckOut:
    """«Проверить связь»: соединение, EHLO, STARTTLS/SMTPS и AUTH без отправки письма, 10 с.

    Ошибки (ADR-0017, `details.reason`): `smtp_not_configured` (409), `smtp_invalid_host` (422),
    `smtp_unavailable` / `smtp_tls_failed` / `smtp_auth_failed` (502).
    """
    return SmtpCheckOut(**asdict(await service.check()))


@router.post("/smtp/test-send", response_model=EmailQueuedOut)
async def send_smtp_test(who: Writer, service: SmtpDep) -> EmailQueuedOut:
    """Тестовое письмо на адрес самого администратора — через журнал и очередь, как настоящее.

    Ошибки: `smtp_not_configured` (409), `secrets_key_missing` (409). Итог доставки — в журнале.
    """
    return queued_out(await service.test_send(who))


@router.get("/smtp/log", response_model=list[EmailLogItem])
async def list_email_log(
    _: Reader,
    container: ContainerDep,
    status: EmailStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[EmailLogItem]:
    """Журнал писем сотрудникам: последние `limit`, фильтр по статусу; тел писем в журнале нет."""
    rows = await container.mail_service.list_log(status, limit)
    return [EmailLogItem.model_validate(asdict(row)) for row in rows]
