"""«Проверить бота» — песочница диалога в CRM без Telegram (admin, аудит 2026-10-12 §3 п. 10)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import ContainerDep, require
from app.schemas.sandbox import SandboxMessageIn, SandboxTurnOut
from app.security import audit
from app.security.principal import Principal

router = APIRouter(prefix="/api/v1/sandbox", tags=["sandbox"])

User = Annotated[Principal, Depends(require("sandbox", "use"))]


@router.post("/messages", response_model=SandboxTurnOut)
async def sandbox_message(
    body: SandboxMessageIn, who: User, container: ContainerDep
) -> SandboxTurnOut:
    """Сообщение боту от имени тестового лида админа: тот же ход, что в Telegram.

    Платно: вызовы моделей пишутся в «Расходы» с пометкой «тест». Передача менеджеру
    показывается в `why` и в CRM не создаётся; квалификатор и канал не задействуются.
    """
    turn = await container.sandbox_service.message(who.user_id, body.text, body.language)
    async with container.session_factory() as session, session.begin():
        await audit.record(
            session,
            who.actor,
            "sandbox.message",
            "sandbox",
            who.user_id,
            after={"language": body.language, "decision": turn.why.decision},
        )
    return turn


@router.post("/reset", status_code=204)
async def sandbox_reset(who: User, container: ContainerDep) -> Response:
    """«Начать заново»: тестовый диалог админа удаляется целиком."""
    await container.sandbox_service.reset(who.user_id)
    async with container.session_factory() as session, session.begin():
        await audit.record(session, who.actor, "sandbox.reset", "sandbox", who.user_id)
    return Response(status_code=204)
