"""Настройки из таблицы `settings` с TTL-кэшем (SPEC §5.7, PLAN Фаза 2).

Значения по умолчанию — в схемах (`app/schemas/settings.py`); строка таблицы
переопределяет ключ целиком. Невалидное значение в БД не роняет бота: берётся
значение по умолчанию, ошибка пишется в лог.
"""

import time
from collections.abc import Callable
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.public_urls import is_schema_default
from app.models.leads import Setting
from app.schemas.settings import SETTINGS_MODELS, AppSettings
from app.security import audit
from app.security.audit import Actor

logger = structlog.get_logger(__name__)


class UnknownSettingError(KeyError):
    """Ключ настроек не описан в SETTINGS_MODELS."""


class SettingsService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        ttl_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        crm_base_url_default: str | None = None,
    ) -> None:
        self._sessions = session_factory
        self._crm_base_url_default = crm_base_url_default
        self._ttl = ttl_s
        self._clock = clock
        self._cached: AppSettings | None = None
        self._loaded_at = 0.0

    async def get(self) -> AppSettings:
        if self._cached is not None and self._clock() - self._loaded_at < self._ttl:
            return self._cached
        async with self._sessions() as session:
            rows = (await session.scalars(select(Setting))).all()
        self._cached = _with_env_defaults(
            _merge({row.key: row.value for row in rows}), self._crm_base_url_default
        )
        self._loaded_at = self._clock()
        return self._cached

    async def raw(self) -> dict[str, dict[str, Any]]:
        """Текущие эффективные значения всех ключей (для API настроек)."""
        current = await self.get()
        return {key: getattr(current, key).model_dump(mode="json") for key in SETTINGS_MODELS}

    async def update(
        self, key: str, value: dict[str, Any], user_id: int | None, actor: Actor | None = None
    ) -> BaseModel:
        """Сохранить ключ целиком (валидация схемой). С `actor` — запись в audit_log."""
        model = SETTINGS_MODELS.get(key)
        if model is None:
            raise UnknownSettingError(key)
        validated = model.model_validate(value)
        payload = validated.model_dump(mode="json")
        before = (await self.raw()).get(key) if actor is not None else None
        async with self._sessions() as session, session.begin():
            await self._upsert(session, key, payload, user_id)
            if actor is not None:
                await audit.record(
                    session, actor, "settings.update", "settings", key, before=before, after=payload
                )
        self.invalidate()
        return validated

    async def merge_map(
        self, key: str, field: str, entries: dict[str, Any], user_id: int | None
    ) -> BaseModel:
        """Дописать записи в поле-словарь ключа настроек, не трогая остальные поля.

        Строка читается в транзакции с блокировкой (`FOR UPDATE`) и мимо кэша процесса: поля,
        которые другой запрос изменил после заполнения кэша (адрес ERP, срок приёма прежнего
        секрета), не откатываются. Нет строки — берутся значения по умолчанию схемы.
        """
        model = SETTINGS_MODELS.get(key)
        if model is None:
            raise UnknownSettingError(key)
        async with self._sessions() as session, session.begin():
            row = await session.scalar(select(Setting).where(Setting.key == key).with_for_update())
            current = dict(row.value) if row is not None else {}
            current[field] = {**(current.get(field) or {}), **entries}
            validated = model.model_validate(current)
            await self._upsert(session, key, validated.model_dump(mode="json"), user_id)
        self.invalidate()
        return validated

    async def update_in(
        self, session: AsyncSession, key: str, value: dict[str, Any], user_id: int | None
    ) -> BaseModel:
        """Сохранить ключ в транзакции вызывающего (вместе с секретами и аудитом).

        Кэш настроек вызывающий сбрасывает сам — `invalidate()` после коммита.
        """
        model = SETTINGS_MODELS.get(key)
        if model is None:
            raise UnknownSettingError(key)
        validated = model.model_validate(value)
        await self._upsert(session, key, validated.model_dump(mode="json"), user_id)
        return validated

    @staticmethod
    async def _upsert(
        session: AsyncSession, key: str, payload: dict[str, Any], user_id: int | None
    ) -> None:
        stmt = insert(Setting).values(key=key, value=payload, updated_by=user_id)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Setting.key],
                set_={
                    "value": payload,
                    "updated_by": user_id,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        )

    async def reset(self, key: str) -> bool:
        """Удалить сохранённое значение ключа — снова действуют значения по умолчанию из схемы.

        Нужно, когда новые тексты по умолчанию не видны: строка таблицы перекрывает ключ целиком.
        """
        if key not in SETTINGS_MODELS:
            raise UnknownSettingError(key)
        async with self._sessions() as session, session.begin():
            result = await session.execute(delete(Setting).where(Setting.key == key))
        self.invalidate()
        return bool(getattr(result, "rowcount", 0))

    def invalidate(self) -> None:
        self._cached = None


def _with_env_defaults(cfg: AppSettings, crm_base_url: str | None) -> AppSettings:
    """`company.crm_base_url` по умолчанию — публичный адрес CRM из окружения, а не `localhost`.

    Подменяется только заводское значение (ключа нет в БД или в нём `http://localhost`); адрес,
    заданный админом в «Настройки» → «Компания», остаётся как есть. В БД ничего не пишется.
    """
    if not crm_base_url or not is_schema_default(cfg.company.crm_base_url):
        return cfg
    company = cfg.company.model_copy(update={"crm_base_url": crm_base_url})
    return cfg.model_copy(update={"company": company})


def _merge(rows: dict[str, dict[str, Any]]) -> AppSettings:
    values: dict[str, Any] = {}
    for key, model in SETTINGS_MODELS.items():
        if key not in rows:
            continue
        try:
            values[key] = model.model_validate(rows[key])
        except ValidationError as exc:
            logger.error("settings_invalid_value_ignored", key=key, errors=exc.error_count())
    return AppSettings(**values)
