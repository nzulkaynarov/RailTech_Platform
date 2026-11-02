"""EDS · «Заполнить из файла» и настройки документооборота (контракт BFF, EDS-REG).

BFF не зовёт модели и не решает (стандарт ИИ-помощника, исследование 2026-11-02 §4.2): чтение
файла, маскирование, вызов шлюза, справочник и журнал — в EDS. Здесь — разделы каталога и перевод
ошибок EDS.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel, ValidationError

from app.clients.eds import eds_error
from app.deps import Authed, require, require_any
from app.errors import backend_unavailable
from app.schemas_eds_intake import (
    AiDecisionIn,
    DocflowSettings,
    DocflowSettingsPatch,
    LetterIntakeIn,
    LetterIntakeSuggestion,
)

router = APIRouter(prefix="/eds", tags=["letters"])

Registrar = Annotated[Authed, Depends(require("eds.inbox.register", "full"))]
SettingsReader = Annotated[
    Authed, Depends(require_any(("eds.inbox.register", "full"), ("admin", "read")))
]
Admin = Annotated[Authed, Depends(require("admin", "full"))]
SuggestionId = Annotated[uuid.UUID, Path(alias="id")]


async def _call(authed: Authed, method: str, path: str, ok: int, **kw: Any) -> Any:
    response = await authed.call("eds", method, f"/api/v1{path}", **kw)
    if response.status_code != ok:
        raise eds_error(response)
    if ok == 204:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise backend_unavailable("eds", "bad_response") from exc


def _parse[M: BaseModel](model: type[M], raw: Any) -> M:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise backend_unavailable("eds", "bad_intake") from exc


@router.post(
    "/letter-intake", response_model=LetterIntakeSuggestion, operation_id="suggestLetterFromFile"
)
async def suggest_letter_from_file(
    authed: Registrar, body: LetterIntakeIn
) -> LetterIntakeSuggestion:
    raw = await _call(authed, "POST", "/letter-intake", 200, json={"file_id": str(body.file_id)})
    return _parse(LetterIntakeSuggestion, raw)


@router.post(
    "/ai-suggestions/{id}/decision",
    status_code=204,
    response_class=Response,
    operation_id="decideAiSuggestion",
)
async def decide_ai_suggestion(
    authed: Registrar, suggestion_id: SuggestionId, body: AiDecisionIn
) -> Response:
    await _call(
        authed,
        "POST",
        f"/ai-suggestions/{suggestion_id}/decision",
        204,
        json={"decision": body.decision},
    )
    return Response(status_code=204)


@router.get("/docflow-settings", response_model=DocflowSettings, operation_id="getDocflowSettings")
async def get_docflow_settings(authed: SettingsReader) -> DocflowSettings:
    return _parse(DocflowSettings, await _call(authed, "GET", "/docflow-settings", 200))


@router.patch(
    "/docflow-settings", response_model=DocflowSettings, operation_id="updateDocflowSettings"
)
async def update_docflow_settings(authed: Admin, body: DocflowSettingsPatch) -> DocflowSettings:
    raw = await _call(authed, "PATCH", "/docflow-settings", 200, json=body.model_dump())
    return _parse(DocflowSettings, raw)
