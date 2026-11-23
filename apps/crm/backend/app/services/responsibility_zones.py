"""Реестр зон ответственности (ЕВ-З): список с проблемами, создание, назначение людей, выключение.

Проблемы зоны считаются при каждом чтении из фактов (`domain/responsibility_zones.py`): действует
ли ответственный и замещающий, есть ли у ответственного разделы зоны, не вышел ли срок. Каждое
изменение — запись в `audit_log` (`responsibility_zone.create|update|deactivate|activate`) с
«до/после».
Зоны не маршрутизируют уведомления и шаги согласования: это программа «Процессы как данные».
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from app.domain.platform_roles import RoleGrant, merge_access
from app.domain.platform_roles_generated import RESOURCE_KEYS
from app.domain.responsibility_zones import ZoneProblem, zone_problems
from app.models.auth import User
from app.models.responsibility_zones import ResponsibilityZone, zone_snapshot
from app.repositories import platform_roles as prepo
from app.repositories import responsibility_zones as repo
from app.repositories import users as users_repo
from app.security import audit
from app.security.audit import Actor
from app.services.user_platform import role_refs

TZ = ZoneInfo("Asia/Tashkent")

# Не передано в PATCH — не менять (в отличие от `None` — снять значение).
UNSET: object = object()


@dataclass(frozen=True, slots=True)
class PersonView:
    id: int
    name: str
    position: str | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class ZoneView:
    id: int
    code: str
    name: dict[str, str]
    description: dict[str, str]
    sections: list[str]
    responsible: PersonView | None
    deputy: PersonView | None
    curator: PersonView | None
    basis: str
    valid_from: date | None
    valid_to: date | None
    is_active: bool
    problems: list[ZoneProblem]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ZonePatch:
    """Изменения зоны; `UNSET` — не менять, `None` — снять."""

    responsible_user_id: object = UNSET
    deputy_user_id: object = UNSET
    curator_user_id: object = UNSET
    basis: object = UNSET
    valid_from: object = UNSET
    valid_to: object = UNSET


@dataclass(slots=True)
class _People:
    users: Mapping[int, User]
    access: Mapping[int, Mapping[str, str]] = field(default_factory=dict)


def today() -> date:
    return datetime.now(TZ).date()


def _person(users: Mapping[int, User], user_id: int | None) -> PersonView | None:
    user = users.get(user_id) if user_id is not None else None
    if user is None:
        return None
    return PersonView(user.id, user.full_name, user.position or None, user.is_active)


def _view(zone: ResponsibilityZone, people: _People, on: date) -> ZoneView:
    active = {uid for uid, user in people.users.items() if user.is_active}
    problems = zone_problems(
        is_active=zone.is_active,
        sections=zone.sections,
        responsible_id=zone.responsible_user_id,
        deputy_id=zone.deputy_user_id,
        valid_to=zone.valid_to,
        today=on,
        active_users=active,
        access_of=people.access,
    )
    return ZoneView(
        id=zone.id,
        code=zone.code,
        name={"ru": zone.name_ru, "uz": zone.name_uz, "en": zone.name_en},
        description={
            "ru": zone.description_ru,
            "uz": zone.description_uz,
            "en": zone.description_en,
        },
        sections=list(zone.sections),
        responsible=_person(people.users, zone.responsible_user_id),
        deputy=_person(people.users, zone.deputy_user_id),
        curator=_person(people.users, zone.curator_user_id),
        basis=zone.basis,
        valid_from=zone.valid_from,
        valid_to=zone.valid_to,
        is_active=zone.is_active,
        problems=problems,
        updated_at=zone.updated_at,
    )


async def _people(session: AsyncSession) -> _People:
    users = {u.id: u for u in await users_repo.list_users(session)}
    held = await prepo.roles_by_user(session)
    access = {
        uid: merge_access(RoleGrant(ref.access) for ref in role_refs(held.get(uid, [])))
        for uid in users
    }
    return _People(users, access)


def _checked_sections(sections: Sequence[str]) -> list[str]:
    unknown = [s for s in sections if s not in RESOURCE_KEYS]
    if unknown:
        raise ValidationFailedError(f"unknown section: {unknown[0]}", field="sections")
    return list(dict.fromkeys(sections))


async def _required(
    session: AsyncSession, zone_id: int, *, for_update: bool = False
) -> ResponsibilityZone:
    zone = await repo.get(session, zone_id, for_update=for_update)
    if zone is None:
        raise NotFoundError("responsibility zone not found")
    return zone


def _checked_person(
    users: Mapping[int, User], value: object, name: str, current: int | None = None
) -> int | None:
    if value is None:
        return None
    if value == current:
        # an unchanged assignment is not re-validated: a deactivated person already in the
        # zone must not block saving the basis, the term or another person
        return current
    user = users.get(value) if isinstance(value, int) else None
    if user is None or not user.is_active:
        raise ValidationFailedError("the employee is not found or inactive", field=name)
    return user.id


class ResponsibilityZoneService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_zones(self) -> list[ZoneView]:
        async with self._sessions() as session:
            people = await _people(session)
            on = today()
            return [_view(z, people, on) for z in await repo.list_zones(session)]

    async def get(self, zone_id: int) -> ZoneView:
        async with self._sessions() as session:
            zone = await _required(session, zone_id)
            return _view(zone, await _people(session), today())

    async def create(
        self,
        actor: Actor,
        code: str,
        name: Mapping[str, str],
        description: Mapping[str, str],
        sections: Sequence[str],
    ) -> ZoneView:
        checked = _checked_sections(sections)
        async with self._sessions() as session, session.begin():
            if await repo.by_code(session, code) is not None:
                raise ConflictError("zone code is taken", field="code")
            zone = ResponsibilityZone(
                code=code,
                name_ru=name["ru"].strip(),
                name_uz=name["uz"].strip(),
                name_en=name["en"].strip(),
                description_ru=description.get("ru", "").strip(),
                description_uz=description.get("uz", "").strip(),
                description_en=description.get("en", "").strip(),
                sections=checked,
                is_active=True,
                created_by=actor.user_id,
                updated_by=actor.user_id,
            )
            session.add(zone)
            await session.flush()
            await audit.record(
                session, actor, "responsibility_zone.create", "responsibility_zone", zone.id,
                after=zone_snapshot(zone),
            )  # fmt: skip
            await session.refresh(zone)
            return _view(zone, await _people(session), today())

    async def update(self, actor: Actor, zone_id: int, patch: ZonePatch) -> ZoneView:
        async with self._sessions() as session, session.begin():
            zone = await _required(session, zone_id, for_update=True)
            if not zone.is_active:
                raise ConflictError("the zone is deactivated: activate it first")
            people = await _people(session)
            before = zone_snapshot(zone)
            if patch.responsible_user_id is not UNSET:
                zone.responsible_user_id = _checked_person(
                    people.users,
                    patch.responsible_user_id,
                    "responsible_user_id",
                    zone.responsible_user_id,
                )
            if patch.deputy_user_id is not UNSET:
                zone.deputy_user_id = _checked_person(
                    people.users, patch.deputy_user_id, "deputy_user_id", zone.deputy_user_id
                )
            if patch.curator_user_id is not UNSET:
                zone.curator_user_id = _checked_person(
                    people.users, patch.curator_user_id, "curator_user_id", zone.curator_user_id
                )
            if zone.responsible_user_id is not None and (
                zone.responsible_user_id == zone.deputy_user_id
            ):
                raise ValidationFailedError(
                    "the deputy must be another employee", field="deputy_user_id"
                )
            if patch.basis is not UNSET:
                zone.basis = str(patch.basis or "").strip()
            if patch.valid_from is not UNSET:
                zone.valid_from = patch.valid_from  # type: ignore[assignment]
            if patch.valid_to is not UNSET:
                zone.valid_to = patch.valid_to  # type: ignore[assignment]
            if zone.valid_from and zone.valid_to and zone.valid_from > zone.valid_to:
                raise ValidationFailedError("the term is reversed", field="valid_to")
            after = zone_snapshot(zone)
            if before != after:
                zone.updated_by = actor.user_id
                await session.flush()
                await audit.record(
                    session, actor, "responsibility_zone.update", "responsibility_zone", zone.id,
                    before=before, after=after,
                )  # fmt: skip
            await session.refresh(zone)
            return _view(zone, people, today())

    async def set_active(self, actor: Actor, zone_id: int, active: bool) -> ZoneView:
        async with self._sessions() as session, session.begin():
            zone = await _required(session, zone_id, for_update=True)
            if zone.is_active != active:
                before = zone_snapshot(zone)
                zone.is_active = active
                zone.updated_by = actor.user_id
                await session.flush()
                await audit.record(
                    session, actor,
                    "responsibility_zone.activate" if active else "responsibility_zone.deactivate",
                    "responsibility_zone", zone.id,
                    before=before, after=zone_snapshot(zone),
                )  # fmt: skip
            await session.refresh(zone)
            return _view(zone, await _people(session), today())
