"""Admin · Настройки бота: разделы настроек CRM, шаблоны ответов, выгрузки CSV (контракт: tag `bot`,
0.11.0).

BFF только проксирует к CRM с токеном сотрудника и проверяет раздел каталога: чтение настроек —
`admin` от `read` (директор видит без правки; в CRM — `settings:read`), правка, пробный прогон,
шаблоны и выгрузки — `admin: full` (`settings:write`, `reply_templates:write`, `export:read`).
Шаблоны читает и менеджер с `crm.leads` полным (они нужны в карточке лида). Значения настроек
проверяет модель раздела в CRM: ошибка приходит как `VALIDATION_FAILED` с путями полей.

Выгрузка CSV: нужны `admin: full` и чтение выгружаемых данных (лиды — `crm.leads`, клиенты и
сделки — `crm.clients`; системная «Администратор» без второй роли бизнес-данные не выгружает,
R3-D-2). Файл идёт потоком: BFF читает ответ CRM кусками и сразу отдаёт браузеру, не накапливая
его в памяти; имя файла с датой — от CRM.
"""

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.clients import crm_models as crm
from app.clients.crm_proxy import CrmProxy, crm_error
from app.deps import Authed, require, require_all, require_any
from app.errors import PlatformError
from app.rbac import allows
from app.schemas_bot import (
    BotSettings,
    EscalationDryRun,
    EscalationSettingsIn,
    ReplyTemplate,
    ReplyTemplateIn,
    ReplyTemplateList,
)
from app.schemas_integrations import ActionOk
from app.schemas_kb import CreatedId, Language

router = APIRouter(tags=["bot"])

API = "/api/v1"
TASHKENT = ZoneInfo("Asia/Tashkent")

Reader = Annotated[Authed, Depends(require("admin", "read"))]
Admin = Annotated[Authed, Depends(require("admin", "full"))]
TemplateReader = Annotated[Authed, Depends(require_any(("admin", "read"), ("crm.leads", "full")))]
Exporter = Annotated[Authed, Depends(require_all(("admin", "full")))]
TemplateId = Annotated[int, Path(ge=1)]
Entity = Literal["leads", "clients", "deals"]

# Раздел каталога, чтение которого нужно, чтобы выгружать сущность (в CRM —
# `leads|clients|deals:read`).
EXPORT_DATA: dict[str, str] = {
    "leads": "crm.leads",
    "clients": "crm.clients",
    "deals": "crm.clients",
}
# Фильтры, которые CRM понимает у каждой выгрузки (остальные параметры запроса BFF отбрасывает).
EXPORT_FILTERS: dict[str, tuple[str, ...]] = {
    "leads": ("q", "stage", "language", "created_from", "created_to"),
    "clients": ("q",),
    "deals": ("stage", "closed_from", "closed_to"),
}
_FILENAME = re.compile(r'^attachment; filename="[A-Za-z0-9._-]{1,100}\.csv"$')


def _crm(authed: Authed) -> CrmProxy:
    return CrmProxy(authed.call)


# --- настройки ----------------------------------------------------------------------------------


@router.get("/admin/bot/settings", response_model=BotSettings, operation_id="getBotSettings")
async def get_settings(authed: Reader) -> BotSettings:
    out = await _crm(authed).get_model(crm.SettingsResponse, "GET", f"{API}/settings")
    return BotSettings(values=out.values, schemas=out.schemas)


@router.put("/admin/bot/settings/{key}", response_model=ActionOk, operation_id="saveBotSetting")
async def save_setting(
    key: Annotated[str, Path(pattern=r"^[a-z_]{1,32}$")], body: dict[str, Any], authed: Admin
) -> ActionOk:
    return ActionOk.model_validate(
        await _crm(authed).request("PUT", f"{API}/settings/{key}", json=body)
    )


