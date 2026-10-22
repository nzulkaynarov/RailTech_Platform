"""Сессия сотрудника в Redis (02-architecture.md §3): `session:<sid>`.

В сессии — токены CRM и ERP и снимок профиля. Браузер знает только `sid` (cookie `rt_pf_session`,
256 бит случайности) и CSRF-значение; токены CRM и ERP не покидают Redis. Сессия живёт абсолютный
срок `PLATFORM_SESSION_TTL_HOURS` от входа.

Любая запись в сессию идёт под блокировкой `session-lock:<sid>` с перечитыванием: refresh-токены
CRM и ERP ротируются, и запись устаревшей копии вернула бы уже использованный токен (CRM расценит
это как кражу и погасит всю семью токенов).
"""

import asyncio
import json
import secrets
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Literal

import structlog
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.errors import PlatformError

log = structlog.get_logger()

LOCK_TTL_MS = 15_000
LOCK_WAIT_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.02

# Снять блокировку может только тот, кто её взял (сравнение и удаление атомарно).
RELEASE_LOCK = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

ErpState = Literal["ok", "unavailable", "not_applicable"]
Language = Literal["ru", "uz", "en"]


def now() -> float:
    """Текущее время (секунды epoch); тесты подменяют, чтобы состарить токены."""
    return time.time()


class BackendTokens(BaseModel):
    access: str = Field(repr=False)
    access_exp: float
    refresh: str = Field(repr=False)


class SessionRole(BaseModel):
    """Роль Платформы сотрудника — снимок `/me` CRM (`platform_role_refs`, R-2).

    Id, название из данных, системная ли, код (только у системных и созданных из шаблона), матрица
    и поля с ограничением.
    """

    id: int
    name: str
    system: bool = False
    code: str | None = None
    access: dict[str, str] = Field(default_factory=dict)
    restricted_fields: list[str] = Field(default_factory=list)


class SessionData(BaseModel):
    """Содержимое `session:<sid>`: только JSON, секретов вне Redis нет."""

    csrf: str = Field(repr=False)
    created_at: float
    expires_at: float
    # Снимок профиля CRM; обновляется не чаще раза в `PROFILE_TTL_SECONDS` (см. app/auth.py).
    user_id: int
    email: str
    name: str
    position: str | None = None
    roles: list[SessionRole]
    platform_access: list[str]
    must_change_password: bool
    profile_checked_at: float
    # Настройки сотрудника в рамках сессии (у BFF нет своей базы).
    language: Language = "ru"
    # Id активной роли («вид», Q-PLT-12-1); None — все роли.
    active_role: int | None = None
    crm: BackendTokens
    erp_state: ErpState
    erp: BackendTokens | None = None
    # Не пытаться переподключить ERP раньше этого момента (ERP недоступен при входе).
    erp_next_try: float = 0.0

    def sources(self) -> dict[str, str]:
        """Состояние источников для `sources` агрегирующих ответов (контракт: `Sources`)."""
        return {"crm": "ok", "erp": self.erp_state}


def new_secret() -> str:
    return secrets.token_urlsafe(32)  # 256 бит


class SessionStore:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def _key(sid: str) -> str:
        return f"session:{sid}"

    async def create(self, data: SessionData) -> str:
        sid = new_secret()
        await self._write(sid, data)
        return sid

    async def get(self, sid: str) -> SessionData | None:
        raw = await self.redis.get(self._key(sid))
        if raw is None:
            return None
        try:
            data = SessionData.model_validate(json.loads(raw))
        except ValueError:  # битый JSON или сессия старой схемы (ValidationError — тоже ValueError)
            # Содержимое сессии (токены) в журнал не попадает: только факт и тип ошибки.
            log.warning("session_unreadable")
            await self.delete(sid)
            return None
        if data.expires_at <= now():
            await self.delete(sid)
            return None
        return data

    async def save(self, sid: str, data: SessionData) -> None:
        """Записать сессию, сохранив абсолютный срок; вызывать только под блокировкой."""
        await self._write(sid, data)

    async def _write(self, sid: str, data: SessionData) -> None:
        ttl = int(data.expires_at - now())
        if ttl <= 0:
            await self.delete(sid)
            return
        await self.redis.set(self._key(sid), data.model_dump_json(), ex=ttl)

    async def delete(self, sid: str) -> None:
        await self.redis.delete(self._key(sid))

    @asynccontextmanager
    async def lock(self, sid: str) -> AsyncIterator[None]:
        key = f"session-lock:{sid}"
        token = new_secret()
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while not await self.redis.set(key, token, nx=True, px=LOCK_TTL_MS):
            if time.monotonic() >= deadline:
                log.warning("session_lock_timeout")
                raise PlatformError(
                    "BACKEND_UNAVAILABLE",
                    "Сервис временно недоступен.",
                    status_code=503,
                )
            await asyncio.sleep(LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            await self.redis.eval(RELEASE_LOCK, 1, key, token)

    async def update(self, sid: str, mutate: Callable[[SessionData], None]) -> SessionData | None:
        """Под блокировкой перечитать сессию, применить `mutate`, записать. `None` — сессии нет."""
        async with self.lock(sid):
            data = await self.get(sid)
            if data is None:
                return None
            mutate(data)
            await self.save(sid, data)
            return data
