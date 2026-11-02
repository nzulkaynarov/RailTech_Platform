"""Очередь «Входящая почта» (W18A-P2, B-INB-5): карточка письма и действия человека.

Право — раздел каталога «Лиды · разбор и передача» (`crm.leads.triage`, первая линия):
`mail_inbox:read` — очередь, карточка, вложения; `mail_inbox:work` — действия. Каждое действие
подтверждает человек одной кнопкой (ИИ только предлагает), строка письма блокируется
(`FOR UPDATE`) и уходит из очереди:

* «Создать лид» — лид из письма во «Входящих» без ответственного (как запрос с сайта: срок первого
  ответа, дальше «Забрать» у менеджера-универсала); открытый лид с этим адресом есть — письмо
  заметкой в него (DECISIONS 2026-11-01 п. 1: делопроизводитель — первая линия);
* «Архив» — с причиной;
* «Зарегистрировать ВХ» делает EDS (форма P8 с `source_mail_id`); CRM узнаёт номер из события
  `uz.railtech.eds.letter.registered.v1` (`accept_registered`, в транзакции inbox шины).

«Ответить» — письмо через почтовый сервис P1 в ту же цепочку (`In-Reply-To`, `References`), в
журнале доставки с объектом `inbound_mail:<id>`.
"""

from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from rt_bus import Event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.domain.errors import ConflictError, NotFoundError, UpstreamUnavailableError
from app.domain.inbound_mail import reply_subject, thread_references
from app.domain.lead_sources import LeadSource
from app.domain.stages import OwnerMode, Stage
from app.models.inbound_mail import InboundMail
from app.models.leads import Lead, LeadNote
from app.repositories import events
from app.repositories import inbound_mail as repo
from app.repositories import lead_intake as leads_repo
from app.repositories import users as users_repo
from app.schemas import inbound_mail as dto
from app.security import audit
from app.security.principal import Principal
from app.services import web_lead_sla
from app.services.mail import MailService
from app.services.mail_templates import RenderedEmail
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

LETTER_REGISTERED = "uz.railtech.eds.letter.registered.v1"
PAGE_LIMIT = 200
PREVIEW_CHARS = 200
_NOTE_MARK = "[почта] "
_SUMMARY_MAX = 2000


class Storage(Protocol):
    async def get(self, bucket: str, key: str) -> bytes: ...


def _assist(row: InboundMail) -> dto.InboundMailAssist:
    return dto.InboundMailAssist.model_validate(
        {
            "status": row.assist_status,
            "kind": row.assist_kind,
            "summary": row.assist_summary,
            "action": row.assist_action,
        }
    )


def _link(ids: dict[int, str], key: int | None) -> dto.InboundMailLink | None:
    return dto.InboundMailLink(id=key, name=ids.get(key, "")) if key is not None else None


def _item_fields(
    row: InboundMail, clients: dict[int, str], leads: dict[int, str]
) -> dict[str, Any]:
    return {
        "id": row.id,
        "status": row.status,
        "from_email": row.from_email,
        "from_name": row.from_name,
        "subject": row.subject,
        "received_at": row.received_at,
        "sent_at": row.sent_at,
        "preview": row.text[:PREVIEW_CHARS],
        "attachments_count": len(row.attachments or []),
        "assist": _assist(row),
        "client": _link(clients, row.client_id),
        "lead": _link(leads, row.matched_lead_id),
    }


