"""«Что может человек» (ДОСТ-1, tag `admin`): сегодняшние права словами.

Карточка, таблица «Кто что может» и «Мои возможности». Только чтение: BFF ничего не выдаёт и не
решает. Роли и их матрицы — данные CRM, права подписи — EDS, зоны — CRM; здесь они складываются
по каталогу `platform-capabilities.yaml` (`app/capabilities.py`). Доступ: таблица и карточка
человека — раздел `admin` от чтения; «Мои возможности» — любой сотрудник про себя. Зоны и подпись
читаются тем, у кого есть на это раздел; иначе ответ честно говорит `zones_known` /
`signing_known = false`, а не «нет».
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from pydantic import ValidationError

from app.capability_views import (
    Extras,
    Person,
    RoleView,
    authorities_by_person,
    card,
    matrix,
    prepare,
    zones_by_person,
)
from app.clients.crm_users import CrmRoles, CrmUsers
from app.clients.crm_zones import CrmZones
from app.deps import Authed, AuthedDep, require
from app.eds_documents import API, EdsProxy
from app.errors import PlatformError, from_backend
from app.schemas import initials_of
from app.schemas_admin import deputy_of, role_refs, status_of
from app.schemas_capabilities import CapabilityMatrix, CapabilityPerson, EmployeeCapabilities
from app.schemas_eds_signing import to_authority
from app.schemas_profile import avatar_url

router = APIRouter(tags=["admin"])

Reader = Annotated[Authed, Depends(require("admin", "read"))]
EmployeeId = Annotated[str, Path(pattern=r"^[1-9][0-9]*$")]
SIGNING = f"{API}/signing/authorities"
ZONES = "/api/v1/responsibility-zones"


def _role_views(raw_roles: list[dict[str, Any]]) -> dict[int, RoleView]:
    return {
        int(r["id"]): RoleView(
            id=int(r["id"]),
            name=str(r["name"]),
            system=bool(r.get("is_system")),
            code=r.get("code") or None,
            access=dict(r.get("access") or {}),
            restricted_fields=list(r.get("restricted_fields") or []),
        )
        for r in raw_roles
    }


def _person(user: dict[str, Any], roles: dict[int, RoleView], names: dict[str, str]) -> Person:
    name = str(user.get("full_name") or "")
    held = [roles[int(ref.id)] for ref in role_refs(user) if int(ref.id) in roles]
    version = user.get("avatar_version")
    return Person(
        id=str(user["id"]),
        name=name,
        initials=initials_of(name, str(user["email"])),
        position=str(user.get("position") or "").strip() or None,
        avatar_url=avatar_url(user["id"], version if isinstance(version, int) else None),
        roles=held,
        deputy=deputy_of(user, names),
    )


async def _extras(authed: Authed, *, mine: bool = False) -> Extras:
    """Зоны (CRM) и подписи (EDS): `mine` — только свои записи, их читает любой сотрудник;
    иначе весь реестр (нужны `admin` и `eds.signing.manage`). Не прочиталось — «не известно»."""
    zones: dict[str, Any] = {}
    zones_known = False
    try:
        if mine:
            response = await authed.call("crm", "GET", f"{ZONES}/mine")
            if response.status_code != 200:
                raise from_backend("crm", response)
            raw_zones = response.json().get("items") or []
        else:
            raw_zones = await CrmZones(authed.call).list_all()
        zones = zones_by_person(raw_zones)
        zones_known = True
    except PlatformError:
        zones_known = False
    signing: dict[str, Any] = {}
    signing_known = False
    try:
        raw = await EdsProxy(authed.call).request(
            "GET",
            f"{API}/signing/mine" if mine else SIGNING,
            params=None if mine else {"status": "all"},
        )
        items = raw.get("items") if isinstance(raw, dict) else None
        if isinstance(items, list):
            signing = authorities_by_person(to_authority(item) for item in items)
            signing_known = True
    except (PlatformError, ValidationError):
        signing_known = False
    return Extras(
        signing_known=signing_known, signing=signing, zones_known=zones_known, zones=zones
    )


async def _grantors(authed: Authed) -> list[CapabilityPerson] | None:
    """Кто выдаёт возможности: действующие сотрудники с разделом `admin` на изменение (CRM, любому
    сотруднику: имя и должность). Не прочиталось — `None`, «не известно»."""
    try:
        response = await authed.call("crm", "GET", "/api/v1/team/granters")
    except PlatformError:
        return None
    if response.status_code != 200:
        return None
    people: list[CapabilityPerson] = []
    for row in response.json():
        name = str(row.get("full_name") or "")
        position = str(row.get("position") or "").strip()
        people.append(
            CapabilityPerson(
                id=str(row["id"]),
                name=name,
                initials=str(row.get("initials") or initials_of(name, name or "?")),
                **({"position": position} if position else {}),
            )
        )
    return people


async def _company(authed: Authed) -> tuple[list[Person], Extras]:
    """Действующие сотрудники с ролями (CRM) и подпись, зоны."""
    users = await CrmUsers(authed.call).list_all()
    roles = _role_views(await CrmRoles(authed.call).list_all())
    names = {str(u["id"]): str(u.get("full_name") or "") for u in users}
    people = [
        _person(u, roles, names) for u in users if status_of(u) != "disabled" and role_refs(u)
    ]
    people.sort(key=lambda p: (p.name.casefold(), p.id))
    return prepare(people), await _extras(authed)


def _today() -> Any:
    return datetime.now(UTC).date()


@router.get(
    "/admin/capabilities",
    response_model=CapabilityMatrix,
    response_model_exclude_none=True,
    operation_id="getCapabilityMatrix",
)
async def get_capability_matrix(authed: Reader) -> CapabilityMatrix:
    people, extras = await _company(authed)
    return matrix(people, extras, _today())


@router.get(
    "/admin/users/{id}/capabilities",
    response_model=EmployeeCapabilities,
    response_model_exclude_none=True,
    operation_id="getEmployeeCapabilities",
)
async def get_employee_capabilities(id: EmployeeId, authed: Reader) -> EmployeeCapabilities:
    people, extras = await _company(authed)
    found = next((p for p in people if p.id == id), None)
    if found is None:
        # Отключённого сотрудника в таблице нет, но карточка у него есть: считаем его отдельно.
        users = await CrmUsers(authed.call).list_all()
        roles = _role_views(await CrmRoles(authed.call).list_all())
        names = {str(u["id"]): str(u.get("full_name") or "") for u in users}
        user = next((u for u in users if str(u["id"]) == id), None)
        if user is None:
            raise PlatformError("NOT_FOUND", "Сотрудник не найден.", status_code=404)
        found = prepare([_person(user, roles, names)])[0]
    return card(found, people, extras, _today())


@router.get(
    "/me/capabilities",
    response_model=EmployeeCapabilities,
    response_model_exclude_none=True,
    operation_id="getMyCapabilities",
)
async def get_my_capabilities(authed: AuthedDep) -> EmployeeCapabilities:
    data = authed.data
    roles = [
        RoleView(
            id=r.id,
            name=r.name,
            system=r.system,
            code=r.code,
            access=dict(r.access),
            restricted_fields=list(r.restricted_fields),
        )
        for r in authed.roles
    ]
    deputy = None
    response = await authed.call("crm", "GET", "/api/v1/me")
    if response.status_code == 200:
        crm_me = response.json()
        who = crm_me.get("deputy_user_id")
        names = {str(who): str(crm_me.get("deputy_name") or "")} if who else {}
        deputy = deputy_of(crm_me, names)
    me = Person(
        id=str(data.user_id),
        name=data.name,
        initials=initials_of(data.name, data.email),
        position=data.position,
        avatar_url=avatar_url(data.user_id, data.avatar_version),
        roles=roles,
        deputy=deputy,
    )
    prepare([me])
    extras = await _extras(authed, mine=True)
    # Про себя: «Кто ещё может» и предупреждения по компании — не здесь (их видит администратор).
    return card(me, [me], extras, _today(), with_others=False, grantors=await _grantors(authed))
