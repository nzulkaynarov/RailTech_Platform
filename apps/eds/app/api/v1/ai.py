"""ИИ-помощник регистрации и настройки документооборота (eds.yaml: `/letter-intake`, `/ai-suggestions/{id}/decision`,
`/docflow-settings`; EDS-REG). Правила — `services/letter_intake.py`, `services/docflow_settings.py`."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_container, get_session, get_storage, require_permission
from app.container import Container
from app.models import Employee
from app.schemas.ai import AiDecisionIn, DocflowSettings, DocflowSettingsPatch, LetterIntakeIn, LetterIntakeSuggestion
from app.security.permissions import EdsPermission as P
from app.services import docflow_settings, letter_intake
from app.services.storage import ObjectStorage

router = APIRouter(prefix="/api/v1", tags=["letters"])

Registrar = Annotated[Employee, Depends(require_permission(P.LETTERS_REGISTER))]
SettingsReader = Annotated[Employee, Depends(require_permission(P.LETTERS_REGISTER, P.BUS_MANAGE))]
Admin = Annotated[Employee, Depends(require_permission(P.BUS_MANAGE))]
Session = Annotated[AsyncSession, Depends(get_session)]
Storage = Annotated[ObjectStorage, Depends(get_storage)]
Box = Annotated[Container, Depends(get_container)]


@router.post("/letter-intake", response_model=LetterIntakeSuggestion, operation_id="suggestLetterFromFile")
async def suggest_letter_from_file(
    body: LetterIntakeIn, employee: Registrar, session: Session, storage: Storage, box: Box
) -> LetterIntakeSuggestion:
    return await letter_intake.suggest(session, box.settings, storage, employee, body.file_id)


@router.post(
    "/ai-suggestions/{suggestion_id}/decision",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="decideAiSuggestion",
)
async def decide_ai_suggestion(
    suggestion_id: uuid.UUID, body: AiDecisionIn, employee: Registrar, session: Session
) -> Response:
    async with session.begin():
        await letter_intake.decide(session, employee, suggestion_id, body.decision)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/docflow-settings", response_model=DocflowSettings, operation_id="getDocflowSettings")
async def get_docflow_settings(_: SettingsReader, session: Session, box: Box) -> DocflowSettings:
    return await docflow_settings.read(session, box.settings)


@router.patch("/docflow-settings", response_model=DocflowSettings, operation_id="updateDocflowSettings")
async def update_docflow_settings(
    body: DocflowSettingsPatch, admin: Admin, session: Session, box: Box
) -> DocflowSettings:
    async with session.begin():
        return await docflow_settings.update(
            session, box.settings, actor_id=admin.crm_user_id, recognize=body.recognize_scans
        )
