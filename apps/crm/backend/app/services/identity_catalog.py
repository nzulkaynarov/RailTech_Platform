"""Автопереопубликация прав EDS при смене каталога (W13C-F4, Q-W13-A2-3 вариант 2).

Права EDS живут в проекции EDS из `identity.user.*` (`permissions.eds`); когда в
`packages/contracts/platform-rbac.yaml` меняется набор кодов EDS, события сами не возникают, и
заведённые сотрудники не получают новое право. Воркер CRM при старте сравнивает отпечаток этой части
каталога (`eds_catalog_fingerprint`) с записанным в `identity_catalog_state` и при расхождении
вызывает ту же `republish_identity`, что и команда `python -m app republish-identity`.

Один раз на изменение при любом числе процессов: проверка и публикация идут под
`pg_advisory_xact_lock`, который держит транзакция проверки; конкурент ждёт её конца, читает уже
записанный отпечаток и ничего не делает. Отпечаток пишется после успешной публикации всех пачек
(в той же транзакции, что держит блокировку), поэтому сбой в середине оставляет старый отпечаток и
следующий старт повторит: часть сотрудников получит событие дважды, это безвредно (проекция
применяет снимок «не старее»). Нет записи (первый старт) — публикация тоже выполняется: пустая база
даёт ноль событий, а база с командой, пришедшая из версии без этого механизма, получает актуальные
права без ручного шага. Сбой не пробрасывается: старт воркера не должен зависеть от шины.
"""

from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.platform_roles import eds_catalog_fingerprint
from app.models.system import IdentityCatalogState
from app.services.identity_republish import republish_identity

logger = structlog.get_logger(__name__)

EDS_KEY: Final = "eds_permissions"
_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtext('identity_catalog_state'))")


@dataclass(frozen=True)
class CatalogSyncResult:
    republished: bool  # отпечаток изменился: публикация выполнена и отпечаток записан
    users: int  # сколько сотрудников переопубликовано


async def ensure_eds_rights_published(
    sessions: async_sessionmaker[AsyncSession],
    *,
    fingerprint: str | None = None,
) -> CatalogSyncResult:
    """Переопубликовать снимки всех сотрудников, если отпечаток каталога EDS изменился.

    `fingerprint` — для тестов; по умолчанию — отпечаток действующего каталога."""
    current = fingerprint or eds_catalog_fingerprint()
    async with sessions() as session, session.begin():
        await session.execute(_LOCK_SQL)  # держится до конца транзакции
        stored = await session.get(IdentityCatalogState, EDS_KEY)
        previous = stored.fingerprint if stored is not None else None
        if previous == current:
            return CatalogSyncResult(republished=False, users=0)
        result = await republish_identity(sessions)
        stmt = insert(IdentityCatalogState).values(
            key=EDS_KEY, fingerprint=current, published_users=result.published
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "fingerprint": current,
                    "published_users": result.published,
                    "published_at": text("now()"),
                },
            )
        )
    logger.info(
        "eds_rights_republished",
        users=result.published,
        previous=previous[:12] if previous else None,
        fingerprint=current[:12],
    )
    return CatalogSyncResult(republished=True, users=result.published)


async def sync_eds_rights_on_start(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Вызов при старте воркера: любой сбой (база, шина) — в лог; повтор при следующем старте."""
    try:
        await ensure_eds_rights_published(sessions)
    except Exception as exc:  # noqa: BLE001 — старт сервиса не зависит от переопубликации
        logger.warning("eds_rights_republish_failed", error=repr(exc))