@router.post(
    "/admin/bot/settings/escalation/dry-run",
    response_model=EscalationDryRun,
    operation_id="dryRunEscalation",
)
async def dry_run_escalation(body: EscalationSettingsIn, authed: Admin) -> EscalationDryRun:
    out = await _crm(authed).get_model(
        crm.DryRunResponse,
        "POST",
        f"{API}/settings/escalation/dry-run",
        json=body.model_dump(exclude_none=True),
        probe=True,
    )
    return EscalationDryRun.model_validate(out.model_dump(mode="json"))


# --- шаблоны ответов ----------------------------------------------------------------------------


@router.get(
    "/admin/bot/reply-templates",
    response_model=ReplyTemplateList,
    operation_id="listReplyTemplates",
)
async def list_templates(authed: TemplateReader) -> ReplyTemplateList:
    rows = await _crm(authed).get_list(crm.ReplyTemplateOut, f"{API}/reply-templates")
    return ReplyTemplateList(
        items=[ReplyTemplate.model_validate(r.model_dump(mode="json")) for r in rows]
    )


@router.post(
    "/admin/bot/reply-templates",
    response_model=CreatedId,
    status_code=status.HTTP_201_CREATED,
    operation_id="createReplyTemplate",
)
async def create_template(body: ReplyTemplateIn, authed: Admin) -> CreatedId:
    out = await _crm(authed).get_model(
        crm.Created, "POST", f"{API}/reply-templates", expected=201, json=body.model_dump()
    )
    return CreatedId(id=out.id)


@router.put(
    "/admin/bot/reply-templates/{id}", response_model=ActionOk, operation_id="updateReplyTemplate"
)
async def update_template(id: TemplateId, body: ReplyTemplateIn, authed: Admin) -> ActionOk:
    return ActionOk.model_validate(
        await _crm(authed).request("PUT", f"{API}/reply-templates/{id}", json=body.model_dump())
    )


@router.delete(
    "/admin/bot/reply-templates/{id}", response_model=ActionOk, operation_id="deleteReplyTemplate"
)
async def delete_template(id: TemplateId, authed: Admin) -> ActionOk:
    return ActionOk.model_validate(
        await _crm(authed).request("DELETE", f"{API}/reply-templates/{id}")
    )


# --- выгрузки CSV -------------------------------------------------------------------------------


def _filename(header: str | None, entity: str) -> str:
    """`Content-Disposition` CRM, если он безопасен; иначе имя с датой по Ташкенту."""
    if header and _FILENAME.match(header):
        return header
    stamp = datetime.now(TASHKENT).strftime("%Y%m%d-%H%M")
    return f'attachment; filename="{entity}-{stamp}.csv"'


@router.get(
    "/admin/bot/exports/{entity}",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}}},
    operation_id="downloadCsvExport",
)
async def download_export(
    entity: Entity,
    authed: Exporter,
    q: Annotated[str | None, Query(max_length=100)] = None,
    stage: Annotated[str | None, Query(max_length=32)] = None,
    language: Language | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    closed_from: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    closed_to: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
) -> StreamingResponse:
    needed = EXPORT_DATA[entity]
    if not allows(authed.access, needed, "read"):
        raise PlatformError(
            "FORBIDDEN",
            "Выгружать эти данные может только роль, которой открыт их раздел.",
            status_code=403,
            details={"resource": needed, "need": "read"},
        )
    given: dict[str, Any] = {
        "q": q,
        "stage": stage,
        "language": language,
        "created_from": created_from.isoformat() if created_from else None,
        "created_to": created_to.isoformat() if created_to else None,
        "closed_from": closed_from,
        "closed_to": closed_to,
    }
    params = {k: v for k, v in given.items() if v is not None and k in EXPORT_FILTERS[entity]}
    response = await _crm(authed).raw(
        "GET", f"{API}/export/{entity}.csv", params=params or None, stream=True
    )
    if response.status_code != 200:
        try:
            await response.aread()
            raise crm_error(response)
        finally:
            await response.aclose()
    return StreamingResponse(
        response.aiter_raw(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": _filename(response.headers.get("content-disposition"), entity)
        },
        background=BackgroundTask(response.aclose),
    )
