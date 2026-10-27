"""Профиль сотрудника: телефон, пояс, подпись, имя и фото (W15-H6, ADR-0015: поля принадлежат CRM).

Сотрудник правит только себя: `user_id` берётся из токена, не из тела запроса. Имя идёт через
`UserService.update` (аудит, событие шины `identity.user.updated`, синхронизация ERP), остальное —
личные поля CRM без событий. Фото лежит в бакете файлов CRM под `staff-avatars/<id>/`; наружу его
отдаёт только API (`GET /staff/{id}/avatar`), публичных ссылок на S3 нет.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import staff_profile as rules
from app.domain.errors import NotFoundError, Reason, ValidationFailedError
from app.repositories import users as repo
from app.security import audit
from app.security.audit import Actor
from app.services.user_views import UserPatch, UserView
from app.services.users import UserService

logger = structlog.get_logger(__name__)


class Storage(Protocol):
    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, bucket: str, key: str) -> bytes: ...
    async def delete(self, bucket: str, key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AvatarFile:
    data: bytes
    content_type: str
    version: int


def invalid(exc: rules.ProfileValueError) -> ValidationFailedError:
    """Ошибка значения профиля -> 422 с `details.field` и `details.reason`."""
    return ValidationFailedError(str(exc), reason=Reason(exc.reason), field=exc.field)


class StaffProfileService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        users: UserService,
        storage: Storage,
        bucket: str,
    ) -> None:
        self._sessions = sessions
        self._users = users
        self._storage = storage
        self._bucket = bucket

    async def update(
        self,
        actor: Actor,
        user_id: int,
        *,
        full_name: str | None = None,
        phone: str | None = None,
        timezone: str | None = None,
        email_signature: str | None = None,
    ) -> UserView:
        """Поля профиля; `None` — не менять, пустая строка в телефоне и подписи — очистить."""
        new_phone, new_zone, new_signature = self.validate(
            full_name=full_name, phone=phone, timezone=timezone, email_signature=email_signature
        )
        if any(v is not None for v in (phone, timezone, email_signature)):
            await self._save_private(
                actor, user_id, phone, new_phone, new_zone, email_signature, new_signature
            )
        if full_name is not None:
            await self._users.update(actor, user_id, UserPatch(full_name=full_name))
        return await self._users.get(user_id)

    @staticmethod
    def validate(
        *,
        full_name: str | None = None,
        phone: str | None = None,
        timezone: str | None = None,
        email_signature: str | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        """Поля проверяются до записи: телефон, пояс и подпись нормализуются; пустое имя — 422."""
        try:
            if full_name is not None and not full_name.strip():
                raise rules.ProfileValueError("name_required", "full_name")
            return (
                None if phone is None else rules.normalize_phone(phone),
                None if timezone is None else rules.checked_timezone(timezone),
                None if email_signature is None else rules.checked_signature(email_signature),
            )
        except rules.ProfileValueError as exc:
            raise invalid(exc) from exc

    async def _save_private(
        self,
        actor: Actor,
        user_id: int,
        phone_sent: str | None,
        phone: str | None,
        timezone: str | None,
        signature_sent: str | None,
        signature: str | None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            before: dict[str, Any] = {}
            after: dict[str, Any] = {}
            if phone_sent is not None and user.phone != phone:
                before["phone"], after["phone"] = user.phone, phone
                user.phone = phone
            if timezone is not None and user.timezone != timezone:
                before["timezone"], after["timezone"] = user.timezone, timezone
                user.timezone = timezone
            if signature_sent is not None and user.email_signature != signature:
                # Текст подписи в журнал не пишем: только факт изменения.
                before["email_signature"], after["email_signature"] = "set", "changed"
                user.email_signature = signature
            if after:
                await audit.record(
                    session, actor, "user.profile_update", "user", user_id,
                    before=before, after=after,
                )  # fmt: skip

    # --- фото -------------------------------------------------------------------------------

    async def set_avatar(
        self, actor: Actor, user_id: int, data: bytes, claimed_type: str | None
    ) -> UserView:
        try:
            content_type = rules.checked_avatar(data, claimed_type)
        except rules.ProfileValueError as exc:
            raise invalid(exc) from exc
        key = rules.avatar_key(user_id, secrets.token_hex(8), content_type)
        # Сначала файл, потом строка в БД: сбой записи оставит лишний объект, а не битую ссылку.
        await self._storage.put(self._bucket, key, data, content_type)
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            old_key = user.avatar_key
            user.avatar_key = key
            user.avatar_updated_at = datetime.now(UTC)
            await audit.record(session, actor, "user.avatar_set", "user", user_id)
        await self._drop(old_key)
        return await self._users.get(user_id)

    async def remove_avatar(self, actor: Actor, user_id: int) -> UserView:
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            old_key = user.avatar_key
            if old_key is not None:
                user.avatar_key = None
                user.avatar_updated_at = None
                await audit.record(session, actor, "user.avatar_removed", "user", user_id)
        await self._drop(old_key)
        return await self._users.get(user_id)

    async def read_avatar(self, user_id: int) -> AvatarFile | None:
        async with self._sessions() as session:
            user = await repo.get(session, user_id)
        if user is None or not user.is_active or not user.avatar_key or not user.avatar_updated_at:
            return None
        data = await self._storage.get(self._bucket, user.avatar_key)
        content_type = rules.sniff_image(data)
        if content_type is None:  # в бакете не картинка: наружу не отдаём
            logger.warning("avatar_unreadable", user_id=user_id)
            return None
        return AvatarFile(data, content_type, int(user.avatar_updated_at.timestamp()))

    async def _drop(self, key: str | None) -> None:
        if key is None:
            return
        try:
            await self._storage.delete(self._bucket, key)
        except Exception:  # лишний объект не повод падать: файл больше нигде не указан
            logger.warning("avatar_delete_failed", exc_info=True)
