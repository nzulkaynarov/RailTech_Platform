"""Мастер первого запуска и чек-лист «Настройка CRM» (scope-аудит §3 п. 9, §4)."""

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import ContainerDep, client_ip, require
from app.api.health import get_readiness
from app.api.v1.auth import respond_with_session
from app.api.v1.system_status import collect_components
from app.schemas.auth import TokenResponse
from app.schemas.setup import (
    ChecklistItem,
    ChecklistKey,
    SetupAdminRequest,
    SetupChecklist,
    SetupState,
)
from app.security.principal import Principal
from app.services import setup_checklist as checks
from app.services.auth import ClientInfo
from app.services.readiness import ReadinessService

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


@router.get("/state", response_model=SetupState)
async def get_setup_state(container: ContainerDep) -> SetupState:
    """Публично: нужен ли мастер первого запуска (в CRM ещё нет активного администратора)."""
    service = container.setup_service
    needs = await service.needs_setup()
    if needs:
        await service.ensure_code()
    return SetupState(needs_setup=needs)


@router.post("/admin", response_model=TokenResponse)
async def create_first_admin(
    body: SetupAdminRequest, request: Request, response: Response, container: ContainerDep
) -> TokenResponse:
    """Публично, один раз: код из логов api (`setup_code_issued`) → первый админ и вход.

    Неверный код — 422 `setup_code_invalid`, истёкший — `setup_code_expired`, перебор —
    `setup_locked` (15 мин); админ уже есть — 409 `setup_done`. Ответ — как у `/auth/login`.
    """
    ip = client_ip(request)
    await container.setup_service.create_admin(
        body.code, body.email, body.full_name, body.password, ip
    )
    client = ClientInfo(ip=ip, user_agent=request.headers.get("user-agent"))
    session = await container.auth_service.login(body.email, body.password, client)
    return respond_with_session(response, session, container.settings)


@router.get("/checklist", response_model=SetupChecklist)
async def get_setup_checklist(
    principal: Annotated[Principal, Depends(require("settings", "write"))],
    container: ContainerDep,
    readiness: Annotated[ReadinessService, Depends(get_readiness)],
) -> SetupChecklist:
    """Чек-лист настройки для админа: что сделано и куда идти. Без платных вызовов моделей.

    Бот и модели — из тех же проверок, что «Состояние системы» (бот = принимает сообщения).
    """
    cfg = await container.settings_service.get()
    components = await collect_components(container, readiness, datetime.now(UTC))
    models_ok, bot_running = checks.health_facts(components)
    async with container.session_factory() as session:
        saved = await checks.saved_settings(session)
        facts = checks.SetupFacts(
            company_saved="company" in saved,
            business_hours_saved="business_hours" in saved,
            models_ok=models_ok,
            bot_running=bot_running,
            channel_set=cfg.notifications.channel_id is not None,
            kb_indexed=await checks.kb_indexed(session),
            teammate_with_telegram=await checks.teammate_with_telegram(session, principal.user_id),
            lead_message_exists=await checks.lead_message_exists(session),
        )
    items = [
        ChecklistItem(key=cast(ChecklistKey, key), done=done, link=checks.LINKS[key])
        for key, done in checks.checklist(facts)
    ]
    return SetupChecklist(items=items, done=sum(i.done for i in items), total=len(items))