class InboundMailService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        mail: MailService,
        storage: Storage,
        bucket: str,
        configured: Any,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._mail = mail
        self._storage = storage
        self._bucket = bucket
        # `async () -> bool`: настроен ли приём (резолвер IMAP «Подключений»).
        self._configured = configured

    async def page(self, status: dto.MailStatus) -> dto.InboundMailPage:
        async with self._sessions() as session:
            rows = await repo.page(session, status, PAGE_LIMIT)
            total = await repo.count(session, status)
            state = await repo.last_mailbox(session)
            clients, leads = await repo.names(
                session,
                [r.client_id for r in rows if r.client_id is not None],
                [r.matched_lead_id for r in rows if r.matched_lead_id is not None],
            )
        mailbox = dto.InboundMailbox(
            configured=await self._configured(),
            last_poll_at=state.last_poll_at if state else None,
            last_ok_at=state.last_ok_at if state else None,
            last_error_kind=state.last_error_kind if state else None,
        )
        items = [dto.InboundMailItem(**_item_fields(r, clients, leads)) for r in rows]
        return dto.InboundMailPage(items=items, total=total, mailbox=mailbox)

    async def get(self, mail_id: int) -> dto.InboundMailOut:
        async with self._sessions() as session:
            row = await repo.get(session, mail_id)
            if row is None:
                raise NotFoundError("mail not found")
            lead_ids = [i for i in (row.matched_lead_id, row.lead_id) if i is not None]
            clients, leads = await repo.names(
                session, [row.client_id] if row.client_id else [], lead_ids
            )
            replies = await repo.replies(session, mail_id)
        return dto.InboundMailOut(
            **_item_fields(row, clients, leads),
            to=list(row.to_addrs or []),
            text=row.text,
            attachments=[
                dto.InboundMailAttachment(
                    index=i, name=a["name"], content_type=a["content_type"], size=a["size"]
                )
                for i, a in enumerate(row.attachments or [])
            ],
            skipped=[dto.InboundMailSkipped.model_validate(s) for s in row.skipped or []],
            too_large=row.too_large,
            inns=list(row.inns or []),
            eds_letter_id=row.eds_letter_id,
            eds_letter_number=row.eds_letter_number,
            result_lead=_link(leads, row.lead_id),
            archive_reason=row.archive_reason,
            handled_at=row.handled_at,
            handled_by=row.handled_by,
            replies=[
                dto.InboundMailReply(
                    id=r.id,
                    to_email=r.to_email,
                    subject=r.subject,
                    status=r.status,
                    created_at=r.created_at,
                    sent_at=r.sent_at,
                )
                for r in replies
            ],
        )

    async def attachment(self, mail_id: int, index: int) -> tuple[bytes, str, str]:
        async with self._sessions() as session:
            row = await repo.get(session, mail_id)
        items = list(row.attachments or []) if row is not None else []
        if row is None or index >= len(items):
            raise NotFoundError("attachment not found")
        item = items[index]
        try:
            data = await self._storage.get(self._bucket, str(item["storage_key"]))
        except Exception as exc:  # хранилище недоступно: 502, а не 500
            logger.warning(
                "inbound_attachment_read_failed", mail_id=mail_id, error=type(exc).__name__
            )
            raise UpstreamUnavailableError("attachment storage unavailable") from exc
        return data, str(item["name"]), str(item["content_type"])

    async def create_lead(self, who: Principal, mail_id: int) -> dto.InboundMailLeadOut:
        now = datetime.now(UTC)
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            row = await _open_row(session, mail_id)
            existing = (
                await leads_repo.lead_by_email(session, row.from_email) if row.from_email else None
            )
            if existing is not None:
                await _note(session, existing, row, who)
                lead_id, created = existing.id, False
            else:
                lead = await _new_lead(session, row, now, web_lead_sla.due_at(cfg, now), who)
                lead_id, created = lead.id, True
            _handled(row, "lead", who, now)
            row.lead_id = lead_id
            await audit.record(
                session,
                who.actor,
                "inbound_mail.lead",
                "inbound_mail",
                row.id,
                after={"lead_id": lead_id, "created": created},
            )
        logger.info("inbound_mail_to_lead", mail_id=mail_id, lead_id=lead_id, created=created)
        return dto.InboundMailLeadOut(lead_id=lead_id, created=created)

    async def archive(self, who: Principal, mail_id: int, reason: str) -> None:
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            row = await _open_row(session, mail_id)
            _handled(row, "archived", who, now)
            row.archive_reason = reason.strip()[:500]
            await audit.record(
                session,
                who.actor,
                "inbound_mail.archive",
                "inbound_mail",
                row.id,
                after={"reason": row.archive_reason},
            )
        logger.info("inbound_mail_archived", mail_id=mail_id)

    async def reply(self, who: Principal, mail_id: int, text: str) -> dto.InboundMailReply:
        async with self._sessions() as session:
            row = await repo.get(session, mail_id)
        if row is None:
            raise NotFoundError("mail not found")
        if not row.from_email:
            raise ConflictError("mail has no sender address", field="from_email")
        rendered = RenderedEmail(subject=reply_subject(row.subject), body=text.strip(), lang="ru")
        view = await self._mail.send_rendered(
            "inbound_reply",
            row.from_email,
            rendered,
            requested_by=who.user_id,
            ref=(repo.REF_KIND, str(row.id)),
            thread_headers={
                "In-Reply-To": f"<{row.message_id}>",
                "References": thread_references(row.message_id, row.references),
            },
        )
        logger.info("inbound_mail_replied", mail_id=mail_id, email_log_id=view.id)
        return dto.InboundMailReply(
            id=view.id,
            to_email=row.from_email,
            subject=rendered.subject,
            status=view.status,
            created_at=view.created_at,
            sent_at=None,
        )

    async def accept_registered(self, session: AsyncSession, event: Event) -> None:
        """`eds.letter.registered` с `source.crm_inbound_mail_id`: письмо → ВХ, из очереди прочь.

        Повтор события — тот же итог; письмо уже в лиде или архиве — номер ВХ записывается, статус
        не меняется (два действия по одному письму видны в карточке).
        """
        data = _obj(event.data)
        mail_id = _obj(data.get("source")).get("crm_inbound_mail_id")
        if not isinstance(mail_id, int):
            return
        letter, actor = _obj(data.get("letter")), _obj(data.get("actor"))
        row = await repo.get(session, mail_id, for_update=True)
        if row is None:
            logger.warning("inbound_mail_registered_unknown", mail_id=mail_id)
            return
        row.eds_letter_id = str(letter.get("eds_letter_id") or "")[:64] or None
        row.eds_letter_number = str(letter.get("number") or "")[:32] or None
        if row.status == "new":
            row.status = "registered"
            row.handled_at = datetime.now(UTC)
            user = actor.get("crm_user_id")
            known = isinstance(user, int) and await users_repo.get(session, user) is not None
            row.handled_by = user if known and isinstance(user, int) else None
        logger.info("inbound_mail_registered", mail_id=mail_id, number=row.eds_letter_number)


