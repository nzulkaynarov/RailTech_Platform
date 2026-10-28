"""Автопереопубликация прав EDS (W13C-F4, Q-W13-A2-3 вариант 2) и ERP (D2-1, B-073) при смене
каталога.

Права ERP уходят не событием, а провижинингом (`tasks.erp_users`): при смене отпечатка ERP-части
каталога (`erp_catalog_fingerprint`, ключ `erp_permissions`) воркер ставит задачу провижининга
каждому активному сотруднику с доступом к ERP — так новые коды (например, визы расчёта
`quote.visa_*`) доезжают до уже заведённых сотрудников без ручного пересохранения ролей. Механика
блокировки и записи отпечатка — та же, что у EDS ниже.

Права EDS живут в проекции EDS из `identity.user.*` (`permissions.eds`); когда в
`packages/contracts/platform-rbac.yaml` меняется набор кодов EDS, события сами не возникают, и
заведённые сотрудники не получают новое право. Воркер CRM при старте сравнивает отпечаток этой части
каталога (`eds_catalog_fingerprint`) с записанным в `identity_catalog_state` и при расхождении
вызывает ту же `republish_identity`, что и команда `python -m app republish-identity`.

Один раз на изменение при любом числе процессов: проверка и публикация идут под
`pg_advisory_xact_lock`, который держит транзакция проверки; конкурент ждёт её конца, читает уже
записанный отпечаток и ничего не делает. Отпечаток пишется после успешной публикации всех пачек (в
той же транзакции, что держит блокировку), поэтому сбой в середине оставляет старый отпечаток и
следующий старт повторит: часть сотрудников получит событие дважды, это безвредно (проекция
применяет снимок «не старее»). Нет записи (первый старт) — публикация тоже выполняется: пустая база
даёт ноль событий, а база с командой, пришедшая из версии без этого механизма, получает актуальные
права без ручного шага. Сбой не пробрасывается: старт воркера не должен зависеть от шины.

Сбой не остаётся только в логе (W15-H8b, B-005): расхождение «записанный отпечаток ≠ отпечаток
каталога» само и есть состояние «права не опубликованы». Его читает строка `eds_rights` центра
внешних сервисов («Состояние системы»): она повторяет эту же публикацию (не чаще раза в 5 минут и по
«Перепроверить»), а пока не удалось дольше 15 минут — одно «Сломано» по общей политике H3, затем
одно «Восстановлено». Отдельной таблицы или флага сбоя нет: данных, которые могли бы разойтись с
реальностью, не появляется. В отпечаток входят и шаблоны ролей `tpl:*`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.platform_roles import eds_catalog_fingerprint, erp_catalog_fingerprint
from app.models.auth import User
from app.models.system import IdentityCatalogState
from app.services.identity_republish import republish_identity

logger = structlog.get_logger(__name__)

EDS_KEY: Final = "eds_permissions"
ERP_KEY: Final = "erp_permissions"
# Поставить задачу ERP (`tasks.erp_users.enqueue_erp_sync`): (действие, user_id).
ErpEnqueue = Callable[[str, int], Awaitable[object]]
_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtext('identity_catalog_state'))")
_LOCK_TIMEOUT_SQL = text(
    "SELECT set_config('lock_timeout', :ms, true)"
)  # true = до конца транзакции
LOCK_TIMEOUT_S: Final = 30.0
_LOCK_NOT_AVAILABLE: Final = "55P03"


@dataclass(frozen=True)
class CatalogSyncResult:
    republished: bool  # отпечаток изменился: публикация выполнена и отпечаток записан
    users: int  # сколько сотрудников переопубликовано
    skipped_locked: bool = (
        False  # блокировку держит другой процесс дольше предела: ничего не делали
    )


async def ensure_eds_rights_published(
    sessions: async_sessionmaker[AsyncSession],
    *,
    fingerprint: str | None = None,
    lock_timeout_s: float = LOCK_TIMEOUT_S,
) -> CatalogSyncResult:
    """Переопубликовать снимки всех сотрудников, если отпечаток каталога EDS изменился.

    `fingerprint` — для тестов; по умолчанию — отпечаток действующего каталога. Ожидание блокировки
    ограничено `lock_timeout_s`: держатель завис — выходим без публикации (`skipped_locked`), старт
    воркера не ждёт, повтор будет при следующем старте."""
    current = fingerprint or eds_catalog_fingerprint()
    try:
        return await _publish_under_lock(sessions, current, lock_timeout_s)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) != _LOCK_NOT_AVAILABLE:
            raise
        logger.warning("eds_rights_republish_skipped_locked", timeout_s=lock_timeout_s)
        return CatalogSyncResult(republished=False, users=0, skipped_locked=True)


async def _publish_under_lock(
    sessions: async_sessionmaker[AsyncSession], current: str, lock_timeout_s: float
) -> CatalogSyncResult:
    async def republish() -> int:
        return (await republish_identity(sessions)).published

    return await _sync_under_lock(
        sessions, EDS_KEY, current, lock_timeout_s, republish, "eds_rights_republished"
    )


async def _sync_under_lock(
    sessions: async_sessionmaker[AsyncSession],
    key: str,
    current: str,
    lock_timeout_s: float,
    action: Callable[[], Awaitable[int]],
    event: str,
) -> CatalogSyncResult:
    async with sessions() as session, session.begin():
        await session.execute(_LOCK_TIMEOUT_SQL, {"ms": f"{int(lock_timeout_s * 1000)}ms"})
        await session.execute(_LOCK_SQL)  # держится до конца транзакции
        await session.execute(_LOCK_TIMEOUT_SQL, {"ms": "0"})  # дальше — без предела (публикация)
        stored = await session.get(IdentityCatalogState, key)
        previous = stored.fingerprint if stored is not None else None
        if previous == current:
            return CatalogSyncResult(republished=False, users=0)
        users = await action()
        stmt = insert(IdentityCatalogState).values(
            key=key, fingerprint=current, published_users=users
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "fingerprint": current,
                    "published_users": users,
                    "published_at": text("now()"),
                },
            )
        )
    logger.info(
        event,
        users=users,
        previous=previous[:12] if previous else None,
        fingerprint=current[:12],
    )
    return CatalogSyncResult(republished=True, users=users)


async def reprovision_erp_users(
    sessions: async_sessionmaker[AsyncSession], enqueue: ErpEnqueue
) -> int:
    """Задача провижининга каждому активному сотруднику с доступом к ERP; сколько поставлено.

    Общая для автопереопубликации по отпечатку и ручной команды `python -m app reprovision-erp`."""
    async with sessions() as session:
        stmt = select(User).where(User.is_active.is_(True)).order_by(User.id)
        ids = [
            u.id for u in (await session.scalars(stmt)).all() if "erp" in (u.platform_access or [])
        ]
    for user_id in ids:
        await enqueue("provision", user_id)
    return len(ids)


async def ensure_erp_rights_provisioned(
    sessions: async_sessionmaker[AsyncSession],
    enqueue: ErpEnqueue,
    *,
    fingerprint: str | None = None,
    lock_timeout_s: float = LOCK_TIMEOUT_S,
) -> CatalogSyncResult:
    """Провижинить заново всех активных сотрудников с доступом к ERP, если отпечаток ERP-части
    каталога изменился.

    Задачи провижининга идемпотентны (ERP перезаписывает роль «CRM Sync» вычисленным набором прав);
    сбой постановки — исключение до записи отпечатка, повтор при следующем старте."""
    current = fingerprint or erp_catalog_fingerprint()

    async def provision_all() -> int:
        return await reprovision_erp_users(sessions, enqueue)

    try:
        return await _sync_under_lock(
            sessions, ERP_KEY, current, lock_timeout_s, provision_all, "erp_rights_reprovisioned"
        )
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) != _LOCK_NOT_AVAILABLE:
            raise
        logger.warning("erp_rights_reprovision_skipped_locked", timeout_s=lock_timeout_s)
        return CatalogSyncResult(republished=False, users=0, skipped_locked=True)


async def sync_erp_rights_on_start(
    sessions: async_sessionmaker[AsyncSession], enqueue: ErpEnqueue
) -> None:
    """Вызов при старте воркера: сбой — в лог (`erp_rights_reprovision_failed`), повтор при
    следующем старте."""
    try:
        await ensure_erp_rights_provisioned(sessions, enqueue)
    except Exception as exc:  # noqa: BLE001 — старт сервиса не зависит от провижининга
        logger.warning("erp_rights_reprovision_failed", error=repr(exc))


async def sync_eds_rights_on_start(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Вызов при старте воркера: любой сбой (база, шина) — в лог; повтор при следующем старте."""
    try:
        await ensure_eds_rights_published(sessions)
    except Exception as exc:  # noqa: BLE001 — старт сервиса не зависит от переопубликации
        logger.warning("eds_rights_republish_failed", error=repr(exc))
