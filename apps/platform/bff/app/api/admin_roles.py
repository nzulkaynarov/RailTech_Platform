"""Admin · Ролевая матрица: роли Платформы как данные (ADR-0012, контракт: tag `admin`, 0.3.1).

BFF не решает: роли хранит CRM (`/api/v1/platform-roles`, R-1), она же проверяет каталог (раздел и
уровень), считает «что произойдёт» и пересчитывает права сотрудников в CRM и ERP. Системные роли
неизменны (409 `ROLE_SYSTEM`), роль с сотрудниками не удаляется (409 `ROLE_IN_USE`). Доступ — раздел
`admin` каталога: чтение матрицы (`GET`) — от `read` (директор видит её только для чтения; в CRM —
`users:read`), создание, изменение, удаление и «что произойдёт» — `full` (в CRM — `users:write`).
Изменение несёт `version`; устаревшая — 409 `CONFLICT`, `details.reason = role_version_conflict`.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Response, status

from app.clients.crm_users import CrmRoles
from app.deps import Authed, require
from app.schemas_admin import (
    Role,
    RoleCreate,
    RoleList,
    RolePreview,
    RolePreviewIn,
    RoleUpdate,
    to_preview,
    to_role,
)
from app.session import SessionData

router = APIRouter(tags=["admin"])

Admin = Annotated[Authed, Depends(require("admin", "full"))]
Reader = Annotated[Authed, Depends(require("admin", "read"))]
RoleId = Annotated[str, Path(pattern=r"^[0-9]+$")]


def _roles(authed: Authed) -> CrmRoles:
    return CrmRoles(authed.call)


def _expire_profile(data: SessionData) -> None:
    data.profile_checked_at = 0.0


async def _refresh_own_profile(authed: Authed, role_id: str) -> None:
    """Изменена роль самого администратора: следующий `/me` перечитывает профиль сразу."""
    if any(str(r.id) == role_id for r in authed.roles):
        await authed.service.store.update(authed.sid, _expire_profile)


@router.get(
    "/admin/roles",
    response_model=RoleList,
    response_model_exclude_none=True,
    operation_id="listRoles",
)
async def list_roles(authed: Reader) -> RoleList:
    return RoleList(items=[to_role(r) for r in await _roles(authed).list_all()])


@router.post(
    "/admin/roles",
    response_model=Role,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    operation_id="createRole",
)
async def create_role(body: RoleCreate, authed: Admin) -> Role:
    payload: dict[str, Any] = {
        "name": body.name,
        "access": dict(body.access),
        "restricted_fields": list(body.restricted_fields),
    }
    if body.description is not None:
        payload["description"] = body.description.strip()
    return to_role(await _roles(authed).create(payload))


@router.post(
    "/admin/roles/preview",
    response_model=RolePreview,
    operation_id="previewRole",
)
async def preview_role(body: RolePreviewIn, authed: Admin) -> RolePreview:
    payload: dict[str, Any] = {}
    if body.role_id is not None:
        payload["role_id"] = int(body.role_id)
    if body.access is not None:
        payload["access"] = dict(body.access)
    if body.restricted_fields is not None:
        payload["restricted_fields"] = list(body.restricted_fields)
    return to_preview(await _roles(authed).preview(payload))


@router.get(
    "/admin/roles/{id}",
    response_model=Role,
    response_model_exclude_none=True,
    operation_id="getRole",
)
async def get_role(id: RoleId, authed: Reader) -> Role:
    return to_role(await _roles(authed).get(id))


@router.patch(
    "/admin/roles/{id}",
    response_model=Role,
    response_model_exclude_none=True,
    operation_id="updateRole",
)
async def update_role(id: RoleId, body: RoleUpdate, authed: Admin) -> Role:
    payload = body.model_dump(include=body.model_fields_set)
    if isinstance(payload.get("name"), str):
        payload["name"] = payload["name"].strip()
    role = to_role(await _roles(authed).update(id, payload))
    await _refresh_own_profile(authed, id)
    return role


@router.delete(
    "/admin/roles/{id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteRole"
)
async def delete_role(id: RoleId, authed: Admin) -> Response:
    await _roles(authed).delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
