from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import ContainerDep, require
from app.bot.profile import ProfilePublish
from app.integrations.erp import ErpRateLimited
from app.integrations.telegram import AiogramProbe
from app.schemas.integrations import (
    BotProfileOut,
    ChatCandidateOut,
    EmailLogItem,
    EmailQueuedOut,
    EmailStatus,
    ErpCheckOut,
    ErpConnectorIn,
    ErpPairIn,
    ErpPairingOut,
    ErpRotateIn,
    ErpStatusOut,
    OffsiteCheckOut,
    OffsiteConnectorIn,
    OffsiteStatusOut,
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
from app.services.erp_pairing import ErpPairingService, PairingOutcome
from app.services.integrations import TelegramIntegrationService
from app.services.mail import EmailLogView
from app.services.offsite_connector import OffsiteConnectorService, OffsiteStatus
from app.services.smtp_connector import SmtpConnectorService

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])

Reader = Annotated[Principal, Depends(require("integrations", "read"))]
Writer = Annotated[Principal, Depends(require("integrations", "write"))]


def get_service(request: Request, container: ContainerDep) -> TelegramIntegrationService:
    """Пробу Telegram тесты подменяют через `app.state.telegram_probe`.

    Бот живёт в `crm-bot`; сервис говорит с ним через БД (`container.bot_state`, S0-4).
    """
    probe = getattr(request.app.state, "telegram_probe", None) or AiogramProbe(container.settings)
    return TelegramIntegrationService(
        container.session_factory,
        container.settings_service,
        container.secrets_store,
        probe,
        container.bot_state,
        container.telegram_bot,
        mode=container.settings.telegram_mode,
        restart_wait_s=container.settings.bot_restart_wait_s,
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

    Ротация секрета вебхуков без простоя: `webhook_secret` — новый (текущий),
    `webhook_secret_previous` — прежний (принимается, пока его не сняли
    `clear_webhook_secret_previous: true`).

    Ошибки: `erp_invalid_url` (422, поле `base_url`), `wrong_password` (422),
    `secrets_key_missing` (409 — секреты нельзя сохранить без `SECRETS_KEY`).
    """
    token = body.service_token.get_secret_value() if body.service_token is not None else None
    webhook = body.webhook_secret.get_secret_value() if body.webhook_secret is not None else None
    previous = (
        body.webhook_secret_previous.get_secret_value()
        if body.webhook_secret_previous is not None
        else None
    )
    status = await service.save(
        who,
        base_url=body.base_url,
        service_token=token,
        webhook_secret=webhook,
        webhook_secret_previous=previous,
        clear_webhook_secret_previous=body.clear_webhook_secret_previous,
        password=body.password.get_secret_value(),
    )
    return _erp_out(status)


@router.post("/erp/check", response_model=ErpCheckOut)
async def check_erp_connection(_: Writer, service: ErpDep) -> ErpCheckOut:
    """«Проверить связь»: `GET {base_url}/api/integration/v1/health` с сервисным токеном, 5 с.

    Ошибки (ADR-0017, `details.reason`): `erp_not_configured` (409), `erp_invalid_url` (422),
    `erp_unauthorized` / `erp_unavailable` / `erp_bad_response` (502). Лимит частоты ERP (429) — не
    ошибка: `status: "rate_limited"` и `retry_after_s` (пауза из `Retry-After`).
    """
    result = await service.check()
    if isinstance(result, ErpRateLimited):
        return ErpCheckOut(
            status="rate_limited", checked_at=result.checked_at, retry_after_s=result.retry_after_s
        )
    return ErpCheckOut(**asdict(result))


def get_erp_pairing(container: ContainerDep) -> ErpPairingService:
    return container.erp_pairing


ErpPairingDep = Annotated[ErpPairingService, Depends(get_erp_pairing)]


def _pairing_out(outcome: PairingOutcome) -> ErpPairingOut:
    check = ErpCheckOut(**asdict(outcome.check)) if outcome.check is not None else None
    return ErpPairingOut(
        status=_erp_out(outcome.status), check=check, check_error=outcome.check_error
    )


@router.post("/erp/pair", response_model=ErpPairingOut)
async def pair_erp(body: ErpPairIn, who: Writer, service: ErpPairingDep) -> ErpPairingOut:
    """«Подключить ERP»: адрес ERP и одноразовый код из её настроек (M3-CRM-10, CONTRACTS §2).

    CRM сама генерирует токены обоих направлений и секрет вебхуков, передаёт их ERP по коду,
    сохраняет зашифрованными и сразу делает «Проверить связь» (результат — в ответе). Пароль
    админа обязателен.

    Ошибки (`details.reason`): `erp_invalid_url` (422, поле `base_url`),
    `erp_pairing_code_invalid` / `erp_pairing_code_expired` / `erp_pairing_code_used` (422, поле
    `code`), `wrong_password` (422), `secrets_key_missing` (409), `erp_unavailable` /
    `erp_bad_response` / `erp_pairing_unsupported` (502).
    """
    return _pairing_out(
        await service.pair(
            who,
            base_url=body.base_url,
            code=body.code.get_secret_value() if body.code is not None else None,
            password=body.password.get_secret_value(),
        )
    )


@router.post("/erp/rotate", response_model=ErpPairingOut)
async def rotate_erp_keys(body: ErpRotateIn, who: Writer, service: ErpPairingDep) -> ErpPairingOut:
    """«Обновить ключи»: CRM генерирует новую тройку секретов, ERP принимает её по токену.

    Прежний токен CRM→ERP остаётся у ERP активным на переходный период (два активных), затем
    гаснет сам; предыдущий секрет вебхуков CRM принимает наравне с новым и снимает по истечении
    срока перехода.

    Ошибки: `erp_not_configured` (409), `secrets_key_missing` (409), `wrong_password` (422),
    `erp_unauthorized` / `erp_unavailable` / `erp_bad_response` (502).
    """
    return _pairing_out(await service.rotate(who, password=body.password.get_secret_value()))


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
    """Журнал доставки почты ансамбля: последние `limit`, фильтр по статусу; источник (CRM, ERP,
    EDS) и назначение письма; тел писем в журнале нет (W18A-P1)."""
    rows = await container.mail_service.list_log(status, limit)
    return [EmailLogItem.model_validate(asdict(row)) for row in rows]


def get_offsite_service(container: ContainerDep) -> OffsiteConnectorService:
    return container.offsite_connector


OffsiteDep = Annotated[OffsiteConnectorService, Depends(get_offsite_service)]


def offsite_out(status: OffsiteStatus) -> OffsiteStatusOut:
    return OffsiteStatusOut.model_validate(asdict(status))


@router.get("/offsite", response_model=OffsiteStatusOut)
async def get_offsite_status(_: Reader, service: OffsiteDep) -> OffsiteStatusOut:
    """Внешняя копия бэкапов на Google Drive (OPS-GDRIVE-2): папка, адрес сервисного аккаунта,
    последние символы ID ключа, доставка сервису копирования, итог последней проверки. Ключ не
    возвращается никогда. Состояние самой копии — строка `offsite_backup` внешних сервисов."""
    return offsite_out(await service.status())


@router.put("/offsite", response_model=OffsiteStatusOut)
async def put_offsite_connector(
    body: OffsiteConnectorIn, who: Writer, service: OffsiteDep
) -> OffsiteStatusOut:
    """Сохранить ключ сервисного аккаунта и папку (после пароля админа) и сразу проверить у Google.

    Ключ доставляется сервису копирования (бакет `offsite-config`, у CRM — только запись) и
    хранится зашифрованным; `key_json = null` — оставить прежний. Итог проверки — `last_check`.
    Ошибки: `offsite_key_invalid` (422, `key_json`; `details.problem`: `not_json`,
    `not_service_account`, `missing_fields`), `offsite_folder_invalid` (422, `folder_id`),
    `wrong_password` (422), `secrets_key_missing` (409), `offsite_delivery_failed` (502).
    """
    secret = body.key_json.get_secret_value() if body.key_json is not None else None
    status = await service.save(
        who,
        key_json=secret,
        folder_id=body.folder_id,
        admin_password=body.password.get_secret_value(),
    )
    return offsite_out(status)


@router.post("/offsite/check", response_model=OffsiteCheckOut)
async def check_offsite_connector(who: Writer, service: OffsiteDep) -> OffsiteCheckOut:
    """«Проверить»: ключ из хранилища → токен Google → папка (общий диск, право добавлять файлы).

    Ничего не пишет на Drive. Итог — 200 с `reason`; ошибка: `offsite_not_configured` (409).
    """
    return OffsiteCheckOut.model_validate(asdict(await service.check(who)))
