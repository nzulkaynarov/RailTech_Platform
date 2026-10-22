"""Admin · Оргструктура: сотрудники, выдача ролей, отключение, приглашение (контракт: tag `admin`).

BFF не решает: роли Платформы хранит CRM (`platform_roles`), он же вычисляет доступ к ERP и роли
ERP и ставит провижининг; инвариант «последний администратор» тоже за CRM (409 `last_admin` ->
`LAST_ADMIN`).
Доступ к разделу `admin` матрицы: ADMIN — полный, DIRECTOR — только чтение.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status

from app.clients.crm_users import CrmUsers
from app.deps import Authed, require
from app.errors import PlatformError
from app.schemas_admin import (
    Employee,
    EmployeeInvite,
    EmployeeList,
    EmployeeStatus,
    EmployeeUpdate,
    to_employee,
)

router = APIRouter(tags=["admin"])

Reader = Annotated[Authed, Depends(require("admin", "read"))]
Writer = Annotated[Authed, Depends(require("admin", "full"))]
EmployeeId = Annotated[str, Path(pattern=r"^[0-9]+$")]

INVITE_NOT_SENT = (
    "Сотрудник добавлен, но письмо не отправлено: проверьте подключение почты в Admin · Интеграции."
)


def _users(authed: Authed) -> CrmUsers:
    return CrmUsers(authed.call)


def _matches(employee: Employee, q: str) -> bool:
    needle = q.strip().casefold()
    haystack = f"{employee.name} {employee.email} {employee.position or ''}".casefold()
    return needle in haystack


@router.get(
    "/admin/users",
    response_model=EmployeeList,
    response_model_exclude_none=True,
    operation_id="listEmployees",
)
async def list_employees(
    authed: Reader,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status_filter: Annotated[EmployeeStatus | None, Query(alias="status")] = None,
) -> EmployeeList:
    items = [to_employee(u) for u in await _users(authed).list_all()]
    if q and q.strip():
        items = [e for e in items if _matches(e, q)]
    if status_filter is not None:
        items = [e for e in items if e.status == status_filter]
    items.sort(key=lambda e: (e.name.casefold(), e.id))
    return EmployeeList(items=items)


@router.post(
    "/admin/users/invite",
    response_model=Employee,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    operation_id="inviteEmployee",
)
async def invite_employee(body: EmployeeInvite, authed: Writer) -> Employee:
    """Создать пользователя в CRM с ролями Платформы и отправить приглашение по почте."""
    users = _users(authed)
    payload: dict[str, Any] = {
        "email": body.email.strip(),
        "full_name": body.name,
        "platform_roles": list(body.roles),
    }
    if body.position and body.position.strip():
        payload["position"] = body.position.strip()
    user = await users.create(payload)
    try:
        await users.invite(str(user["id"]))
    except PlatformError as exc:
        # Пользователь уже создан, временный пароль BFF наружу не отдаёт: письмо — единственный
        # путь. Повтор приглашения — отдельная операция (разрыв, Q-PLT-15-3), ошибка несёт id.
        raise PlatformError(
            "CONFLICT",
            INVITE_NOT_SENT,
            status_code=status.HTTP_409_CONFLICT,
            source=exc.body.source,
            details={
                "employee_id": str(user["id"]),
                "invite": "not_sent",
                **(exc.body.details or {}),
            },
        ) from exc
    return to_employee(user)


@router.get(
    "/admin/users/{id}",
    response_model=Employee,
    response_model_exclude_none=True,
    operation_id="getEmployee",
)
async def get_employee(id: EmployeeId, authed: Reader) -> Employee:
    return to_employee(await _users(authed).get(id))


@router.patch(
    "/admin/users/{id}",
    response_model=Employee,
    response_model_exclude_none=True,
    operation_id="updateEmployee",
)
async def update_employee(id: EmployeeId, body: EmployeeUpdate, authed: Writer) -> Employee:
    """Роли (`platform_roles` в CRM), должность, отключение; «последний админ» — решение CRM."""
    payload: dict[str, Any] = {}
    if "roles" in body.model_fields_set:
        payload["platform_roles"] = list(body.roles or [])
    if "position" in body.model_fields_set:
        payload["position"] = (body.position or "").strip()
    if "is_active" in body.model_fields_set:
        payload["is_active"] = body.is_active
    return to_employee(await _users(authed).update(id, payload))
