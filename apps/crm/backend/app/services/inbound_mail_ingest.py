"""Опрос общего ящика (W18A-P2, B-INB-5): новые письма → очередь «Входящая почта».

Задача Procrastinate раз в 2 минуты (`app/tasks/inbound_mail.py`, одна одновременно). Порядок:
настройки «Подключений» → IMAP только на чтение → письма с UID больше запомненного (первый опрос и
смена UIDVALIDITY — за последние дни) → разбор (`domain/inbound_mail.py`) → вложения в бакет
вложений CRM → строка `inbound_mail` (UNIQUE `message_id`: повтор дубля не даёт) → UID и итог опроса
в `inbound_mailbox`. Подсказку помощника опрос не запрашивает (только кнопка). Сбой IMAP —
итог с причиной в состоянии папки (строка здоровья), письма не теряются: UID не сдвигается.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.inbound_mail import ParsedMail, find_inns, parse_message
from app.integrations.imap import FetchedMessage, ImapClient, ImapProbeError, resolve_imap
from app.models.inbound_mail import InboundMailbox
from app.repositories import inbound_mail as repo
from app.repositories import lead_intake as leads_repo
from app.security.secrets_store import SecretsStore
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

STORAGE_PREFIX = "mail/"


class Storage(Protocol):
    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None: ...


NewMailHook = Callable[[list[int]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PollOutcome:
    status: Literal["off", "ok", "error"]
    fetched: int = 0
    created: int = 0
    error_kind: str | None = None


class InboundMailIngest:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        store: SecretsStore,
        settings: SettingsService,
        client: ImapClient,
        storage: Storage,
        bucket: str,
        on_new: NewMailHook | None = None,
    ) -> None:
        self._sessions = sessions
        self._store = store
        self._settings = settings
        self._client = client
        self._storage = storage
        self._bucket = bucket
        self._on_new = on_new

    async def poll(self) -> PollOutcome:
        connection = (await resolve_imap(self._store, self._settings)).connection
        if connection is None:
            return PollOutcome("off")
        name = connection.mailbox
        async with self._sessions() as session:
            state = await repo.mailbox(session, name)
        same_host = state is not None and state.host == connection.host
        uidvalidity = state.uidvalidity if state is not None and same_host else None
        last_uid = state.last_uid if state is not None and same_host else None
        now = datetime.now(UTC)
        try:
            batch = await self._client.fetch(connection, uidvalidity, last_uid)
        except ImapProbeError as exc:
            logger.warning("inbound_mail_poll_failed", kind=exc.kind, detail=exc.detail)
            await self._save_state(name, connection.host, now, error=exc)
            return PollOutcome("error", error_kind=exc.kind)
        created: list[int] = []
        done: list[int] = []
        for item in batch.messages:
            try:
                mail_id = await self._store_one(name, batch.uidvalidity, item)
            except (
                Exception
            ):  # хранилище или база: UID не сдвигаем — письмо заберёт следующий опрос
                logger.exception("inbound_mail_store_failed", uid=item.uid)
                break
            done.append(item.uid)
            if mail_id is not None:
                created.append(mail_id)
        top = max(done, default=None)
        if batch.uidvalidity != uidvalidity:
            new_last = top if top is not None else None
        else:
            new_last = max(top or 0, last_uid or 0) or None
        await self._save_state(
            name,
            connection.host,
            now,
            uidvalidity=batch.uidvalidity,
            last_uid=new_last,
            fetched=len(batch.messages),
        )
        logger.info("inbound_mail_polled", fetched=len(batch.messages), created=len(created))
        if created and self._on_new is not None:
            try:
                await self._on_new(created)
            except Exception:  # письма уже в очереди; подсказка — не обязательна
                logger.exception("inbound_mail_assist_enqueue_failed")
        return PollOutcome("ok", len(batch.messages), len(created))

    async def _store_one(self, mailbox: str, uidvalidity: int, item: FetchedMessage) -> int | None:
        parsed = parse_message(item.raw)
        async with self._sessions() as session:
            if await repo.exists(session, parsed.message_id):
                return None
        files = await self._put_files(parsed)
        async with self._sessions() as session, session.begin():
            values = await _row(session, parsed, files)
            values.update(
                mailbox=mailbox, uidvalidity=uidvalidity, uid=item.uid, too_large=item.too_large
            )
            mail_id = await repo.insert_new(session, values)
        if mail_id is not None:
            logger.info("inbound_mail_stored", mail_id=mail_id, files=len(files))
        return mail_id

    async def _put_files(self, parsed: ParsedMail) -> list[dict[str, object]]:
        stored: list[dict[str, object]] = []
        folder = f"{STORAGE_PREFIX}{uuid.uuid4().hex}"
        for index, item in enumerate(parsed.files):
            key = f"{folder}/{index}"
            await self._storage.put(self._bucket, key, item.data, item.content_type)
            stored.append(
                {
                    "name": item.name,
                    "content_type": item.content_type,
                    "size": len(item.data),
                    "storage_key": key,
                }
            )
        return stored

    async def _save_state(
        self,
        name: str,
        host: str,
        now: datetime,
        *,
        error: ImapProbeError | None = None,
        uidvalidity: int | None = None,
        last_uid: int | None = None,
        fetched: int = 0,
    ) -> None:
        async with self._sessions() as session, session.begin():
            state = await repo.mailbox(session, name, for_update=True)
            if state is None:
                state = InboundMailbox(mailbox=name, host=host, fetched_total=0)
                session.add(state)
            state.last_poll_at = now
            if error is not None:
                state.last_error_kind, state.last_error = error.kind, error.detail or None
                return
            state.host = host
            state.uidvalidity, state.last_uid = uidvalidity, last_uid
            state.last_ok_at = now
            state.last_error_kind = state.last_error = None
            state.fetched_total = (state.fetched_total or 0) + fetched


async def _row(
    session: AsyncSession, parsed: ParsedMail, files: list[dict[str, object]]
) -> dict[str, object]:
    inns = find_inns(f"{parsed.subject}\n{parsed.text}")
    client = await repo.client_by_email(session, parsed.from_email) if parsed.from_email else None
    if client is None:
        client = await repo.client_by_inns(session, inns)
    lead = await leads_repo.lead_by_email(session, parsed.from_email) if parsed.from_email else None
    return {
        "message_id": parsed.message_id,
        "from_email": parsed.from_email,
        "from_name": parsed.from_name,
        "to_addrs": list(parsed.to),
        "subject": parsed.subject,
        "sent_at": parsed.sent_at,
        "in_reply_to": parsed.in_reply_to,
        "references": parsed.references,
        "text": parsed.text,
        "attachments": files,
        "skipped": [{"name": s.name, "reason": s.reason} for s in parsed.skipped],
        "inns": inns,
        "client_id": client[0] if client else None,
        "matched_lead_id": lead.id if lead is not None else None,
    }
