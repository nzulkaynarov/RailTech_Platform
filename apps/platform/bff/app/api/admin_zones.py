"""Admin · Зоны ответственности (ЕВ-З, tag `admin`): «зона → ответственный → замещающий → куратор».

BFF не решает: зоны, проблемы по фактам (нет ответственного, нет прав зоны, неактивный человек,
вышел срок) и журнал изменений — в CRM (`/api/v1/responsibility-zones`). Доступ — раздел каталога:
чтение списка — `admin` от `read` (директор), завести и выключить зону — `admin: full`, назначить
людей, основание и срок — `company.settings: full` (администратор и директор). Сводка для сигналов —
`company.settings: full`. Зоны не маршрутизируют уведомления и согласования.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from app.clients.crm_zones import CrmZones
from app.deps import Authed, require
from app.schemas_zones import (
    Zone,
    ZoneCreate,
    ZoneList,
    ZoneSummary,
    ZoneUpdate,
    to_zone,
)

router = APIRouter(tags=["admin"])

Reader = Annotated[Authed, Depends(require("admin", "read"))]
Admin = Annotated[Authed, Depends(require("admin", "full"))]
Assigner = Annotated[Authed, Depends(require("company.settings", "full"))]
ZoneId = Annotated[str, Path(pattern=r"^[1-9][0-9]*$")]
ADMIN_ZONES = "/admin/responsibility-zones"
# Поля людей в контракте BFF -> поля CRM (id сотрудника CRM — число).
_PEOPLE = {
    "responsible_id": "responsible_user_id",
    "deputy_id": "deputy_user_id",
    "curator_id": "curator_user_id",
}


@router.get(
    ADMIN_ZONES,
    response_model=ZoneList,
    response_model_exclude_none=True,
    operation_id="listResponsibilityZones",
)
async def list_zones(authed: Reader) -> ZoneList:
    return ZoneList(items=[to_zone(z) for z in await CrmZones(authed.call).list_all()])


@router.get(
    f"{ADMIN_ZONES}/summary",
    response_model=ZoneSummary,
    operation_id="getResponsibilityZonesSummary",
)
async def zones_summary(authed: Assigner) -> ZoneSummary:
    return ZoneSummary.model_validate(await CrmZones(authed.call).summary())


@router.post(
    ADMIN_ZONES,
    response_model=Zone,
    response_model_exclude_none=True,
    status_code=201,
    operation_id="createResponsibilityZone",
)
async def create_zone(body: ZoneCreate, authed: Admin) -> Zone:
    payload: dict[str, Any] = {
        "code": body.code,
        "name": body.name.model_dump(),
        "sections": list(body.sections),
    }
    if body.description is not None:
        payload["description"] = body.description.model_dump()
    return to_zone(await CrmZones(authed.call).create(payload))


@router.get(
    f"{ADMIN_ZONES}/{{id}}",
    response_model=Zone,
    response_model_exclude_none=True,
    operation_id="getResponsibilityZone",
)
async def get_zone(id: ZoneId, authed: Reader) -> Zone:
    return to_zone(await CrmZones(authed.call).get(id))


@router.patch(
    f"{ADMIN_ZONES}/{{id}}",
    response_model=Zone,
    response_model_exclude_none=True,
    operation_id="updateResponsibilityZone",
)
async def update_zone(id: ZoneId, body: ZoneUpdate, authed: Assigner) -> Zone:
    sent = body.model_dump(include=body.model_fields_set, mode="json")
    payload: dict[str, Any] = {}
    for key, value in sent.items():
        if key in _PEOPLE:
            payload[_PEOPLE[key]] = int(value) if value is not None else None
        else:
            payload[key] = value
    return to_zone(await CrmZones(authed.call).update(id, payload))


@router.post(
    f"{ADMIN_ZONES}/{{id}}/deactivate",
    response_model=Zone,
    response_model_exclude_none=True,
    operation_id="deactivateResponsibilityZone",
)
async def deactivate_zone(id: ZoneId, authed: Admin) -> Zone:
    return to_zone(await CrmZones(authed.call).set_active(id, False))


@router.post(
    f"{ADMIN_ZONES}/{{id}}/activate",
    response_model=Zone,
    response_model_exclude_none=True,
    operation_id="activateResponsibilityZone",
)
async def activate_zone(id: ZoneId, authed: Admin) -> Zone:
    return to_zone(await CrmZones(authed.call).set_active(id, True))
