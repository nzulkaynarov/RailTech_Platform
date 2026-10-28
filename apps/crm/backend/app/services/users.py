"""Пользователи CRM (SPEC §5.1, §10.1): создание с временным паролем, роли, деактивация.

Инвариант: всегда есть хотя бы один активный admin — нарушение → `LastAdminError` (409).
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.bus import snapshots
from app.domain.erp_roles import normalize_erp_roles
from app.domain.erp_sync import AccessState, SyncAction, access_audit_action, sync_action
from app.domain.errors import (
    ConflictError,
    LastAdminError,
    NotFoundError,
    Reason,
    ValidationFailedError,
)
from app.domain.lead_access import loses_work_role
from app.domain.platform_roles import derive_access
from app.models.auth import RefreshToken, User
from app.models.platform_roles import PlatformRole
from app.repositories import platform_roles as prepo
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
from app.services.erp_enqueue import ErpSyncEnqueue, enqueue_sync
from app.services.user_handover import hand_over_work
from app.services.user_parts import check_roles, normalize_email
from app.services.user_platform import (
    ADMIN_CODE,
    checked_position,
    grants_of,
    guard_system_holders,
    resolve_patch,
    resolve_requested,
)
from app.services.user_views import (
    UserPatch,
    UserView,
    access_state_of,
    audit_of,
    view_of,
)

__all__ = [
    "ErpSyncEnqueue",
    "UserPatch",
    "UserService",
    "UserView",
    "close_sessions",
    "revoke_tokens",
]

logger = structlog.get_logger(__name__)


class UserService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        lockout: reauth.LockoutPolicy | None = None,
        erp_sync: ErpSyncEnqueue | None = None,
    ) -> None:
        self._sessions = sessions
        self._lockout = lockout or reauth.LockoutPolicy()
        self._erp_sync = erp_sync

    async def list_all(self) -> list[UserView]:
        async with self._sessions() as session:
            users = await repo.list_users(session)
            roles = await repo.roles_by_user(session)
            platform = await prepo.roles_by_user(session)
            pending = await repo.erp_sync_pending_ids(session)
        return [
            view_of(u, roles.get(u.id, []), platform.get(u.id, []), erp_pending=u.id in pending)
            for u in users
        ]

    async def get(self, user_id: int) -> UserView:
        async with self._sessions() as session:
            user = await repo.get(session, user_id)
            if user is None:
                raise NotFoundError("user not found")
            return await _loaded_view(session, user)

    async def create(
        self,
        actor: Actor,
        email: str,
        full_name: str,
        roles: Sequence[str],
        *,
        platform_role_ids: Sequence[int] | None = None,
        position: str | None = None,
    ) -> tuple[UserView, str]:
        """Новый пользователь и временный пароль (показывается один раз).

        Непустые роли Платформы вычисляют роль CRM и доступ к ERP; `roles` тогда игнорируются,
        а выдача доступа ставит провижининг в очередь.
        """
        password = temporary_password()
        async with self._sessions() as session, session.begin():
            platform = await resolve_requested(session, platform_role_ids)
            derived = derive_access(grants_of(platform)) if platform else None
            roles = [derived.crm_role] if derived else list(roles)
            check_roles(roles)
            user = User(
                email=normalize_email(email),
                full_name=full_name.strip(),
                password_hash=hash_password(password),
                must_change_password=True,
                ui_mode="admin" if "admin" in roles else "manager",
                position=checked_position(position),
            )
            if derived:
                user.platform_access = list(derived.platform_access)
                user.erp_role_codes = list(derived.erp_role_codes)
            session.add(user)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ConflictError(
                    "email already registered", reason=Reason.EMAIL_TAKEN, field="email"
                ) from exc
            await repo.set_roles(session, user.id, roles, actor.user_id)
            if platform:
                await prepo.set_user_roles(
                    session, user.id, [r.id for r in platform], actor.user_id
                )
            view = view_of(user, sorted(roles), platform or [], erp_pending=bool(derived))
            await audit.record(session, actor, "user.create", "user", user.id, after=audit_of(view))
            await bus_events.user_created(session, user, actor)
            if derived:
                await _audit_access(session, actor, user.id, _NEW_USER_STATE, access_state_of(view))
        if derived:
            await self._sync_erp("provision", view.id)
        return view, password

    async def update(self, actor: Actor, user_id: int, patch: UserPatch) -> UserView:
        if patch.roles is not None:
            check_roles(patch.roles)
        position = None if patch.position is None else (checked_position(patch.position) or "")
        patch = replace(patch, position=position)
        async with self._sessions() as session, session.begin():
            await repo.lock_admin_set(session)
            await prepo.lock_system_roles(session)
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            roles = await repo.roles_of(session, user_id)
            held = await prepo.roles_of_user(session, user_id)
            before = view_of(user, roles, held)
            fields_before = snapshots.user_fields(user, held)
            erp_before = access_state_of(before)
            requested = await resolve_requested(session, patch.platform_role_ids)
            await guard_system_holders(
                session,
                user_id=user_id,
                user_active=user.is_active,
                held=held,
                requested=requested,
                deactivating=patch.is_active is False,
            )
            patch = resolve_patch(held, requested, patch)
            if patch.roles is not None:
                check_roles(patch.roles)
            new_roles = None if patch.roles is None else sorted(set(patch.roles))
            roles_changed = new_roles is not None and new_roles != roles
            loses_admin = "admin" in roles and (
                (new_roles is not None and "admin" not in new_roles) or patch.is_active is False
            )
            if loses_admin and await repo.count_active_admins(session, excluding=user_id) == 0:
                raise LastAdminError("the last active admin cannot lose the admin role")
            _apply(user, patch)
            if requested is not None:
                await prepo.set_user_roles(
                    session, user_id, [r.id for r in requested], actor.user_id
                )
            if new_roles is not None and roles_changed:
                await repo.set_roles(session, user_id, new_roles, actor.user_id)
                roles = new_roles
                if "admin" not in roles:
                    user.ui_mode = "manager"
            stops_work = roles_changed and loses_work_role(before.roles, roles)
            if patch.is_active is False or stops_work:
                await hand_over_work(session, actor, user_id, patch.transfer_to_user_id)
            if patch.is_active is False:
                await revoke_tokens(session, user_id)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ConflictError(
                    "telegram already linked", reason=Reason.TELEGRAM_TAKEN, field="tg_user_id"
                ) from exc
            effective = held if requested is None else requested
            after = view_of(user, roles, effective)
            changed = snapshots.changed_user_fields(
                fields_before, snapshots.user_fields(user, effective)
            )
            await audit.record(
                session,
                actor,
                "user.update",
                "user",
                user_id,
                before=audit_of(before),
                after=audit_of(after),
            )
            erp_after = access_state_of(after)
            await _audit_access(session, actor, user_id, erp_before, erp_after)
            await _publish_change(session, actor, user, before, after, changed)
            action = sync_action(erp_before, erp_after)
        await self._sync_erp(action, user_id)
        if action == "provision":
            after = replace(after, erp_sync="error" if after.erp_sync_error else "pending")
        return after

    async def _sync_erp(self, action: SyncAction | None, user_id: int) -> None:
        await enqueue_sync(self._sessions, self._erp_sync, action, user_id)

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
            await close_sessions(session, user_id)
            await audit.record(session, actor, "user.reset_password", "user", user_id)
        return password

    async def change_password(self, actor: Actor, user_id: int, current: str, new: str) -> datetime:
        """Новый пароль; возвращает момент смены (прежние сессии закрыты: `close_sessions`)."""
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
            changed = await close_sessions(session, user_id)
            await audit.record(session, actor, "user.change_password", "user", user_id)
        return changed

    async def set_ui_mode(self, actor: Actor, user_id: int, mode: str) -> UserView:
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            roles = await repo.roles_of(session, user_id)
            if mode == "admin" and "admin" not in roles:
                raise ValidationFailedError("admin mode requires the admin role", field="ui_mode")
            user.ui_mode = mode
            return await _loaded_view(session, user, roles)

    async def set_language(self, actor: Actor, user_id: int, language: str) -> UserView:
        """Язык интерфейса (CRM-01b): сотрудник меняет сам себе, значение проверено схемой."""
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            if user.language != language:
                before = {"language": user.language}
                user.language = language
                await audit.record(
                    session, actor, "user.update", "user", user_id,
                    before=before, after={"language": language},
                )  # fmt: skip
                await bus_events.user_updated(session, user, actor, ["language"])
            return await _loaded_view(session, user)

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
            return await _loaded_view(session, user)

    async def set_onboarding_done(self, actor: Actor, user_id: int) -> UserView:
        """«Пропустить» / «Больше не показывать» в туре первого входа (W15-H7): сам, один раз."""
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            if user.onboarding_done_at is None:
                user.onboarding_done_at = datetime.now(UTC)
                await audit.record(session, actor, "user.onboarding_done", "user", user_id)
            return await _loaded_view(session, user)

    async def bootstrap_admin(self, email: str, full_name: str, password: str | None) -> str:
        """Первый админ или восстановление (CLI `create-admin`). Возвращает пароль (временный,
        если не задан).

        Админ — сотрудник Платформы с ролью ADMIN (CRM-01b): к уже имеющимся ролям Платформы она
        добавляется, доступ `crm+erp`, после коммита ставится провижининг ERP (как в `/setup`).
        """
        actor = Actor.system()
        secret = password or temporary_password()
        if password:
            _check_password(password, email)
        async with self._sessions() as session, session.begin():
            user_id = await _upsert_admin(
                session, email, full_name, secret, password is None, platform_admin=True
            )
            await audit.record(session, actor, "user.bootstrap_admin", "user", user_id)
        await self._sync_erp("provision", user_id)
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
                user_id = await _upsert_admin(
                    session, email, full_name.strip(), password, False, platform_admin=True
                )
            except IntegrityError as exc:
                raise ConflictError("admin already exists", reason=Reason.SETUP_DONE) from exc
            await audit.record(
                session, actor, "setup.admin_created", "user", user_id, after={"email": email}
            )
        # Первый админ — сотрудник Платформы с ролью ADMIN (CRM-01): доступ к ERP выдан сразу.
        await self._sync_erp("provision", user_id)
        return user_id


def _check_password(password: str, email: str) -> None:
    try:
        validate_new_password(password, email=email)
    except WeakPasswordError as exc:
        raise ValidationFailedError(
            str(exc), reason=Reason.WEAK_PASSWORD, field="password"
        ) from exc


async def _upsert_admin(
    session: AsyncSession,
    email: str,
    full_name: str,
    secret: str,
    temporary: bool,
    *,
    platform_admin: bool = False,
) -> int:
    user = await repo.by_email(session, email, for_update=True)
    created = user is None
    if user is None:
        user = User(email=normalize_email(email), full_name=full_name, password_hash="")
        session.add(user)
        await session.flush()
    held = await prepo.roles_of_user(session, user.id)
    fields_before = None if created else snapshots.user_fields(user, held)
    user.password_hash = hash_password(secret)
    user.must_change_password = temporary
    user.is_active = True
    user.ui_mode = "admin"
    user.failed_logins, user.locked_until = 0, None
    if platform_admin or held:
        # Роли Платформы ведут роль CRM и доступ к ERP: к ним добавляется системная роль ADMIN.
        admin_role = next(iter(await prepo.by_codes(session, [ADMIN_CODE])), None)
        if admin_role is None:
            raise NotFoundError("system role ADMIN is missing: apply migrations")
        held = [*held, admin_role] if admin_role.id not in {r.id for r in held} else held
        derived = derive_access(grants_of(held))
        await prepo.set_user_roles(session, user.id, [r.id for r in held], None)
        user.platform_access = list(derived.platform_access)
        user.erp_role_codes = list(derived.erp_role_codes)
        await repo.set_roles(session, user.id, [derived.crm_role], None)
        await _publish_admin(session, user, held, fields_before)
        return user.id
    roles = set(await repo.roles_of(session, user.id)) | {"admin"}
    await repo.set_roles(session, user.id, sorted(roles), None)
    await _publish_admin(session, user, held, fields_before)
    return user.id


async def _publish_admin(
    session: AsyncSession,
    user: User,
    held: Sequence[PlatformRole],
    fields_before: dict[str, Any] | None,
) -> None:
    """Первый администратор или восстановление (CLI, мастер): событие — в той же транзакции.

    `fields_before` — срез полей снимка до изменения; `None` — сотрудник создан сейчас."""
    system = Actor.system()
    if fields_before is None:
        await bus_events.user_created(session, user, system)
        return
    changed = snapshots.changed_user_fields(fields_before, snapshots.user_fields(user, held))
    await bus_events.user_updated(session, user, system, changed)


async def _publish_change(
    session: AsyncSession,
    actor: Actor,
    user: User,
    before: UserView,
    after: UserView,
    changed: Sequence[str],
) -> None:
    """Изменение сотрудника на шину: отключение — `deactivated`, прочее — снимок `updated`.

    `changed_fields` — все изменившиеся поля снимка (роли, системы, роли ERP, права EDS, ...):
    EDS проверяет право по проекции на момент запроса (sso-token.md)."""
    if before.is_active and not after.is_active:
        await bus_events.user_deactivated(session, user.id, actor)
    elif changed or audit_of(before) != audit_of(after):
        await bus_events.user_updated(session, user, actor, changed)


def _apply(user: User, patch: UserPatch) -> None:
    if patch.full_name is not None:
        user.full_name = patch.full_name.strip()
    if patch.is_active is not None:
        user.is_active = patch.is_active
    if patch.clear_tg_user_id:
        user.tg_user_id = None
        user.tg_username = None
        user.tg_linked_at = None
    elif patch.tg_user_id is not None:
        if patch.tg_user_id != user.tg_user_id:
            user.tg_username = None  # ник относился к прежнему аккаунту
            user.tg_linked_at = None  # привязал администратор
        user.tg_user_id = patch.tg_user_id
    if patch.platform_access is not None:
        user.platform_access = sorted(set(patch.platform_access) | {"crm"})
    if patch.erp_role_codes is not None:
        user.erp_role_codes = normalize_erp_roles(patch.erp_role_codes)
    if patch.position is not None:
        user.position = patch.position or None
    if patch.language is not None:
        user.language = patch.language


async def close_sessions(session: AsyncSession, user_id: int) -> datetime:
    """Смена или сброс пароля: refresh отозваны, выпущенные раньше токены больше не принимаются.

    Время — по часам приложения, как `iat` access-токенов и `created_at` новых refresh-токенов
    (часы БД с ними не сравниваются). Возвращает момент смены: сессия, которую нужно сохранить
    (смена пароля самим сотрудником), выпускается заново ровно на него."""
    changed = datetime.now(UTC)
    await revoke_tokens(session, user_id)
    await session.execute(
        update(User).where(User.id == user_id).values(password_changed_at=changed)
    )
    return changed


async def revoke_tokens(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def _loaded_view(
    session: AsyncSession, user: User, roles: list[str] | None = None
) -> UserView:
    """Срез пользователя с его ролями CRM и Платформы и признаком задачи ERP в очереди."""
    return view_of(
        user,
        roles if roles is not None else await repo.roles_of(session, user.id),
        await prepo.roles_of_user(session, user.id),
        erp_pending=user.id in await repo.erp_sync_pending_ids(session, user.id),
    )


_NEW_USER_STATE = AccessState(platform_access=("crm",), is_active=True, roles=(), full_name="")


async def _audit_access(
    session: AsyncSession, actor: Actor, user_id: int, before: AccessState, after: AccessState
) -> None:
    """Аудит выдачи и снятия доступа к ERP (`platform_access.granted|revoked`)."""
    action = access_audit_action(before, after)
    if action is not None:
        await audit.record(
            session,
            actor,
            action,
            "user",
            user_id,
            before={"platform_access": list(before.platform_access)},
            after={"platform_access": list(after.platform_access)},
        )
