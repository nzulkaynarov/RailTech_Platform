"""`GET /api/v1/me` — сотрудник и его права EDS по проекции на момент запроса."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import require_permission
from app.models import Employee
from app.security.permissions import known_permissions

router = APIRouter(prefix="/api/v1", tags=["auth"])


class Me(BaseModel):
    crm_user_id: int
    full_name: str
    email: str
    permissions: list[str]


@router.get("/me", response_model=Me, operation_id="getMe")
async def get_me(employee: Annotated[Employee, Depends(require_permission())]) -> Me:
    return Me(
        crm_user_id=employee.crm_user_id,
        full_name=employee.full_name,
        email=employee.email,
        permissions=known_permissions(employee.permissions_eds),
    )