def _obj(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


async def _open_row(session: AsyncSession, mail_id: int) -> InboundMail:
    row = await repo.get(session, mail_id, for_update=True)
    if row is None:
        raise NotFoundError("mail not found")
    if row.status != "new":
        raise ConflictError("mail is already handled", status=row.status)
    return row


def _handled(row: InboundMail, status: str, who: Principal, now: datetime) -> None:
    row.status = status
    row.handled_by = who.user_id
    row.handled_at = now


def _need(row: InboundMail) -> str:
    return f"{row.subject}\n\n{row.text}".strip()[:_SUMMARY_MAX]


async def _note(session: AsyncSession, lead: Lead, row: InboundMail, who: Principal) -> None:
    session.add(
        LeadNote(lead_id=lead.id, user_id=who.user_id, text=(_NOTE_MARK + _need(row))[:4000])
    )
    lead.notes_count += 1
    if not lead.need_summary:
        lead.need_summary = _need(row)
    await events.publish(session, "lead.updated", lead_id=lead.id)


async def _new_lead(
    session: AsyncSession, row: InboundMail, now: datetime, due: datetime, who: Principal
) -> Lead:
    """Лид во «Входящих» без ответственного — как запрос с сайта; «Забрать» — у менеджера."""
    lead = Lead(
        display_name=(row.from_name or row.from_email or "Письмо")[:255],
        language="ru",
        stage=Stage.NEW.value,
        owner_mode=OwnerMode.PAUSED.value,
        source=LeadSource.EMAIL.value,
        email=row.from_email or None,
        need_summary=_need(row),
        last_lead_msg_at=row.received_at,
        first_response_due_at=due,
    )
    session.add(lead)
    await session.flush()
    await audit.record(
        session,
        who.actor,
        "lead.create_mail",
        "lead",
        lead.id,
        after={"source": lead.source, "inbound_mail_id": row.id},
    )
    await bus_events.lead_created(session, lead, who.actor)
    await events.publish(session, "lead.updated", lead_id=lead.id, owner_mode="paused")
    return lead
