"""Роли Платформы как данные: создание, изменение, удаление и предпросмотр (ADR-0012, R-1).

Роль — матрица `access` и `restricted_fields`; права сотрудника — объединение его ролей
(`domain/platform_roles.py`). Изменение роли в одной транзакции: сама роль, правила casbin
`pr:<id>`, роли CRM держателей (для старого фронта), аудит. После коммита каждому затронутому
сотруднику с доступом к ERP ставится задача провижининга (итог — `erp_sync` в карточке).
Системные роли («Администратор», «Директор») неизменны; роль с сотрудниками не удаляется.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.bus import snapshots
from app.domain.errors import (
    ConflictError,
    LastAdminError,
    NotFoundError,
    RoleInUseError,
    RoleSystemError,
    RoleVersionConflictError,
    ValidationFailedError,
)
from app.domain.platform_roles import (
    RoleGrant,
    check_spec,
    derive_access,
    diff_access,
    role_subject,
)
from app.models.platform_roles import PlatformRole, role_snapshot
from app.repositories import platform_roles as repo
from app.repositories import users as users_repo
from app.security import audit
from app.security.audit import Actor
from app.services.erp_enqueue import ErpSyncEnqueue, enqueue_sync
from app.services.platform_policies import write_role_policies
from app.services.user_platform import grants_of

NAME_MAX_LEN = 120


@dataclass(frozen=True, slots=True)
class RoleView:
    id: int
    code: str | None
    name: str
    description: str
    is_system: bool
    version: int
    access: dict[str, str]
    restricted_fields: list[str]
    employees: int
    created_by: int | None
    updated_by: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RolePatch:
    """Изменения роли; `None` — не менять."""

    version: int
    name: str | None = None
    description: str | None = None
    access: Mapping[str, str] | None = None
    restricted_fields: Sequence[str] | None = None


@dataclass(frozen=True, slots=True)
class EmployeeImpact:
    user_id: int
    full_name: str
    is_active: bool
    gained: list[tuple[str, str]]
    lost: list[tuple[str, str]]
    fields_gained: list[str]
    fields_lost: list[str]
    erp_gained: list[str]
    erp_lost: list[str]


@dataclass(frozen=True, slots=True)
class Preview:
    """Блок «Что произойдёт»: кто из сотрудников что получит и потеряет."""

    role_id: int | None
    employees_total: int
    employees: list[EmployeeImpact] = field(default_factory=list)
    gained: list[tuple[str, str]] = field(default_factory=list)
    lost: list[tuple[str, str]] = field(default_factory=list)
    fields_gained: list[str] = field(default_factory=list)
    fields_lost: list[str] = field(default_factory=list)


def _view(role: PlatformRole, employees: int) -> RoleView:
    return RoleView(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        version=role.version,
        access=dict(role.access),
        restricted_fields=list(role.restricted_fields),
        employees=employees,
        created_by=role.created_by,
        updated_by=role.updated_by,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


def _checked_name(value: str) -> str:
    name = " ".join(value.split())
    if not name or len(name) > NAME_MAX_LEN:
        raise ValidationFailedError(f"name must be 1..{NAME_MAX_LEN} characters", field="name")
    return name


def _checked_spec(
    access: Mapping[str, str], fields: Sequence[str]
) -> tuple[dict[str, str], list[str]]:
    try:
        return check_spec(access, fields)
    except ValueError as exc:
        text = str(exc)
        field_name = "restricted_fields" if "field" in text else "access"
        raise ValidationFailedError(text, field=field_name) from exc


class PlatformRoleService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], erp_sync: ErpSyncEnqueue | None = None
    ) -> None:
        self._sessions = sessions
        self._erp_sync = erp_sync

    async def list_roles(self) -> list[RoleView]:
        async with self._sessions() as session:
            counts = await repo.member_counts(session)
            return [_view(r, counts.get(r.id, 0)) for r in await repo.list_roles(session)]

    async def get(self, role_id: int) -> RoleView:
        async with self._sessions() as session:
            role = await _required(session, role_id)
            return _view(role, len(await repo.user_ids_of_role(session, role_id)))

    async def create(
        self,
        actor: Actor,
        name: str,
        description: str,
        access: Mapping[str, str],
        restricted_fields: Sequence[str],
    ) -> RoleView:
        title = _checked_name(name)
        spec_access, spec_fields = _checked_spec(access, restricted_fields)
        async with self._sessions() as session, session.begin():
            if await repo.name_taken(session, title):
                raise ConflictError("role name is taken", field="name")
            role = PlatformRole(
                code=None,
                name=title,
                description=description.strip(),
                is_system=False,
                access=spec_access,
                restricted_fields=spec_fields,
                created_by=actor.user_id,
                updated_by=actor.user_id,
            )
            session.add(role)
            await session.flush()
            await write_role_policies(session, role.id, spec_access)
            await audit.record(
                session, actor, "platform_role.create", "platform_role", role.id,
                after=role_snapshot(role),
            )  # fmt: skip
            await session.refresh(role)
            return _view(role, 0)

    async def update(self, actor: Actor, role_id: int, patch: RolePatch) -> RoleView:
        async with self._sessions() as session, session.begin():
            await users_repo.lock_admin_set(session)
            role = await _required(session, role_id, for_update=True)
            if role.is_system:
                raise RoleSystemError("a system role cannot be changed")
            if role.version != patch.version:
                raise RoleVersionConflictError(
                    "the role was changed by someone else: reload it", current=role.version
                )
            before = role_snapshot(role)
            holders = await repo.user_ids_of_role(session, role_id)
            eds_before = await _eds_of(session, holders)
            await self._apply(session, role, patch, actor)
            after = role_snapshot(role)
            access_changed = (before["access"], before["restricted_fields"]) != (
                after["access"],
                after["restricted_fields"],
            )
            if access_changed:
                await write_role_policies(session, role_id, role.access)
                await _recompute_holders(session, actor, holders)
                await _publish_eds_changes(session, actor, holders, eds_before)
            if before != after:
                role.version += 1
                await session.flush()
                await audit.record(
                    session, actor, "platform_role.update", "platform_role", role_id,
                    before=before, after=after,
                )  # fmt: skip
            await session.refresh(role)
            view = _view(role, len(holders))
            to_sync = await _erp_targets(session, holders) if access_changed else []
        for user_id in to_sync:
            await enqueue_sync(self._sessions, self._erp_sync, "provision", user_id)
        return view

    async def _apply(
        self, session: AsyncSession, role: PlatformRole, patch: RolePatch, actor: Actor
    ) -> None:
        if patch.name is not None:
            title = _checked_name(patch.name)
            if await repo.name_taken(session, title, excluding=role.id):
                raise ConflictError("role name is taken", field="name")
            role.name = title
        if patch.description is not None:
            role.description = patch.description.strip()
        if patch.access is not None or patch.restricted_fields is not None:
            access, fields = _checked_spec(
                role.access if patch.access is None else patch.access,
                role.restricted_fields
                if patch.restricted_fields is None
                else patch.restricted_fields,
            )
            role.access, role.restricted_fields = access, fields
        role.updated_by = actor.user_id
        await session.flush()

    async def delete(self, actor: Actor, role_id: int) -> None:
        async with self._sessions() as session, session.begin():
            role = await _required(session, role_id, for_update=True)
            if role.is_system:
                raise RoleSystemError("a system role cannot be deleted")
            holders = await repo.user_ids_of_role(session, role_id)
            if holders:
                raise RoleInUseError(
                    "the role is assigned to employees: reassign them first", users=len(holders)
                )
            before = role_snapshot(role)
            await repo.delete_policies(session, [role_subject(role_id)])
            await session.delete(role)
            await audit.record(
                session, actor, "platform_role.delete", "platform_role", role_id, before=before
            )

    async def preview(
        self,
        role_id: int | None,
        access: Mapping[str, str] | None,
        restricted_fields: Sequence[str] | None,
    ) -> Preview:
        """Последствия сохранения роли: для каждого её сотрудника — что получит и потеряет.

        Новая роль (без `role_id`) никого не затрагивает; системную роль менять нельзя (409)."""
        async with self._sessions() as session:
            if role_id is None:
                _checked_spec(access or {}, restricted_fields or [])
                return Preview(role_id=None, employees_total=0)
            role = await _required(session, role_id)
            if role.is_system:
                raise RoleSystemError("a system role cannot be changed")
            draft_access, draft_fields = _checked_spec(
                role.access if access is None else access,
                role.restricted_fields if restricted_fields is None else restricted_fields,
            )
            draft = RoleGrant(draft_access, tuple(draft_fields), role.code)
            return await _impact(session, role, draft)


async def _required(
    session: AsyncSession, role_id: int, *, for_update: bool = False
) -> PlatformRole:
    role = await repo.get(session, role_id, for_update=for_update)
    if role is None:
        raise NotFoundError("platform role not found")
    return role


async def _recompute_holders(session: AsyncSession, actor: Actor, holders: Sequence[int]) -> None:
    """Роли CRM держателей по новой матрице (старый фронт до T4); админов остаётся ≥ 1."""
    for user_id in holders:
        user = await users_repo.get(session, user_id, for_update=True)
        if user is None:
            continue
        roles = await repo.roles_of_user(session, user_id)
        derived = derive_access(grants_of(roles))
        current = await users_repo.roles_of(session, user_id)
        if current == [derived.crm_role]:
            continue
        await users_repo.set_roles(session, user_id, [derived.crm_role], actor.user_id)
        await audit.record(
            session, actor, "user.update", "user", user_id,
            before={"roles": current}, after={"roles": [derived.crm_role]},
        )  # fmt: skip
    if holders and await users_repo.count_active_admins(session) == 0:
        raise LastAdminError("the change would leave the company without an active admin")


async def _eds_of(session: AsyncSession, user_ids: Sequence[int]) -> dict[int, list[str]]:
    """Права EDS держателей роли сейчас (по матрицам ролей в базе и сессии)."""
    result: dict[int, list[str]] = {}
    for user_id in user_ids:
        user = await users_repo.get(session, user_id)
        if user is None:
            continue
        roles = await repo.roles_of_user(session, user_id)
        result[user_id] = snapshots.eds_permissions(roles, is_active=bool(user.is_active))
    return result


async def _publish_eds_changes(
    session: AsyncSession,
    actor: Actor,
    holders: Sequence[int],
    before: Mapping[int, list[str]],
) -> None:
    """`identity.user.updated` (`changed_fields = ["permissions"]`) каждому держателю роли,
    у кого права EDS изменились; у кого не изменились — события нет. Та же транзакция (outbox)."""
    after = await _eds_of(session, holders)
    for user_id in holders:
        if user_id not in after or after[user_id] == before.get(user_id):
            continue
        user = await users_repo.get(session, user_id)
        if user is not None:
            await bus_events.user_updated(session, user, actor, ["permissions"])


async def _erp_targets(session: AsyncSession, holders: Sequence[int]) -> list[int]:
    """Держатели роли, которым нужен повторный провижининг: активные, с доступом к ERP."""
    targets = []
    for user_id in holders:
        user = await users_repo.get(session, user_id)
        if user is not None and user.is_active and "erp" in (user.platform_access or []):
            targets.append(user_id)
    return targets


async def _impact(session: AsyncSession, role: PlatformRole, draft: RoleGrant) -> Preview:
    holders = await repo.user_ids_of_role(session, role.id)
    employees: list[EmployeeImpact] = []
    gained: dict[tuple[str, str], None] = {}
    lost: dict[tuple[str, str], None] = {}
    fields_gained: dict[str, None] = {}
    fields_lost: dict[str, None] = {}
    for user_id in holders:
        user = await users_repo.get(session, user_id)
        if user is None:
            continue
        roles = await repo.roles_of_user(session, user_id)
        now = derive_access(grants_of(roles))
        after_grants = [draft if r.id == role.id else grants_of([r])[0] for r in roles]
        then = derive_access(after_grants)
        diff = diff_access(now.access, then.access, now.restricted_fields, then.restricted_fields)
        erp_now, erp_then = set(now.erp_permissions), set(then.erp_permissions)
        impact = EmployeeImpact(
            user_id=user_id,
            full_name=user.full_name,
            is_active=user.is_active,
            gained=diff.gained,
            lost=diff.lost,
            fields_gained=diff.fields_gained,
            fields_lost=diff.fields_lost,
            erp_gained=[p for p in then.erp_permissions if p not in erp_now],
            erp_lost=[p for p in now.erp_permissions if p not in erp_then],
        )
        if not (
            impact.gained or impact.lost or impact.fields_gained or impact.fields_lost
            or impact.erp_gained or impact.erp_lost
        ):  # fmt: skip
            continue
        employees.append(impact)
        gained.update(dict.fromkeys(impact.gained))
        lost.update(dict.fromkeys(impact.lost))
        fields_gained.update(dict.fromkeys(impact.fields_gained))
        fields_lost.update(dict.fromkeys(impact.fields_lost))
    return Preview(
        role_id=role.id,
        employees_total=len(holders),
        employees=employees,
        gained=list(gained),
        lost=list(lost),
        fields_gained=list(fields_gained),
        fields_lost=list(fields_lost),
    )
