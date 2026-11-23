"""Реестр зон ответственности (ЕВ-З): `/api/v1/responsibility-zones`.

Чтение — `users:read` (администратор и директор). Завести и выключить зону — `users:write`
(администратор). Назначить людей, основание и срок — администратор или директор: право
`ticket_label:write` (раздел `company.settings: full`, его держат оба). Зона без ответственного,
ответственный без прав зоны и вышедший срок — проблемы в ответе, не запрет. Зоны не маршрутизируют
уведомления и согласования.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import ContainerDep, require
from app.schemas.responsibility_zones import (
    LocalizedText,
    ResponsibilityZoneCreate,
    ResponsibilityZoneList,
    ResponsibilityZoneOut,
    ResponsibilityZoneSummary,
    ResponsibilityZoneUpdate,
    ZonePerson,
    ZoneProblemOut,
)
from app.security.principal import Principal
from app.services.responsibility_zones import PersonView, ZonePatch, ZoneView

router = APIRouter(prefix="/api/v1/responsibility-zones", tags=["responsibility-zones"])

Reader = Annotated[Principal, Depends(require("users", "read"))]
Admin = Annotated[Principal, Depends(require("users", "write"))]
# Назначение людей: раздел `company.settings` (администратор и директор), в CRM — `ticket_label`.
Signal = Annotated[Principal, Depends(require("ticket_label", "read"))]
Assigner = Annotated[Principal, Depends(require("ticket_label", "write"))]

_PATCH_FIELDS = (
    "responsible_user_id",
    "deputy_user_id",
    "curator_user_id",
    "basis",
    "valid_from",
    "valid_to",
)


def _person(view: PersonView | None) -> ZonePerson | None:
    if view is None:
        return None
    return ZonePerson(id=view.id, name=view.name, position=view.position, is_active=view.is_active)


def to_out(view: ZoneView) -> ResponsibilityZoneOut:
    return ResponsibilityZoneOut(
        id=view.id,
        code=view.code,
        name=LocalizedText(**view.name),
        description=LocalizedText(**view.description),
        sections=view.sections,
        responsible=_person(view.responsible),
        deputy=_person(view.deputy),
        curator=_person(view.curator),
        basis=view.basis,
        valid_from=view.valid_from,
        valid_to=view.valid_to,
        is_active=view.is_active,
        problems=[
            ZoneProblemOut(code=p.code, severity=p.severity, sections=list(p.sections))
            for p in view.problems
        ],
        updated_at=view.updated_at,
    )


@router.get("", response_model=ResponsibilityZoneList)
async def list_zones(_: Reader, container: ContainerDep) -> ResponsibilityZoneList:
    zones = await container.responsibility_zone_service.list_zones()
    return ResponsibilityZoneList(items=[to_out(z) for z in zones])


@router.get("/summary", response_model=ResponsibilityZoneSummary)
async def zones_summary(_: Signal, container: ContainerDep) -> ResponsibilityZoneSummary:
    """Числа для сигналов: доступны держателям `company.settings`, без списка людей."""
    zones = [z for z in await container.responsibility_zone_service.list_zones() if z.is_active]
    return ResponsibilityZoneSummary(
        zones_total=len(zones),
        without_responsible=sum(
            1
            for z in zones
            if any(p.code in ("no_responsible", "responsible_inactive") for p in z.problems)
        ),
        with_problems=sum(1 for z in zones if z.problems),
    )


@router.post("", response_model=ResponsibilityZoneOut, status_code=status.HTTP_201_CREATED)
async def create_zone(
    body: ResponsibilityZoneCreate, who: Admin, container: ContainerDep
) -> ResponsibilityZoneOut:
    view = await container.responsibility_zone_service.create(
        who.actor,
        body.code,
        body.name.model_dump(),
        body.description.model_dump(),
        body.sections,
    )
    return to_out(view)


@router.get("/{zone_id}", response_model=ResponsibilityZoneOut)
async def get_zone(zone_id: int, _: Reader, container: ContainerDep) -> ResponsibilityZoneOut:
    return to_out(await container.responsibility_zone_service.get(zone_id))


@router.patch("/{zone_id}", response_model=ResponsibilityZoneOut)
async def update_zone(
    zone_id: int, body: ResponsibilityZoneUpdate, who: Assigner, container: ContainerDep
) -> ResponsibilityZoneOut:
    sent = {name: getattr(body, name) for name in _PATCH_FIELDS if name in body.model_fields_set}
    view = await container.responsibility_zone_service.update(who.actor, zone_id, ZonePatch(**sent))
    return to_out(view)


@router.post("/{zone_id}/deactivate", response_model=ResponsibilityZoneOut)
async def deactivate_zone(
    zone_id: int, who: Admin, container: ContainerDep
) -> ResponsibilityZoneOut:
    return to_out(await container.responsibility_zone_service.set_active(who.actor, zone_id, False))


@router.post("/{zone_id}/activate", response_model=ResponsibilityZoneOut)
async def activate_zone(zone_id: int, who: Admin, container: ContainerDep) -> ResponsibilityZoneOut:
    return to_out(await container.responsibility_zone_service.set_active(who.actor, zone_id, True))
