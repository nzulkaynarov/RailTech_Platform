"""Admin · Оргструктура: сотрудники, выдача ролей, отключение, приглашение (контракт: tag `admin`).

BFF не решает: роли Платформы — данные CRM (`platform_role_ids`, R-1), CRM же вычисляет права в CRM
и ERP и ставит провижининг; инварианты «последний администратор / директор» и «лиды в работе» —
тоже CRM (409 -> `LAST_ADMIN`, `LAST_DIRECTOR`, `CONFLICT`). Пустой набор ролей BFF отклоняет сам
(422 `ROLES_REQUIRED`, 0.6.0) — это проверка формы запроса, а не решение. Доступ — раздел `admin`
каталога: чтение — список и карточки, полный — изменения.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status

from app.clients.crm_users import CrmUsers, roles_required
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
from app.session import SessionData

router = APIRouter(tags=["admin"])

Reader = Annotated[Authed, Depends(require("admin", "read"))]
Writer = Annotated[Authed, Depends(require("admin", "full"))]
EmployeeId = Annotated[str, Path(pattern=r"^[0-9]+$")]

INVITE_CRM_UNAVAILABLE = (
    "CRM недоступна, повторите позже. Сотрудник уже добавлен, но письмо не отправлено."
)
RESEND_CRM_UNAVAILABLE = "CRM недоступна, повторите позже. Письмо не отправлено."
INVITE_NOT_SENT = (
    "Сотрудник добавлен, но письмо не отправлено: проверьте подключение почты в Admin · Интеграции."
)


def _expire_profile(data: SessionData) -> None:
    data.profile_checked_at = 0.0


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
        "platform_role_ids": [int(i) for i in body.role_ids],
    }
    if body.position and body.position.strip():
        payload["position"] = body.position.strip()
    user = await users.create(payload)
    try:
        await users.invite(str(user["id"]))
    except PlatformError as exc:
        # Пользователь уже создан, временный пароль BFF наружу не отдаёт: письмо — единственный
        # путь. Повтор — `POST /admin/users/{id}/invite`; ошибка несёт id сотрудника.
        raise _not_sent(exc, str(user["id"]), INVITE_CRM_UNAVAILABLE) from exc
    return to_employee(user)


def _not_sent(exc: PlatformError, employee_id: str, unavailable: str) -> PlatformError:
    details = {"employee_id": employee_id, "invite": "not_sent", **(exc.body.details or {})}
    if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
        # CRM не ответила: про почту сказать нечего, коннектор «Почта» мог быть исправен.
        return PlatformError(
            "BACKEND_UNAVAILABLE",
            unavailable,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            source=exc.body.source,
            details=details,
        )
    if exc.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN):
        return exc
    return PlatformError(
        "CONFLICT",
        INVITE_NOT_SENT,
        status_code=status.HTTP_409_CONFLICT,
        source=exc.body.source,
        details=details,
    )


@router.post(
    "/admin/users/{id}/invite",
    response_model=Employee,
    response_model_exclude_none=True,
    operation_id="resendInvite",
)
async def resend_invite(id: EmployeeId, authed: Writer) -> Employee:
    """Отправить приглашение снова. CRM меняет временный пароль только при отправке письма: без
    подключённой почты пароль прежний, ответ — 409 `CONFLICT` с `details.invite = not_sent`."""
    users = _users(authed)
    try:
        await users.invite(id)
    except PlatformError as exc:
        raise _not_sent(exc, id, RESEND_CRM_UNAVAILABLE) from exc
    return to_employee(await users.get(id))


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
    """Роли (`platform_role_ids` в CRM, хотя бы одна), должность, отключение, передача лидов;
    инварианты — CRM.

    Роли уходят полным набором id: BFF не читает и не дописывает роли кодами (иначе слетели бы
    роли без кода)."""
    payload: dict[str, Any] = {}
    if "role_ids" in body.model_fields_set:
        if not body.role_ids:
            raise roles_required()
        payload["platform_role_ids"] = [int(i) for i in body.role_ids]
    if "transfer_to_user_id" in body.model_fields_set and body.transfer_to_user_id is not None:
        payload["transfer_to_user_id"] = int(body.transfer_to_user_id)
    if "position" in body.model_fields_set:
        payload["position"] = (body.position or "").strip()
    if "is_active" in body.model_fields_set:
        payload["is_active"] = body.is_active
    employee = to_employee(await _users(authed).update(id, payload))
    if id == str(authed.data.user_id):
        # Свои роли изменены: следующий `/me` перечитывает профиль CRM, а не ждёт конца кэша (60 с).
        await authed.service.store.update(authed.sid, _expire_profile)
    return employee
