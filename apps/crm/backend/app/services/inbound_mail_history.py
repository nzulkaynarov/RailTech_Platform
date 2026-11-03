"""«Загрузить письма за период» (W18A-P2-2): старые письма общего ящика — в очередь, фоном.

Эталон — импорт истории при подключении ящика в Front и Help Scout (выбор периода, фоновая загрузка,
итог). Админ в «Подключения · Почта · Приём» выбирает 7, 14, 30 или 90 дней; строка
`inbound_mail_import` хранит ход и итог, задача Procrastinate (`inbound_mail_history`) читает папки
опроса только на чтение (`UID SEARCH SINCE`, `BODY.PEEK[]`) и пишет письма тем же
`InboundMailIngest.store`, что и опрос: дубль по Message-ID не создаётся, повтор безопасен. Письмо
старше окна задач — «из истории» (в списке «Входящая почта», не строкой «Моих задач»); из спам-папки
— в «Подозрительные». Не больше `HISTORY_LIMIT` писем за раз: обычные папки раньше спама, новые
раньше старых. Одна загрузка одновременно (advisory-блокировка); зависшая после сбоя воркера
(не обновлялась `STALE_AFTER`) новой не мешает.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, ValidationFailedError
from app.domain.inbound_folders import HISTORY_DAYS, FolderSetting, pick_history
from app.integrations.imap import (
    ImapClient,
    ImapConnection,
    ImapProbeError,
    in_folder,
    resolve_imap,
)
from app.models.inbound_mail import InboundMailImport
from app.repositories import inbound_mail as repo
from app.schemas.inbound_mail import ImapHistoryOut
from app.security import audit
from app.security.principal import Principal
from app.security.secrets_store import SecretsStore
from app.services.inbound_mail_ingest import InboundMailIngest
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

STALE_AFTER: Final = timedelta(minutes=30)
#: Писем за одно чтение из ящика; после каждой пачки — ход в строке загрузки.
FETCH_BATCH: Final = 25
_LOCK: Final = "inbound_mail_import"

Enqueue = Callable[[int], Awaitable[object]]


def view(row: InboundMailImport) -> ImapHistoryOut:
    return ImapHistoryOut(
        id=row.id,
        days=row.days,
        status=row.status,
        found=row.found,
        processed=row.processed,
        created=row.created,
        limited=row.limited,
        error_kind=row.error_kind,
        started_at=row.created_at,
        finished_at=row.finished_at,
    )


class InboundMailHistory:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        store: SecretsStore,
        settings: SettingsService,
        client: ImapClient,
        ingest: InboundMailIngest,
        enqueue: Enqueue,
    ) -> None:
        self._sessions = sessions
        self._store = store
        self._settings = settings
        self._client = client
        self._ingest = ingest
        self._enqueue = enqueue

    async def last(self) -> ImapHistoryOut | None:
        async with self._sessions() as session:
            row = await repo.last_import(session)
        return view(row) if row is not None else None

    async def start(self, who: Principal, days: int) -> ImapHistoryOut:
        """Начать загрузку; уже идёт — та же (второй задачи нет)."""
        if days not in HISTORY_DAYS:
            raise ValidationFailedError("period is not allowed", field="days")
        if (await resolve_imap(self._store, self._settings)).connection is None:
            raise ConflictError("imap is not configured", field="host")
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(_LOCK))))
            running = await repo.running_import(session, now - STALE_AFTER)
            if running is not None:
                return view(running)
            row = InboundMailImport(days=days, status="running", requested_by=who.user_id)
            session.add(row)
            await session.flush()
            await audit.record(
                session,
                who.actor,
                "inbound_mail.history",
                "inbound_mail_import",
                row.id,
                after={"days": days},
            )
            await session.refresh(row)
            out = view(row)
        try:
            await self._enqueue(out.id)
        except Exception:
            logger.exception("inbound_mail_history_enqueue_failed", import_id=out.id)
            await self._finish(out.id, "error", error_kind="unavailable")
            raise
        logger.info("inbound_mail_history_started", import_id=out.id, days=days)
        return out

    async def run(self, import_id: int) -> str:
        """Задача: найти письма за период, загрузить пачками, записать ход и итог."""
        async with self._sessions() as session:
            row = await session.get(InboundMailImport, import_id)
        if row is None or row.status != "running":
            return "skipped"
        resolved = await resolve_imap(self._store, self._settings)
        connection = resolved.connection
        if connection is None:
            return await self._finish(import_id, "error", error_kind="not_configured")
        try:
            found = await self._search(connection, resolved.folders, row.days)
        except ImapProbeError as exc:
            return await self._finish(import_id, "error", error_kind=exc.kind)
        chosen, limited = pick_history([(folder, uids) for folder, _, uids in found])
        validity = {folder.name: value for folder, value, _ in found}
        await self._progress(import_id, found=sum(len(uids) for _, uids in chosen), limited=limited)
        history_at = datetime.now(UTC)
        for folder, uids in chosen:
            for start in range(0, len(uids), FETCH_BATCH):
                chunk = uids[start : start + FETCH_BATCH]
                try:
                    messages = await self._client.fetch_uids(
                        in_folder(connection, folder.name), chunk
                    )
                except ImapProbeError as exc:
                    return await self._finish(import_id, "error", error_kind=exc.kind)
                created = 0
                for item in messages:
                    try:
                        mail_id = await self._ingest.store(
                            folder, validity[folder.name], item, history_at=history_at
                        )
                    except Exception:  # одно письмо не сломает загрузку; повтор её дозаберёт
                        logger.exception("inbound_mail_history_store_failed", uid=item.uid)
                        continue
                    created += mail_id is not None
                await self._progress(import_id, processed=len(chunk), created=created)
        return await self._finish(import_id, "done")

    async def _search(
        self, connection: ImapConnection, folders: Sequence[FolderSetting], days: int
    ) -> list[tuple[FolderSetting, int, list[int]]]:
        found: list[tuple[FolderSetting, int, list[int]]] = []
        for folder in folders:
            try:
                validity, uids = await self._client.search_since(
                    in_folder(connection, folder.name), days
                )
            except ImapProbeError as exc:
                if exc.kind == "mailbox_missing":  # папку удалили — остальные загружаем
                    logger.warning("inbound_mail_history_folder_missing", folder=folder.name)
                    continue
                raise
            found.append((folder, validity, uids))
        return found

    async def _progress(
        self,
        import_id: int,
        *,
        found: int | None = None,
        limited: bool | None = None,
        processed: int = 0,
        created: int = 0,
    ) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(InboundMailImport, import_id, with_for_update=True)
            if row is None:
                return
            if found is not None:
                row.found = found
            if limited is not None:
                row.limited = limited
            row.processed += processed
            row.created += created

    async def _finish(self, import_id: int, status: str, *, error_kind: str | None = None) -> str:
        async with self._sessions() as session, session.begin():
            row = await session.get(InboundMailImport, import_id, with_for_update=True)
            if row is not None:
                row.status, row.error_kind = status, error_kind
                row.finished_at = datetime.now(UTC)
        logger.info("inbound_mail_history_finished", import_id=import_id, status=status)
        return status
