"""Опрос общего ящика (W18A-P2, B-INB-5): новые письма → очередь «Входящая почта».

Задача Procrastinate раз в 2 минуты (`app/tasks/inbound_mail.py`, одна одновременно). Порядок:
настройки «Подключений» → IMAP только на чтение → письма с UID больше запомненного (первый опрос и
смена UIDVALIDITY — за последние дни) → разбор (`domain/inbound_mail.py`) → вложения в бакет
вложений CRM → строка `inbound_mail` (UNIQUE `message_id`: повтор дубля не даёт) → UID и итог опроса
в `inbound_mailbox`. Подсказку помощника опрос не запрашивает (только кнопка). Сбой IMAP —
итог с причиной в состоянии папки (строка здоровья), письма не теряются: UID не сдвигается.

Папок несколько (W18A-P2-2): у каждой своё состояние (UIDVALIDITY, UID). Письмо из спам-папки —
статус `spam` («Подозрительные»); то же письмо (Message-ID) в обычной папке — одна строка, из `spam`
в `new`.
Загрузка истории (`inbound_mail_history.py`) пишет письма тем же `store` с пометкой «из истории».

Обращение (W18A-P2-3): ответ клиента по `In-Reply-To`/`References` на известное письмо
прикрепляется к
той же записи (`thread_root_id`) и переоткрывает разобранную; письмо с сотрудником в «Кому» и общим
ящиком в копии при включённом правиле сразу «в работе» у этого сотрудника («адресовано лично»).
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.inbound_folders import FolderSetting, is_history
from app.domain.inbound_mail import ParsedMail, find_inns, parse_message
from app.domain.inbound_mail_flow import (
    chain_addresses,
    classify_recipients,
    is_new_participant,
    status_after_reply,
    thread_ids,
)
from app.integrations.imap import (
    FetchedMessage,
    ImapClient,
    ImapConnection,
    ImapProbeError,
    in_folder,
    resolve_imap,
)
from app.models.inbound_mail import InboundMail
from app.repositories import inbound_mail as repo
from app.repositories import inbound_mail_views as views
from app.repositories import lead_intake as leads_repo
from app.security import audit
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
        resolved = await resolve_imap(self._store, self._settings)
        connection = resolved.connection
        if connection is None:
            return PollOutcome("off")
        fetched, created, error = 0, [], None
        for folder in resolved.folders:
            try:
                count, ids = await self._poll_folder(connection, folder)
            except ImapProbeError as exc:
                error = error or exc
                if exc.kind != "mailbox_missing":  # вход или сеть: остальные папки не пробуем
                    break
                continue
            fetched += count
            created += ids
        logger.info("inbound_mail_polled", fetched=fetched, created=len(created))
        await self._notify(created)
        if error is not None:
            return PollOutcome("error", fetched, len(created), error_kind=error.kind)
        return PollOutcome("ok", fetched, len(created))

    async def _notify(self, created: list[int]) -> None:
        if created and self._on_new is not None:
            try:
                await self._on_new(created)
            except Exception:  # письма уже в очереди; подсказка — не обязательна
                logger.exception("inbound_mail_assist_enqueue_failed")

    async def _poll_folder(
        self, connection: ImapConnection, folder: FolderSetting
    ) -> tuple[int, list[int]]:
        name = folder.name
        async with self._sessions() as session:
            state = await repo.mailbox(session, name)
        same_host = state is not None and state.host == connection.host
        uidvalidity = state.uidvalidity if state is not None and same_host else None
        last_uid = state.last_uid if state is not None and same_host else None
        now = datetime.now(UTC)
        try:
            batch = await self._client.fetch(in_folder(connection, name), uidvalidity, last_uid)
        except ImapProbeError as exc:
            logger.warning("inbound_mail_poll_failed", kind=exc.kind, detail=exc.detail)
            await self._save_state(name, connection.host, now, error=exc)
            raise
        created: list[int] = []
        done: list[int] = []
        for item in batch.messages:
            try:
                mail_id = await self.store(
                    folder, batch.uidvalidity, item, mailbox_address=connection.username
                )
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
        return len(batch.messages), created

    async def store(
        self,
        folder: FolderSetting,
        uidvalidity: int,
        item: FetchedMessage,
        *,
        history_at: datetime | None = None,
        mailbox_address: str = "",
    ) -> int | None:
        """Письмо → строка очереди; уже есть (Message-ID) — None. `history_at` — время загрузки
        истории: письмо старше окна задач помечается «из истории». `mailbox_address` — адрес самого
        общего ящика (логин приёма) для правила «адресовано лично»."""
        parsed = parse_message(item.raw)
        async with self._sessions() as session, session.begin():
            if await repo.exists(session, parsed.message_id):
                if not folder.spam and await repo.promote_from_spam(
                    session, parsed.message_id, folder.name
                ):
                    logger.info("inbound_mail_left_spam", folder=folder.name)
                return None
        files = await self._put_files(parsed)
        rule_on = (await self._settings.get()).integrations.imap.personal_rule
        async with self._sessions() as session, session.begin():
            now = datetime.now(UTC)
            values = await _row(session, parsed, files)
            values.update(
                mailbox=folder.name,
                uidvalidity=uidvalidity,
                uid=item.uid,
                too_large=item.too_large,
                status="spam" if folder.spam else "new",
                from_history=history_at is not None and is_history(parsed.sent_at, history_at),
                activity_at=min(parsed.sent_at, now) if parsed.sent_at else now,
            )
            root = None
            if (
                not folder.spam
            ):  # из спама цепочку не продолжаем: подделка `In-Reply-To` не оживит запись
                ids = thread_ids(parsed.in_reply_to, parsed.references)
                root = await views.thread_root(session, ids, for_update=True)
            if root is not None:
                known = await views.chain_messages(session, root.id)
                values.update(
                    thread_root_id=root.id,
                    status="done",
                    new_participant=is_new_participant(
                        parsed.from_email, chain_addresses(known, mailbox_address)
                    ),
                )
            else:
                await _personal(session, parsed, values, mailbox_address, rule_on, now)
            mail_id = await repo.insert_new(session, values)
            if mail_id is not None and root is not None:
                await _attach(session, root, mail_id, values["activity_at"])  # type: ignore[arg-type]
            elif mail_id is not None and values.get("personal"):
                await audit.record(
                    session,
                    audit.Actor.system(),
                    "inbound_mail.personal",
                    "inbound_mail",
                    mail_id,
                    after={"assignee_id": values["assignee_id"]},
                )
        if mail_id is not None:
            logger.info("inbound_mail_stored", mail_id=mail_id, files=len(files), spam=folder.spam)
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
            state = await repo.lock_mailbox(session, name, host)
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
        "cc_addrs": list(parsed.cc),
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


async def _personal(
    session: AsyncSession,
    parsed: ParsedMail,
    values: dict[str, object],
    mailbox_address: str,
    rule_on: bool,
    now: datetime,
) -> None:
    """Адресаты письма: сотрудники из «Кому» и копии; «лично» — сразу «в работе» у первого."""
    staff = await views.staff_by_email(session, [*parsed.to, *parsed.cc])
    found = classify_recipients(parsed.to, parsed.cc, mailbox_address, staff, rule_on=rule_on)
    values.update(
        to_staff_ids=list(found.to_staff),
        cc_staff_ids=list(found.cc_staff),
        personal=found.personal,
    )
    if found.personal and values["status"] == "new":
        values.update(status="in_work", assignee_id=found.assignee_id, assigned_at=now)


async def _attach(session: AsyncSession, root: InboundMail, child_id: int, at: datetime) -> None:
    """Ответ клиента — к записи: видно новое письмо (снова «не прочитано»), запись помечена «ответ
    в цепочке» в любом рабочем состоянии (Новое, В работе, Регистрируется), а разобранная снова
    «Новое (ответ в цепочке)» с прежним исполнителем в справке."""
    root.activity_at = max(root.activity_at, at)
    reopened = status_after_reply(root.status) != root.status
    if reopened:
        root.status = "new"
        root.outcome = root.archive_reason = None
        root.handled_by = root.handled_at = None
    if root.status != "spam":
        root.thread_reply = True
    await audit.record(
        session,
        audit.Actor.system(),
        "inbound_mail.thread_reply",
        "inbound_mail",
        root.id,
        after={"mail_id": child_id, "reopened": reopened},
    )
