"""Admin · Делегирование (СОТР-2): «Что делегировано» в карточке сотрудника (контракт: tag `admin`,
0.129.0).

Человек — сотрудник, должность — подпись, права — список действий, выданных лично. Права по-
прежнему считает CRM по
ролям, поэтому личный набор хранится служебной ролью CRM (`app/delegation.py`); BFF только
собирает её из выбранных
действий и назначает сотруднику. Менять делегирование может держатель раздела `admin` на запись;
выдать больше, чем есть у самого
выдающего, нельзя (403 `FORBIDDEN`, `details.reason = delegation_exceeds_own`), в том числе себе.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from app import delegation, rbac
from app.clients.crm_users import CrmRoles, CrmUsers
from app.deps import Authed, StepUpDep, require
from app.errors import PlatformError
from app.schemas_delegation import (
    DelegationAction,
    DelegationArea,
    DelegationCatalog,
    DelegationPreset,
    EmployeeDelegation,
    EmployeeDelegationUpdate,
)
from app.session import SessionData

router = APIRouter(tags=["admin"])

Reader = Annotated[Authed, Depends(require("admin", "read"))]
Writer = Annotated[Authed, Depends(require("admin", "full"))]
EmployeeId = Annotated[str, Path(pattern=r"^[1-9][0-9]*$")]


def _presets(roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in roles if not delegation.is_personal(r)]


def _held(user: dict[str, Any], roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {
        int(r["id"])
        for r in user.get("platform_role_refs") or []
        if isinstance(r, dict) and isinstance(r.get("id"), int)
    }
    return [r for r in roles if int(r["id"]) in ids]


def _current(user: dict[str, Any], roles: list[dict[str, Any]]) -> EmployeeDelegation:
    held = _held(user, roles)
    presets = [{"id": str(r["id"]), "name": str(r["name"])} for r in _presets(roles)]
    return EmployeeDelegation(
        codes=delegation.codes_on(delegation.merge_access(held)),
        suggested_preset_id=delegation.suggest_preset(user.get("position"), presets),
    )


@router.get(
    "/admin/delegation",
    response_model=DelegationCatalog,
    operation_id="getDelegationCatalog",
)
async def get_delegation_catalog(authed: Reader) -> DelegationCatalog:
    """Действия по областям и заготовки «набор по должности» (роли компании)."""
    catalog = delegation.catalog()
    roles = await CrmRoles(authed.call).list_all()
    return DelegationCatalog(
        areas=[DelegationArea(**a) for a in catalog["areas"]],
        actions=[DelegationAction(**c) for c in catalog["capabilities"]],
        presets=[
            DelegationPreset(
                id=str(r["id"]),
                name=str(r["name"]),
                codes=delegation.codes_on(delegation.merge_access([r])),
            )
            for r in _presets(roles)
        ],
    )


@router.get(
    "/admin/users/{id}/delegation",
    response_model=EmployeeDelegation,
    operation_id="getEmployeeDelegation",
)
async def get_employee_delegation(id: EmployeeId, authed: Reader) -> EmployeeDelegation:
    user = await CrmUsers(authed.call).get(id)
    return _current(user, await CrmRoles(authed.call).list_all())


def _expire_profile(data: SessionData) -> None:
    data.profile_checked_at = 0.0


@router.put(
    "/admin/users/{id}/delegation",
    response_model=EmployeeDelegation,
    operation_id="setEmployeeDelegation",
)
async def set_employee_delegation(
    id: EmployeeId,
    body: EmployeeDelegationUpdate,
    authed: Writer,
    step_up: StepUpDep = None,
) -> EmployeeDelegation:
    """Личный набор сотрудника — ровно выбранные действия; прочие разделы сохраняются."""
    users, roles_api = CrmUsers(authed.call), CrmRoles(authed.call)
    user = await users.get(id)
    roles = await roles_api.list_all()
    held = _held(user, roles)
    base = delegation.merge_access(held)
    try:
        wanted = delegation.known(body.codes)
    except ValueError as error:
        raise PlatformError(
            "VALIDATION_FAILED", str(error), status_code=422, details={"fields": ["codes"]}
        ) from error
    access = delegation.compose(wanted, base)
    if not access:
        raise PlatformError(
            "VALIDATION_FAILED",
            "Нужно оставить хотя бы одно действие.",
            status_code=422,
            details={"fields": ["codes"]},
        )
    over = delegation.exceeds(access, base, rbac.merge(authed.roles))
    if over:
        raise PlatformError(
            "FORBIDDEN",
            "Нельзя делегировать больше, чем есть у вас.",
            status_code=403,
            details={"reason": "delegation_exceeds_own", "resources": over},
        )
    if body.preset_id is None:
        fields = delegation.merge_fields(held)
    else:
        preset = next((r for r in _presets(roles) if str(r["id"]) == body.preset_id), None)
        if preset is None:
            raise PlatformError(
                "VALIDATION_FAILED",
                "Такого набора по должности нет.",
                status_code=422,
                details={"fields": ["preset_id"]},
            )
        fields = delegation.merge_fields([preset])
    marker = delegation.personal_marker(id)
    personal = next((r for r in roles if r.get("description") == marker), None)
    if personal is None:
        personal = await _create_personal(roles_api, user, marker, access, fields)
    elif (
        dict(personal.get("access") or {}) != access
        or list(personal.get("restricted_fields") or []) != fields
    ):
        personal = await roles_api.update(
            str(personal["id"]),
            {
                "version": int(personal.get("version") or 1),
                "access": access,
                "restricted_fields": fields,
            },
        )
    if {int(r["id"]) for r in held} != {int(personal["id"])}:
        payload: dict[str, Any] = {"platform_role_ids": [int(personal["id"])]}
        if body.transfer_to_user_id is not None:
            payload["transfer_to_user_id"] = int(body.transfer_to_user_id)
        user = await users.update(id, payload, step_up)
    else:
        user = await users.get(id)
    if int(id) == int(authed.data.user_id):
        await authed.service.store.update(authed.sid, _expire_profile)
    return _current(user, await roles_api.list_all())


async def _create_personal(
    roles_api: CrmRoles,
    user: dict[str, Any],
    marker: str,
    access: dict[str, str],
    fields: list[str],
) -> dict[str, Any]:
    name = str(user.get("full_name") or user.get("email") or marker).strip()
    title = f"{str(user.get('position') or '').strip() or 'Личный набор'} · {name}"[:120]
    payload = {
        "name": title,
        "description": marker,
        "access": access,
        "restricted_fields": fields,
    }
    try:
        return await roles_api.create(payload)
    except PlatformError as error:
        if error.status_code not in (409, 422):
            raise
        payload["name"] = f"{title[:100]} · №{marker[len(delegation.PERSONAL_PREFIX) :]}"
        return await roles_api.create(payload)
