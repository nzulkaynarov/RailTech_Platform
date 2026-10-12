"""«Подключения» (admin, аудит 2026-10-12 §3): Telegram-бот и канал команды из интерфейса."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import ContainerDep, require
from app.bot.supervisor import BotSupervisor
from app.integrations.telegram import AiogramProbe
from app.schemas.integrations import ChatCandidateOut, TelegramStatusOut, TelegramTokenIn
from app.schemas.leads import ActionResult
from app.security.principal import Principal
from app.services.integrations import TelegramIntegrationService

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
