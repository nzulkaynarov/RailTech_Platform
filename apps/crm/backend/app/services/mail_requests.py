"""Письма ERP и EDS — запросом по шине, отправляет почтовый сервис CRM (W18A-P1, B-INB-6).

Исходящую почту ансамбля отправляет только CRM — через SMTP карточки «Почта». ERP и EDS рендерят
тему, текст и HTML своим шаблоном и публикуют `uz.railtech.<домен>.mail.requested.v1` в транзакции
своего изменения; здесь — приём такого события в транзакции записи inbox:

* идемпотентность: строка журнала на (`source`, `request_key`) одна (UNIQUE): повтор события, в том
  числе повторная публикация с новым id конверта, второго письма не даёт;
* тело открывается ключом пары «<домен> → crm» (`app/services/mail_content.py`) и сразу ложится в
  журнал шифртекстом `SECRETS_KEY`, как тело своих писем CRM; ссылки на вложения — тоже;
* почта не настроена или тело не открывается — строка с итогом сразу (`skipped_no_smtp` / `failed`)
  и, если отправитель просил (`notify`), событие `crm.mail.failed` в той же транзакции;
* постановка в очередь — после коммита обработки (`dispatch`, хук `after_processed` шины): задача,
  поставленная до коммита, могла бы не увидеть строку. Потерянную постановку подбирает сборщик
  (`MailService.sweep`).
"""

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final

import structlog
from rt_bus import Event
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.models.email import EmailLog
from app.services.mail import MailService
from app.services.mail_content import ContentUnreadableError, open_content

logger = structlog.get_logger(__name__)

#: Тип запроса → система-источник (`email_log.source`).
MAIL_REQUEST_TYPES: Final = {
    "uz.railtech.erp.mail.requested.v1": "erp",
    "uz.railtech.eds.mail.requested.v1": "eds",
}
SERVICE: Final = "crm"

PairSecrets = Callable[[str, str], Sequence[str]]
Refresh = Callable[[], Awaitable[None]]


async def _no_refresh() -> None:
    return None


class MailRequestService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        mail: MailService,
        secrets: PairSecrets,
        *,
        refresh: Refresh = _no_refresh,
    ) -> None:
        self._sessions = sessions
        self._mail = mail
        self._secrets = secrets
        self._refresh = refresh

    async def accept(self, session: AsyncSession, event: Event) -> int | None:
        """Строка журнала по запросу (в транзакции inbox). None — такой запрос уже принят."""
        requester = MAIL_REQUEST_TYPES[event.type]
        data: dict[str, Any] = dict(event.data)
        key = str(data["request_key"])
        if await self._known(session, requester, key):
            logger.info("mail_request_duplicate", source=requester, request_key=key)
            return None
        row = self._row(requester, str(event.id), data)
        await self._fill(row, requester, data)
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            # Тот же ключ принят параллельно другим воркером: второе письмо не нужно.
            logger.info("mail_request_duplicate", source=requester, request_key=key)
            return None
        if row.status != "queued":
            await bus_events.mail_result(session, row)
        logger.info(
            "mail_request_accepted",
            email_log_id=row.id,
            source=requester,
            purpose=row.purpose,
            status=row.status,
            attachments=len(row.attachments or []),
        )
        return row.id

    async def dispatch(self, event_id: str) -> int:
        """После коммита обработки события: его письмо — в очередь отправки."""
        async with self._sessions() as session:
            ids = list(
                (
                    await session.scalars(
                        select(EmailLog.id).where(
                            EmailLog.bus_event_id == event_id,
                            EmailLog.status == "queued",
                            EmailLog.body_ciphertext.is_not(None),
                        )
                    )
                ).all()
            )
        return await self._mail.enqueue(ids)

    @staticmethod
    async def _known(session: AsyncSession, source: str, key: str) -> bool:
        found = await session.scalar(
            select(EmailLog.id).where(EmailLog.source == source, EmailLog.request_key == key)
        )
        return found is not None

    @staticmethod
    def _row(requester: str, event_id: str, data: dict[str, Any]) -> EmailLog:
        purpose = str(data["purpose"])
        ref = data.get("ref") or {}
        return EmailLog(
            to_email=", ".join(str(a).strip().lower() for a in data["to"]),
            subject=str(data["subject"])[:255],
            template=purpose[:64],
            lang=str(data.get("language") or "ru")[:2],
            status="queued",
            attempts=0,
            source=requester,
            purpose=purpose[:64],
            request_key=str(data["request_key"]),
            bus_event_id=event_id,
            ref_kind=ref.get("kind"),
            ref_id=str(ref["id"]) if ref.get("id") is not None else None,
            reply_to=data.get("reply_to"),
            notify=bool(data.get("notify", False)),
            attachments=[
                {k: item[k] for k in ("filename", "content_type", "size", "sha256")}
                for item in data.get("attachments") or []
            ]
            or None,
        )

    async def _fill(self, row: EmailLog, requester: str, data: dict[str, Any]) -> None:
        """Тело — шифртекстом `SECRETS_KEY`; не открыть или некуда слать — итог сразу."""
        cipher = self._mail.cipher
        connection = (await self._mail.resolution()).connection
        if connection is None or cipher is None:
            row.status = "skipped_no_smtp"
            row.error = "smtp_not_configured" if connection is None else "secrets_key_missing"
            return
        await self._refresh()
        content = data["content"]
        try:
            opened = open_content(
                str(content["alg"]), str(content["ciphertext"]), self._secrets(requester, SERVICE)
            )
        except ContentUnreadableError as exc:
            logger.warning("mail_request_unreadable", source=requester, error=str(exc))
            row.status, row.error = "failed", "content_unreadable"
            return
        if len(opened.links) != len(row.attachments or []):
            row.status, row.error = "failed", "attachment_unavailable: links do not match"
            return
        row.body_ciphertext = cipher.encrypt(opened.text)
        if opened.html:
            row.html_ciphertext = cipher.encrypt(opened.html)
        if opened.links:
            row.links_ciphertext = cipher.encrypt(json.dumps([link.url for link in opened.links]))
