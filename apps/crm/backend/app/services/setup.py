"""Мастер первого запуска: код из логов api → первый админ → вход (scope-аудит §4).

Пока нет ни одного активного админа, api выдаёт одноразовый код и пишет его в лог один
раз (`setup_code_issued`). После создания админа мастер закрыт навсегда (409), даже если
админа позже деактивируют: инвариант «≥ 1 активный admin» не даёт остаться без админов.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog

from app.domain.errors import ConflictError, Reason
from app.domain.setup_code import SetupCodeGate
from app.security.audit import Actor

logger = structlog.get_logger(__name__)

CountAdmins = Callable[[], Awaitable[int]]
CreateAdmin = Callable[[str, str, str, Actor], Awaitable[int]]
Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SetupService:
    def __init__(
        self,
        count_admins: CountAdmins,
        create_admin: CreateAdmin,
        clock: Clock = _utcnow,
        gate: SetupCodeGate | None = None,
    ) -> None:
        self._count_admins = count_admins
        self._create_admin = create_admin
        self._clock = clock
        self._gate = gate or SetupCodeGate()
        self._done = False
        self._lock = asyncio.Lock()

    async def needs_setup(self) -> bool:
        """Нет активного админа. «Готово» кэшируется — после админа в БД больше не ходим."""
        if self._done:
            return False
        if await self._count_admins() > 0:
            self._finish()
            return False
        return True

    async def ensure_code(self) -> bool:
        """Выдать код, если мастер нужен и действующего кода нет. True — код выдан сейчас."""
        if not await self.needs_setup():
            return False
        now = self._clock()
        if self._gate.is_valid(now):
            return False
        self._gate.issue(now)
        logger.warning(
            "setup_code_issued",
            setup_code=self._gate.code,
            valid_hours=int(self._gate.ttl.total_seconds() // 3600),
            hint="Первый запуск: откройте CRM, страница /setup, и введите этот код",
        )
        return True

    async def create_admin(
        self, code: str, email: str, full_name: str, password: str, ip: str | None = None
    ) -> None:
        """Проверить код и создать первого админа; гасит код. Вход выполняет вызывающий."""
        async with self._lock:
            if not await self.needs_setup():
                raise ConflictError("setup already completed", reason=Reason.SETUP_DONE)
            self._gate.verify(code, self._clock())
            await self._create_admin(email, full_name, password, Actor(None, "system", ip))
            self._finish()
        logger.info("setup_admin_created")

    def _finish(self) -> None:
        self._done = True
        self._gate.consume()
