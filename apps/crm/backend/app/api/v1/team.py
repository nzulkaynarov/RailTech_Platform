"""Сотрудники для выбора (SPEC §10.1; D1-8, B-007): кому передать лида, исполнители раздела.

`GET /team` без параметров — активные менеджеры и админы (базовая роль CRM): кому передать лида;
право `leads:read`. `GET /team?section=<раздел>&level=full|read` — активные сотрудники, у которых
объединение матриц ролей даёт раздел каталога на уровне (зона резолюции, визы): право — чтение
сотрудников по каталогу (`users:read`, раздел `admin` не ниже чтения), как у директора. Список
раскрывает, у кого какой раздел, поэтому открыт тем, кто и так видит сотрудников; ответ — только id,
имя, инициалы и должность, без почты, телефона и ролей.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import ContainerDep, PrincipalDep, get_rbac, require
from app.domain.errors import ValidationFailedError
from app.schemas.leads import TeamMember
from app.security.principal import Principal
from app.security.rbac import Rbac
from app.services import team as team_service

router = APIRouter(prefix="/api/v1", tags=["leads"])

SECTION_DESCRIPTION = (
    "Раздел каталога (`erp.calc.goods`, `eds.payments`, …): сотрудники с этим разделом. "
    "Нужен `level`. "
    "Право — чтение сотрудников (`users:read`, раздел `admin` не ниже чтения); без `section` — "
    "`leads:read`. Раздела нет в каталоге — 422."
)

_leads_reader = require("leads", "read")
_directory_reader = require("users", "read")


async def team_reader(
    principal: PrincipalDep,
    rbac: Annotated[Rbac, Depends(get_rbac)],
    section: Annotated[str | None, Query(max_length=64, description=SECTION_DESCRIPTION)] = None,
) -> Principal:
    """Право зависит от режима: список для передачи — `leads:read`, по разделу — `users:read`."""
    check = _directory_reader if section is not None else _leads_reader
    return await check(principal, rbac)


@router.get("/team", response_model=list[TeamMember])
async def team(
    _: Annotated[Principal, Depends(team_reader)],
    container: ContainerDep,
    section: Annotated[str | None, Query(max_length=64, description=SECTION_DESCRIPTION)] = None,
    level: Annotated[
        Literal["full", "read"] | None,
        Query(description="Уровень раздела не ниже: `full` или `read` (`full` ⊇ `read`)."),
    ] = None,
) -> list[TeamMember]:
    """Менеджеры и админы (без `section`) либо сотрудники раздела каталога (с `section`)."""
    if (section is None) != (level is None):
        raise ValidationFailedError(
            "section and level are given together", field="level" if section else "section"
        )
    async with container.session_factory() as session:
        if section is None or level is None:
            return await team_service.workers(session)
        return await team_service.by_section(session, section, level)
