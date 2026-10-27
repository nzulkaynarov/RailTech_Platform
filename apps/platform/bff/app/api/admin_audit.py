"""Admin · Журнал аудита и журнал изменений роли (контракт: tag `admin`, 0.12.0).

BFF только проксирует журнал CRM (`GET /api/v1/audit`, право `audit:read`) с токеном сотрудника и
проверяет раздел `admin` каталога: читать журнал могут администратор (полный доступ) и директор
(чтение); изменять записи не может никто — эндпоинтов записи нет. Фильтры CRM — автор, действие,
объект, период; BFF переименовывает параметры и по умолчанию скрывает входы в систему (они забивают
журнал изменений). Значения секретных полей из `before`/`after` вырезаются.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from app.clients.crm_users import CrmRoles
from app.deps import Authed, require
from app.errors import PlatformError, from_backend
from app.schemas_audit import (
    AuditPage,
    RoleJournal,
    to_audit_page,
    to_role_journal,
)

router = APIRouter(tags=["admin"])

Reader = Annotated[Authed, Depends(require("admin", "read"))]
RoleIdPath = Annotated[str, Path(pattern=r"^[1-9][0-9]*$")]

AUDIT = "/api/v1/audit"
# Входы и неудачные попытки (`auth.login`, `auth.login_failed`) и обмен SSO — не изменения данных.
LOGIN_ACTIONS = ["auth.login", "sso.exchange"]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


async def _audit(authed: Authed, params: dict[str, Any]) -> dict[str, Any]:
    response = await authed.call("crm", "GET", AUDIT, params=params)
    if response.status_code != 200:
        raise from_backend("crm", response)
    body = response.json()
    if not isinstance(body, dict):
        raise PlatformError(
            "BACKEND_UNAVAILABLE", "Сервис временно недоступен.", status_code=503, source="crm"
        )
    return body


@router.get(
    "/admin/audit",
    response_model=AuditPage,
    response_model_exclude_none=True,
    operation_id="listAudit",
)
async def list_audit(
    authed: Reader,
    actor_id: Annotated[str | None, Query(pattern=r"^[1-9][0-9]*$")] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_type: Annotated[str | None, Query(max_length=32)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    include_logins: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> AuditPage:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if actor_id:
        params["actor_user_id"] = actor_id
    if action:
        params["action"] = action
    if entity_type:
        params["entity_type"] = entity_type
    if entity_id:
        params["entity_id"] = entity_id
    if from_ is not None:
        params["created_from"] = from_.isoformat()
    if to is not None:
        params["created_to"] = to.isoformat()
    if not include_logins:
        params["exclude_actions"] = LOGIN_ACTIONS
    return to_audit_page(await _audit(authed, params), limit=limit, offset=offset)


@router.get(
    "/admin/roles/{id}/journal",
    response_model=RoleJournal,
    response_model_exclude_none=True,
    operation_id="getRoleJournal",
)
async def get_role_journal(
    id: RoleIdPath, authed: Reader, limit: Limit = 50, offset: Offset = 0
) -> RoleJournal:
    """Изменения роли: записи аудита CRM `platform_role.*` с этим `entity_id`, новые первыми.

    Несуществующая роль — 404 (CRM `GET /platform-roles/{id}`), а не пустой журнал: иначе опечатка
    в адресе выглядела бы как роль без изменений."""
    await CrmRoles(authed.call).get(id)
    body = await _audit(
        authed,
        {"entity_type": "platform_role", "entity_id": id, "limit": limit, "offset": offset},
    )
    return to_role_journal(body)
