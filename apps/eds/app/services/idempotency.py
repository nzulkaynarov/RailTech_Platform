"""`Idempotency-Key` создающих POST (eds.yaml, «Идемпотентность»): повтор в течение 24 часов возвращает прежний ответ.

Ключ принадлежит сотруднику и операции. Строка ключа создаётся в той же транзакции, что и сам объект, и откатывается
вместе с ним: параллельный повтор ждёт первую транзакцию на вставке и затем получает её ответ. Другое тело с тем же
ключом — 409 `CONFLICT` (`details.reason = idempotency_key_reused`).
"""

import datetime as dt
import json
from collections.abc import Awaitable, Callable
from hashlib import sha256
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import conflict
from app.models import IdempotencyKey

TTL = dt.timedelta(hours=24)


def body_hash(*parts: Any) -> str:
    """Отпечаток тела запроса: JSON-представление частей в каноническом виде."""
    canonical = json.dumps(
        [p.model_dump(mode="json") if isinstance(p, BaseModel) else p for p in parts],
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return sha256(canonical.encode()).hexdigest()


async def run(
    session: AsyncSession,
    *,
    crm_user_id: int,
    scope: str,
    key: str | None,
    request_hash: str,
    status_code: int,
    action: Callable[[], Awaitable[BaseModel]],
) -> BaseModel | JSONResponse:
    """Выполнить `action` в транзакции вызывающего; с ключом — один раз на (ключ, сотрудник, операция) за 24 часа."""
    if key is None:
        return await action()
    now = clock.now()
    claimed = await session.execute(
        insert(IdempotencyKey)
        .values(key=key, crm_user_id=crm_user_id, scope=scope, request_hash=request_hash, created_at=now)
        .on_conflict_do_nothing()
        .returning(IdempotencyKey.key)
    )
    if claimed.first() is None:
        existing = (
            await session.execute(
                select(IdempotencyKey)
                .where(
                    IdempotencyKey.key == key,
                    IdempotencyKey.crm_user_id == crm_user_id,
                    IdempotencyKey.scope == scope,
                )
                .with_for_update()
            )
        ).scalar_one()
        if existing.created_at + TTL <= now:  # ключ просрочен — выполняем заново под тем же ключом
            existing.request_hash, existing.created_at = request_hash, now
            existing.status_code, existing.response = None, None
        elif existing.request_hash != request_hash:
            raise conflict("idempotency_key_reused", "Ключ повтора уже использован с другим запросом.")
        elif existing.response is not None and existing.status_code is not None:
            return JSONResponse(existing.response, status_code=existing.status_code)
    result = await action()
    await session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.key == key, IdempotencyKey.crm_user_id == crm_user_id, IdempotencyKey.scope == scope)
        .values(status_code=status_code, response=result.model_dump(mode="json"))
    )
    return result


async def purge_expired(session: AsyncSession) -> int:
    """Удалить просроченные ключи (задача раз в час)."""
    result = await session.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < clock.now() - TTL))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
