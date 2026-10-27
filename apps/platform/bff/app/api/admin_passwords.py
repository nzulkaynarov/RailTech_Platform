"""Admin · Оргструктура: сотрудник без почты и временный пароль (контракт: tag `admin`, 0.10.0).

Пароль выдаёт CRM (`POST /users` при создании, `POST /users/{id}/reset-password` при сбросе) и
показывает его один раз: BFF отдаёт его в теле этого ответа и больше нигде не держит — ни в
журнале, ни в Redis, ни в сессии; ответ `Cache-Control: no-store`. Повторно получить пароль
нельзя (CRM хранит только хеш) — можно выдать новый.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Response, status

from app.clients import crm_setup
from app.clients.crm_users import CrmUsers, crm_error
from app.deps import Authed, require
from app.errors import PlatformError
from app.schemas_admin import EmployeeInvite, to_employee
from app.schemas_setup import EmployeeCredentials

router = APIRouter(tags=["admin"])

Writer = Annotated[Authed, Depends(require("admin", "full"))]
EmployeeId = Annotated[str, Path(pattern=r"^[1-9][0-9]*$")]

OWN_ACCOUNT_MESSAGE = "Свой пароль меняется в профиле. Временный пароль выдают другим сотрудникам."


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post(
    "/admin/users",
    response_model=EmployeeCredentials,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    operation_id="createEmployee",
)
async def create_employee(
    body: EmployeeInvite, authed: Writer, response: Response
) -> EmployeeCredentials:
    """Создать пользователя в CRM с ролями Платформы; временный пароль — в этом ответе, один раз."""
    payload: dict[str, Any] = {
        "email": body.email.strip(),
        "full_name": body.name,
        "platform_role_ids": [int(i) for i in body.role_ids],
    }
    if body.position and body.position.strip():
        payload["position"] = body.position.strip()
    user, password = await crm_setup.create_user_with_password(authed.call, payload, crm_error)
    _no_store(response)
    return EmployeeCredentials(employee=to_employee(user), temporary_password=password)


@router.post(
    "/admin/users/{id}/temporary-password",
    response_model=EmployeeCredentials,
    response_model_exclude_none=True,
    operation_id="issueTemporaryPassword",
)
async def issue_temporary_password(
    id: EmployeeId, authed: Writer, response: Response
) -> EmployeeCredentials:
    """Новый временный пароль (CRM `reset-password`); прежний пароль и сессии не действуют."""
    # Сравнение числом остаётся страховкой к шаблону пути: «07» и «7» — один сотрудник.
    if int(id) == authed.data.user_id:
        raise PlatformError(
            "CONFLICT",
            OWN_ACCOUNT_MESSAGE,
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": "own_account"},
        )
    users = CrmUsers(authed.call)
    before = await users.get(id)
    password = await crm_setup.reset_user_password(authed.call, id, crm_error)
    # Пароль уже выдан и больше нигде не хранится: сбой перечитывания сотрудника его не теряет.
    try:
        user = await users.get(id)
    except PlatformError:
        user = {**before, "must_change_password": True}
    _no_store(response)
    return EmployeeCredentials(employee=to_employee(user), temporary_password=password)
