"""Пользователи CRM (SPEC §5.1, §10.1): создание с временным паролем, роли, деактивация.

Инвариант: всегда есть хотя бы один активный admin — нарушение → `LastAdminError` (409).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import (
    ActiveLeadsError,
    ConflictError,
    LastAdminError,
    NotFoundError,
    Reason,
    ValidationFailedError,
)
from app.domain.lead_access import loses_work_role
from app.models.auth import RefreshToken, User
from app.models.clients import Client
from app.models.deals import Deal
from app.models.leads import Lead
from app.repositories import users as repo
from app.security import audit, reauth
from app.security.audit import Actor
from app.security.passwords import (
    WeakPasswordError,
    hash_password,
    temporary_password,
    validate_new_password,
    verify_password,
)
from app.services.user_parts import check_roles, normalize_email


@dataclass(frozen=True, slots=True)
class UserView:
    id: int
    email: str
    full_name: str
    roles: list[str]
    is_active: bool
    tg_user_id: int | None
    must_change_password: bool
    ui_mode: str
    notify_system: bool = True
    notify_leads: bool = True
    tg_dm_failed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UserPatch:
    full_name: str | None = None
    roles: list[str] | None = None
    is_active: bool | None = None
    tg_user_id: int | None = None
    clear_tg_user_id: bool = False
    transfer_to_user_id: int | None = None


class UserService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        lockout: reauth.LockoutPolicy | None = None,
    ) -> None:
        self._sessions = sessions
        self._lockout = lockout or reauth.LockoutPolicy()

    async def list_all(self) -> list[UserView]:
        async with self._sessions() as session:
            users = await repo.list_users(session)
            roles = await repo.roles_by_user(session)
        return [_view(u, roles.get(u.id, [])) for u in users]

    async def get(self, user_id: int) -> UserView:
        async with self._sessions() as session:
            user = await repo.get(session, user_id)
            if user is None:
                raise NotFoundError("user not found")
            return _view(user, await repo.roles_of(session, user_id))

    async def create(
        self, actor: Actor, email: str, full_name: str, roles: Sequence[str]
    ) -> tuple[UserView, str]:
        """Новый пользователь и временный пароль (показывается один раз)."""
        check_roles(roles)
        password = temporary_password()
        async with self._sessions() as session, session.begin():
            user = User(
                email=normalize_email(email),
                full_name=full_name.strip(),
                password_hash=hash_password(password),
                must_change_password=True,
                ui_mode="admin" if "admin" in roles else "manager",
            )
            session.add(user)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ConflictError(
                    "email already registered", reason=Reason.EMAIL_TAKEN, field="email"
                ) from exc
            await repo.set_roles(session, user.id, roles, actor.user_id)
            view = _view(user, sorted(roles))
            await audit.record(session, actor, "user.create", "user", user.id, after=_audit(view))
        return view, password

    async def update(self, actor: Actor, user_id: int, patch: UserPatch) -> UserView:
        if patch.roles is not None:
            check_roles(patch.roles)
        async with self._sessions() as session, session.begin():
            await repo.lock_admin_set(session)
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            roles = await repo.roles_of(session, user_id)
            before = _view(user, roles)
            loses_admin = "admin" in roles and (
                (patch.roles is not None and "admin" not in patch.roles) or patch.is_active is False
            )
            if loses_admin and await repo.count_active_admins(session, excluding=user_id) == 0:
                raise LastAdminError("the last active admin cannot lose the admin role")
            _apply(user, patch)
            if patch.roles is not None:
                await repo.set_roles(session, user_id, patch.roles, actor.user_id)
                roles = sorted(patch.roles)
                if "admin" not in roles:
                    user.ui_mode = "manager"
            stops_work = patch.roles is not None and loses_work_role(before.roles, patch.roles)
            if patch.is_active is False or stops_work:
                await _hand_over_work(session, actor, user_id, patch.transfer_to_user_id)
            if patch.is_active is False:
                await revoke_tokens(session, user_id)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ConflictError(
                    "telegram already linked", reason=Reason.TELEGRAM_TAKEN, field="tg_user_id"
                ) from exc
            after = _view(user, roles)
            await audit.record(
                session,
                actor,
                "user.update",
                "user",
                user_id,
                before=_audit(before),
                after=_audit(after),
            )
        return after

    async def reset_password(self, actor: Actor, user_id: int) -> str:
        password = temporary_password()
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            user.password_hash = hash_password(password)
            user.must_change_password = True
            user.failed_logins = 0
            user.locked_until = None
            await revoke_tokens(session, user_id)
            await audit.record(session, actor, "user.reset_password", "user", user_id)
        return password

    async def change_password(self, actor: Actor, user_id: int, current: str, new: str) -> None:
        # Lockout как у входа (аудит P0-4): счётчик коммитится, ошибка — после транзакции.
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            failure = reauth.check(
                user, current, datetime.now(UTC), self._lockout, field="current_password"
            )
        if failure is not None:
            raise failure
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            if verify_password(user.password_hash, new):
                raise ValidationFailedError(
                    "new password must differ",
                    reason=Reason.SAME_PASSWORD,
                    field="new_password",
                )
            try:
                validate_new_password(new, email=user.email)
            except WeakPasswordError as exc:
                raise ValidationFailedError(
                    str(exc), reason=Reason.WEAK_PASSWORD, field="new_password"
                ) from exc
            user.password_hash = hash_password(new)
            user.must_change_password = False
            await audit.record(session, actor, "user.change_password", "user", user_id)

    async def set_ui_mode(self, actor: Actor, user_id: int, mode: str) -> UserView:
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            roles = await repo.roles_of(session, user_id)
            if mode == "admin" and "admin" not in roles:
                raise ValidationFailedError("admin mode requires the admin role", field="ui_mode")
            user.ui_mode = mode
            return _view(user, roles)

    async def set_notify(
        self, actor: Actor, user_id: int, *, system: bool | None, leads: bool | None
    ) -> UserView:
        """Подписки на личные уведомления от бота (Q-010) — меняет только сам пользователь."""
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            before = {"notify_system": user.notify_system, "notify_leads": user.notify_leads}
            if system is not None:
                user.notify_system = system
            if leads is not None:
                user.notify_leads = leads
            after = {"notify_system": user.notify_system, "notify_leads": user.notify_leads}
            if after != before:
                await audit.record(
                    session, actor, "user.notify", "user", user_id, before=before, after=after
                )
            return _view(user, await repo.roles_of(session, user_id))

    async def bootstrap_admin(self, email: str, full_name: str, password: str | None) -> str:
        """Первый админ (scripts/create_admin.py). Возвращает пароль (временный, если не задан)."""
        actor = Actor.system()
        secret = password or temporary_password()
        if password:
            _check_password(password, email)
        async with self._sessions() as session, session.begin():
            user_id = await _upsert_admin(session, email, full_name, secret, password is None)
            await audit.record(session, actor, "user.bootstrap_admin", "user", user_id)
        return secret

    async def create_first_admin(
        self, email: str, full_name: str, password: str, actor: Actor
    ) -> int:
        """Админ из мастера первого запуска: только пока нет ни одного активного админа.

        Блокировка роли admin сериализует параллельные попытки; вторая получит 409.
        """
        _check_password(password, email)
        async with self._sessions() as session, session.begin():
            await repo.lock_admin_set(session)
            if await repo.count_active_admins(session) > 0:
                raise ConflictError("admin already exists", reason=Reason.SETUP_DONE)
            try:
                user_id = await _upsert_admin(session, email, full_name.strip(), password, False)
            except IntegrityError as exc:
                raise ConflictError("admin already exists", reason=Reason.SETUP_DONE) from exc
            await audit.record(
                session, actor, "setup.admin_created", "user", user_id, after={"email": email}
            )
        return user_id


def _check_password(password: str, email: str) -> None:
    try:
        validate_new_password(password, email=email)
    except WeakPasswordError as exc:
        raise ValidationFailedError(
            str(exc), reason=Reason.WEAK_PASSWORD, field="password"
        ) from exc


async def _upsert_admin(
    session: AsyncSession, email: str, full_name: str, secret: str, temporary: bool
) -> int:
    user = await repo.by_email(session, email, for_update=True)
    if user is None:
        user = User(email=normalize_email(email), full_name=full_name, password_hash="")
        session.add(user)
        await session.flush()
    user.password_hash = hash_password(secret)
    user.must_change_password = temporary
    user.is_active = True
    user.ui_mode = "admin"
    user.failed_logins, user.locked_until = 0, None
    roles = set(await repo.roles_of(session, user.id)) | {"admin"}
    await repo.set_roles(session, user.id, sorted(roles), None)
    return user.id


def _apply(user: User, patch: UserPatch) -> None:
    if patch.full_name is not None:
        user.full_name = patch.full_name.strip()
    if patch.is_active is not None:
        user.is_active = patch.is_active
    if patch.clear_tg_user_id:
        user.tg_user_id = None
    elif patch.tg_user_id is not None:
        user.tg_user_id = patch.tg_user_id


async def _hand_over_work(
    session: AsyncSession, actor: Actor, user_id: int, to_user_id: int | None
) -> None:
    """Лиды в работе и клиенты уходящего менеджера — коллеге; без коллеги деактивация запрещена."""
    leads = list(
        await session.scalars(
            select(Lead.id).where(
                Lead.assigned_user_id == user_id,
                Lead.owner_mode == "human",
                Lead.erased_at.is_(None),
            )
        )
    )
    if to_user_id is None:
        if leads:
            raise ActiveLeadsError("hand over the leads first", count=len(leads))
        await _reassign(session, user_id, None)  # лиды у бота и сделки — в общую очередь
        return
    target = await repo.get(session, to_user_id)
    roles = await repo.roles_of(session, to_user_id) if target else []
    inactive = target is None or to_user_id == user_id or not target.is_active
    if inactive or not {"manager", "admin"} & set(roles):
        raise ValidationFailedError(
            "choose an active colleague",
            reason=Reason.INACTIVE_COLLEAGUE,
            field="transfer_to_user_id",
        )
    await _reassign(session, user_id, to_user_id)
    await session.execute(
        update(Client).where(Client.owner_user_id == user_id).values(owner_user_id=to_user_id)
    )
    await audit.record(
        session,
        actor,
        "user.hand_over",
        "user",
        user_id,
        after={"to_user_id": to_user_id, "active_leads": leads},
    )


async def _reassign(session: AsyncSession, user_id: int, to_user_id: int | None) -> None:
    """Все лиды с ответственным (и у бота — клиенты после сделки) и открытые сделки."""
    await session.execute(
        update(Lead)
        .where(Lead.assigned_user_id == user_id, Lead.erased_at.is_(None))
        .values(assigned_user_id=to_user_id)
    )
    await session.execute(
        update(Deal)
        .where(Deal.owner_user_id == user_id, Deal.stage == "open")
        .values(owner_user_id=to_user_id)
    )


async def revoke_tokens(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def _view(user: User, roles: list[str]) -> UserView:
    return UserView(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        roles=roles,
        is_active=user.is_active,
        tg_user_id=user.tg_user_id,
        must_change_password=user.must_change_password,
        ui_mode=user.ui_mode,
        notify_system=user.notify_system,
        notify_leads=user.notify_leads,
        tg_dm_failed_at=user.tg_dm_failed_at,
    )


def _audit(view: UserView) -> dict[str, object]:
    return {
        "email": view.email,
        "full_name": view.full_name,
        "roles": view.roles,
        "is_active": view.is_active,
        "tg_user_id": view.tg_user_id,
    }
