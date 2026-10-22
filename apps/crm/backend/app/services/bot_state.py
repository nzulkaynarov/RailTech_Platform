"""Связь `crm-api` и `crm-bot` через БД (S0-4): состояние бота, пульс, запрос на перезапуск.

Бот живёт в отдельном процессе `crm-bot`; API не держит его в памяти. Поэтому:

* `crm-bot` пишет в `bot_runtime` свой статус и пульс (`report`), забирает запрос на перезапуск
  (`pending_restart`) и отмечает его выполненным (`mark_applied`);
* `crm-api` читает статус (`snapshot`) для «Подключений», «Состояния системы» и чек-листа настройки
  и просит перезапуск при смене токена (`request_restart`, `wait_applied`).

Значение токена в таблицу не попадает. Каждый процесс обновляет только свои столбцы, поэтому
записи друг друга не затирают. Время сравнивается на стороне БД: часы контейнеров не важны.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.profile import ProfilePublish
from app.models.system import BotRuntimeState

_ROW = 1
_POLL_S = 0.25


@dataclass(frozen=True, slots=True)
class BotSnapshot:
    """Что `crm-bot` сообщил о себе. `alive` — пульс свежий; без него `running` недостоверен."""

    alive: bool
    running: bool
    source: str
    username: str | None
    mode: str | None
    last_error: str | None
    profile: ProfilePublish | None
    heartbeat_age_s: float | None


@dataclass(frozen=True, slots=True)
class PendingRestart:
    requested_at: datetime | None
    applied_at: datetime | None

    @property
    def pending(self) -> bool:
        return self.requested_at is not None and self.requested_at != self.applied_at


def profile_to_json(result: ProfilePublish | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "ok": result.ok,
        "at": result.at.isoformat(),
        "changed": result.changed,
        "error": result.error,
        "retry_after": result.retry_after,
    }


def profile_from_json(raw: dict[str, Any] | None) -> ProfilePublish | None:
    if not raw:
        return None
    return ProfilePublish(
        ok=bool(raw.get("ok")),
        at=datetime.fromisoformat(str(raw["at"])) if raw.get("at") else datetime.now(UTC),
        changed=int(raw.get("changed") or 0),
        error=raw.get("error"),
        retry_after=raw.get("retry_after"),
    )


class BotStateService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, stale_after_s: float = 45.0
    ) -> None:
        self._sessions = sessions
        self._stale_after_s = stale_after_s

    # --- чтение (crm-api) ------------------------------------------------------------------

    async def snapshot(self) -> BotSnapshot | None:
        """`None` — `crm-bot` ни разу не отчитывался (ещё не запускался)."""
        age = func.extract("epoch", func.now() - BotRuntimeState.heartbeat_at)
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(BotRuntimeState, age.label("age")).where(BotRuntimeState.id == _ROW)
                )
            ).one_or_none()
        if row is None:
            return None
        state, heartbeat_age = row
        age_s = float(heartbeat_age) if heartbeat_age is not None else None
        alive = age_s is not None and age_s <= self._stale_after_s
        return BotSnapshot(
            alive=alive,
            running=alive and state.running,
            source=state.source,
            username=state.username if alive else None,
            mode=state.mode,
            last_error=state.last_error,
            profile=profile_from_json(state.profile),
            heartbeat_age_s=age_s,
        )

    # --- запись (crm-api) ------------------------------------------------------------------

    async def request_restart(self, session: AsyncSession) -> datetime:
        """В транзакции вызывающего: «токен сменили — `crm-bot`, перезапусти бота»."""
        stmt = (
            insert(BotRuntimeState)
            .values(id=_ROW, running=False, source="none", restart_requested_at=func.now())
            .on_conflict_do_update(
                index_elements=[BotRuntimeState.id],
                set_={"restart_requested_at": func.now(), "updated_at": func.now()},
            )
            .returning(BotRuntimeState.restart_requested_at)
        )
        requested = (await session.execute(stmt)).scalar_one()
        if requested is None:  # ON CONFLICT всегда выставляет значение
            raise RuntimeError("bot_runtime.restart_requested_at is empty after upsert")
        return requested

    async def wait_applied(self, requested_at: datetime, timeout_s: float) -> bool:
        """Ждать, пока `crm-bot` применит запрос; `False` — не успел (процесс лежит или занят)."""
        deadline = time.monotonic() + timeout_s
        while True:
            state = await self.pending_restart()
            if state.applied_at == requested_at or (
                state.requested_at is not None and state.requested_at > requested_at
            ):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(_POLL_S)

    async def record_profile(self, result: ProfilePublish) -> None:
        """Итог публикации профиля, сделанной из API (исходящий вызов `setMyName` и т. п.)."""
        stmt = insert(BotRuntimeState).values(
            id=_ROW, running=False, source="none", profile=profile_to_json(result)
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[BotRuntimeState.id],
            set_={"profile": profile_to_json(result), "updated_at": func.now()},
        )
        async with self._sessions() as session, session.begin():
            await session.execute(stmt)

    # --- crm-bot ---------------------------------------------------------------------------

    async def pending_restart(self) -> PendingRestart:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(
                        BotRuntimeState.restart_requested_at, BotRuntimeState.restart_applied_at
                    ).where(BotRuntimeState.id == _ROW)
                )
            ).one_or_none()
        return PendingRestart(None, None) if row is None else PendingRestart(row[0], row[1])

    async def report(
        self,
        *,
        running: bool,
        mode: str,
        source: str,
        username: str | None,
        last_error: str | None,
        profile: ProfilePublish | None,
        started: bool = False,
    ) -> None:
        """Статус и пульс процесса бота. `started` — процесс только что поднялся."""
        values: dict[str, Any] = {
            "running": running,
            "mode": mode,
            "source": source,
            "username": username,
            "last_error": last_error,
            "heartbeat_at": func.now(),
            "updated_at": func.now(),
        }
        if started:
            values["started_at"] = func.now()
        if profile is not None:
            values["profile"] = profile_to_json(profile)
        stmt = insert(BotRuntimeState).values(id=_ROW, **values)
        stmt = stmt.on_conflict_do_update(index_elements=[BotRuntimeState.id], set_=values)
        async with self._sessions() as session, session.begin():
            await session.execute(stmt)

    async def mark_stopped(self) -> None:
        """Штатная остановка: пульса больше не будет, API сразу видит «не отвечает»."""
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(BotRuntimeState)
                .where(BotRuntimeState.id == _ROW)
                .values(running=False, heartbeat_at=None, updated_at=func.now())
            )

    async def mark_applied(self, requested_at: datetime) -> None:
        """Запрос выполнен: в `restart_applied_at` копируется то, что было прочитано."""
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(BotRuntimeState)
                .where(BotRuntimeState.id == _ROW)
                .values(restart_applied_at=requested_at)
            )
