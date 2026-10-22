"""Роли Платформы (только администратор): список, создание, изменение, удаление, предпросмотр.

Права сотрудников — объединение их ролей (ADR-0012). Системные роли («Администратор»,
«Директор») не меняются и не удаляются (409 `role_system`); роль с сотрудниками не удаляется
(409 `role_in_use`, `details.users`); неизвестный раздел или уровень вне `levels` — 422.
Выдача ролей сотрудникам — `PATCH /api/v1/users/{id}` с `platform_role_ids`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import ContainerDep, get_rbac, require
from app.schemas.platform_roles import (
    EmployeeImpactOut,
    PlatformRoleCreate,
    PlatformRoleOut,
    PlatformRoleUpdate,
    PreviewIn,
    PreviewOut,
    SectionLevel,
)
from app.security.principal import Principal
from app.security.rbac import Rbac
from app.services.platform_roles import Preview, RolePatch, RoleView

router = APIRouter(prefix="/api/v1/platform-roles", tags=["platform-roles"])

# «Только admin»: управление ролями — то же право, что запись сотрудников (`users:write`).
Admin = Annotated[Principal, Depends(require("users", "write"))]
RbacDep = Annotated[Rbac, Depends(get_rbac)]


def to_out(view: RoleView) -> PlatformRoleOut:
    return PlatformRoleOut.model_validate(view, from_attributes=True)


def _levels(pairs: list[tuple[str, str]]) -> list[SectionLevel]:
    return [SectionLevel(resource=r, level=lv) for r, lv in pairs]


def _preview_out(preview: Preview) -> PreviewOut:
    return PreviewOut(
        role_id=preview.role_id,
        employees_total=preview.employees_total,
        employees=[
            EmployeeImpactOut(
                user_id=e.user_id,
                full_name=e.full_name,
                is_active=e.is_active,
                gained=_levels(e.gained),
                lost=_levels(e.lost),
                fields_gained=e.fields_gained,
                fields_lost=e.fields_lost,
                erp_gained=e.erp_gained,
                erp_lost=e.erp_lost,
            )
            for e in preview.employees
        ],
        gained=_levels(preview.gained),
        lost=_levels(preview.lost),
        fields_gained=preview.fields_gained,
        fields_lost=preview.fields_lost,
    )


@router.get("", response_model=list[PlatformRoleOut])
async def list_roles(_: Admin, container: ContainerDep) -> list[PlatformRoleOut]:
    return [to_out(v) for v in await container.platform_role_service.list_roles()]


@router.post("", response_model=PlatformRoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: PlatformRoleCreate, who: Admin, container: ContainerDep, rbac: RbacDep
) -> PlatformRoleOut:
    view = await container.platform_role_service.create(
        who.actor, body.name, body.description, body.access, body.restricted_fields
    )
    await rbac.safe_reload()
    return to_out(view)


@router.post("/preview", response_model=PreviewOut)
async def preview_role(body: PreviewIn, _: Admin, container: ContainerDep) -> PreviewOut:
    """Что произойдёт при сохранении: сколько сотрудников и какие разделы получат или потеряют."""
    preview = await container.platform_role_service.preview(
        body.role_id, body.access, body.restricted_fields
    )
    return _preview_out(preview)


@router.get("/{role_id}", response_model=PlatformRoleOut)
async def get_role(role_id: int, _: Admin, container: ContainerDep) -> PlatformRoleOut:
    return to_out(await container.platform_role_service.get(role_id))


@router.patch("/{role_id}", response_model=PlatformRoleOut)
async def update_role(
    role_id: int, body: PlatformRoleUpdate, who: Admin, container: ContainerDep, rbac: RbacDep
) -> PlatformRoleOut:
    patch = RolePatch(
        name=body.name,
        description=body.description,
        access=body.access,
        restricted_fields=body.restricted_fields,
    )
    view = await container.platform_role_service.update(who.actor, role_id, patch)
    await rbac.safe_reload()
    return to_out(view)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: int, who: Admin, container: ContainerDep, rbac: RbacDep) -> Response:
    await container.platform_role_service.delete(who.actor, role_id)
    await rbac.safe_reload()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
