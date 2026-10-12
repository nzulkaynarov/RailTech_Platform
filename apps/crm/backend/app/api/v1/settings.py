"""Настройки (admin, PLAN Фаза 5): значения и схемы для форм, сохранение, «сухой прогон»."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from pydantic import ValidationError

from app.api.deps import ContainerDep, require
from app.domain.errors import NotFoundError, ValidationFailedError
from app.schemas.admin import DryRunResponse, DryRunRowOut, SettingsResponse
from app.schemas.leads import ActionResult
from app.schemas.settings import SETTINGS_MODELS, EscalationSettings
from app.security.principal import Principal
from app.services import escalation_dry_run as dry

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

Reader = Annotated[Principal, Depends(require("settings", "read"))]
Writer = Annotated[Principal, Depends(require("settings", "write"))]
# Профиль бота правится и публикуется в «Подключениях» (`/integrations/telegram/profile`).
PAGE_KEYS = tuple(key for key in SETTINGS_MODELS if key != "bot_profile")


@router.get("", response_model=SettingsResponse)
async def get_settings(_: Reader, container: ContainerDep) -> SettingsResponse:
    raw = await container.settings_service.raw()
    values = {key: raw[key] for key in PAGE_KEYS}
    schemas = {key: SETTINGS_MODELS[key].model_json_schema() for key in PAGE_KEYS}
    return SettingsResponse(values=values, schemas=schemas)


@router.put("/{key}", response_model=ActionResult)
async def put_setting(
    key: Annotated[str, Path(max_length=32)],
    body: dict[str, Any],
    who: Writer,
    container: ContainerDep,
) -> ActionResult:
    if key not in PAGE_KEYS:
        raise NotFoundError("unknown settings key")
    try:
        await container.settings_service.update(key, body, who.user_id, who.actor)
    except ValidationError as exc:
        # Пути полей («greeting.uz») — чтобы форма подсветила поле и открыла нужный текст.
        paths = [".".join(str(p) for p in err["loc"]) for err in exc.errors()][:20]
        raise ValidationFailedError(str(exc)[:1000], field=key, paths=paths) from exc
    except ValueError as exc:
        raise ValidationFailedError(str(exc)[:1000], field=key) from exc
    return ActionResult()


@router.post("/escalation/dry-run", response_model=DryRunResponse)
async def escalation_dry_run(
    body: EscalationSettings, _: Reader, container: ContainerDep
) -> DryRunResponse:
    current = (await container.settings_service.get()).escalation.triggers()
    async with container.session_factory() as session:
        runs = await dry.latest_runs(session)
    report = dry.compare(runs, current, body.triggers())
    return DryRunResponse(
        dialogs=report.dialogs,
        escalated_current=report.escalated_current,
        escalated_candidate=report.escalated_candidate,
        by_code_current=report.by_code_current,
        by_code_candidate=report.by_code_candidate,
        changed=[
            DryRunRowOut(
                run_id=r.run_id,
                lead_id=r.lead_id,
                at=r.at,
                current=r.current,
                candidate=r.candidate,
            )
            for r in report.changed
        ],
    )
