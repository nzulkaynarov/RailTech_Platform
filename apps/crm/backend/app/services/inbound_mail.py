"""Очередь «Входящая почта» (W18A-P2, B-INB-5; обращение — W18A-P2-3): карточка письма и действия.

Право — раздел каталога «Лиды · разбор и передача» (`crm.leads.triage`, первая линия):
`mail_inbox:read` — очередь, карточка, вложения; `mail_inbox:work` — действия. Остальной сотрудник
видит только письма, где он исполнитель или названный в «адресовано лично» (`can_see`), и может
ответить и вернуть своё письмо в «Новые». Состояния — `domain/inbound_mail_flow.py`, «в работе» —
`services/inbound_mail_work.py`: первое действие берёт письмо, строка блокируется (`FOR UPDATE`),
другому — 409 «уже в работе у …». Действие подтверждает человек одной кнопкой (ИИ только
предлагает):

* «Создать лид» — лид из письма во «Входящих» без ответственного (как запрос с сайта: срок первого
  ответа, дальше «Забрать» у менеджера-универсала); открытый лид с этим адресом есть — письмо
  заметкой в него (DECISIONS 2026-11-01 п. 1: делопроизводитель — первая линия) → «Разобрано: лид»;
* «Архив» — с причиной → «Разобрано: архив»; массово — `bulk_archive`;
* «Ответить» (всем) — почтовым сервисом P1 в ту же цепочку (`In-Reply-To`, `References` последнего
  входящего), в журнале доставки с объектом `inbound_mail:<id>` → «Разобрано: ответ отправлен»,
  «Ждём ответа» оставляет «в работе»;
* решение человека (ВХ, лид, архив) — в журнал ИИ: принял подсказку, выбрал другое или вручную;
* «Зарегистрировать ВХ» делает EDS (форма P8 с `source_mail_id`): BFF сначала помечает письмо
  «Регистрируется» (`registration`), CRM узнаёт номер из события
  `uz.railtech.eds.letter.registered.v1`
  (`accept_registered`, в транзакции inbox шины) → «Разобрано: ВХ».

Письма из спам-папки (W18A-P2-2, эталон — Zendesk «Suspended tickets») — статус `spam`, вкладка
«Подозрительные»: «Не спам» — в очередь (`new`), «Убрать» — в архив с причиной «Спам». Ящик на
сервере
не меняется (только чтение).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from rt_bus import Event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.domain.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.domain.inbound_mail import reply_subject, thread_references
from app.domain.inbound_mail_flow import can_see, chain_addresses, reply_all_copy, reply_default
from app.domain.lead_sources import LeadSource
from app.domain.stages import OwnerMode, Stage
from app.models.inbound_mail import InboundMail
from app.models.leads import Lead, LeadNote
from app.repositories import events
from app.repositories import inbound_mail as repo
from app.repositories import inbound_mail_views as views
from app.repositories import lead_intake as leads_repo
from app.repositories import users as users_repo
from app.schemas import inbound_mail as dto
from app.security import audit
from app.security.principal import Principal
from app.services import inbound_mail_view as view
from app.services import inbound_mail_work as work
from app.services import web_lead_sla
from app.services.inbound_mail_assist import record_decision
from app.services.mail import MailService
from app.services.mail_templates import RenderedEmail
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

LETTER_REGISTERED = "uz.railtech.eds.letter.registered.v1"
PAGE_LIMIT = 200
SPAM_REASON = "Спам"
_NOTE_MARK = "[почта] "
_SUMMARY_MAX = 2000


class Storage(Protocol):
    async def get(self, bucket: str, key: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class MailAccess:
    """Кто обращается и видит ли всю очередь (`mail_inbox:read`) или только свои письма."""

    who: Principal
    full: bool

    @property
    def scope(self) -> views.Scope:
        return views.Scope(self.who.user_id, self.full)


class InboundMailService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        mail: MailService,
        storage: Storage,
        bucket: str,
        configured: Any,
        mailbox_address: Callable[[], Awaitable[str | None]] | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._mail = mail
        self._storage = storage
        self._bucket = bucket
        # `async () -> bool`: настроен ли приём (резолвер IMAP «Подключений»).
        self._configured = configured
        # Адрес самого общего ящика (логин приёма): его нет в «Ответить всем».
        self._mailbox_address = mailbox_address

    async def _mailbox(self) -> str | None:
        return await self._mailbox_address() if self._mailbox_address else None

    async def _assist_on(self) -> bool:
        return (await self._settings.get()).integrations.imap.assist_enabled

    @staticmethod
    def _check_visible(access: MailAccess, row: InboundMail) -> None:
        staff = [*(row.to_staff_ids or []), *(row.cc_staff_ids or [])]
        if not can_see(access.full, access.who.user_id, row.assignee_id, row.personal, staff):
            raise ForbiddenError("mail is not addressed to you", resource="mail_inbox")

    async def _visible_row(
        self, session: AsyncSession, access: MailAccess, mail_id: int, *, lock: bool = False
    ) -> InboundMail:
        """Запись (корень цепочки) с проверкой, что сотрудник её видит."""
        row = await (work.lock(session, mail_id) if lock else repo.get(session, mail_id))
        if row is None or row.thread_root_id is not None:
            raise NotFoundError("mail not found")
        self._check_visible(access, row)
        return row

    async def page(
        self,
        access: MailAccess,
        mail_view: views.View = "new",
        history: bool | None = None,
        q: str | None = None,
        type_code: str | None = None,
    ) -> dto.InboundMailPage:
        """`history`: `false` — без писем «из истории», `true` — только они (вкладка «Новые»);
        `type_code` — только письма этого типа."""
        now = datetime.now(UTC)
        on = await self._assist_on()
        async with self._sessions() as session:
            items, total, counts = await view.build_page(
                session,
                mail_view,
                access.scope,
                limit=PAGE_LIMIT,
                history=history,
                q=q,
                assist_on=on,
                now=now,
                type_code=type_code,
            )
            state = await repo.last_mailbox(session)
        mailbox = dto.InboundMailbox(
            configured=await self._configured(),
            last_poll_at=state.last_poll_at if state else None,
            last_ok_at=state.last_ok_at if state else None,
            last_error_kind=state.last_error_kind if state else None,
            personal_label=(await self._settings.get()).integrations.imap.personal_label,
        )
        return dto.InboundMailPage(items=items, total=total, mailbox=mailbox, counts=counts)

    async def get(self, access: MailAccess, mail_id: int) -> dto.InboundMailOut:
        cfg = await self._settings.get()
        mailbox = await self._mailbox()
        async with self._sessions() as session:
            row = await self._visible_row(session, access, mail_id)
            return await view.build_card(
                session,
                row,
                access.scope,
                assist_on=cfg.integrations.imap.assist_enabled,
                personal_label=cfg.integrations.imap.personal_label,
                mailbox=mailbox,
                now=datetime.now(UTC),
            )

    async def mark_read(self, access: MailAccess, mail_id: int) -> None:
        """«Открыл карточку — прочитано» (на человека)."""
        async with self._sessions() as session, session.begin():
            row = await self._visible_row(session, access, mail_id)
            await views.mark_read(session, row.id, access.who.user_id, datetime.now(UTC))

    async def attachment(
        self, access: MailAccess, mail_id: int, index: int
    ) -> tuple[bytes, str, str]:
        """Вложение письма записи (корня или ответа клиента в цепочке)."""
        async with self._sessions() as session:
            row = await repo.get(session, mail_id)
            if row is not None:
                await self._visible_row(session, access, row.thread_root_id or row.id)
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

    async def take(self, who: Principal, mail_id: int, takeover: bool = False) -> None:
        async with self._sessions() as session, session.begin():
            await work.take(session, who, mail_id, datetime.now(UTC), takeover=takeover)
        logger.info("inbound_mail_taken", mail_id=mail_id, takeover=takeover)

    async def release(self, access: MailAccess, mail_id: int) -> None:
        async with self._sessions() as session, session.begin():
            await self._visible_row(session, access, mail_id)
            await work.release(session, access.who, mail_id, full=access.full)
        logger.info("inbound_mail_released", mail_id=mail_id)

    async def registration(self, who: Principal, mail_id: int, state: str) -> None:
        async with self._sessions() as session, session.begin():
            await work.registration(session, who, mail_id, datetime.now(UTC), state)

    async def bulk_archive(
        self, who: Principal, ids: list[int], reason: str
    ) -> dto.InboundMailBulkArchiveOut:
        async with self._sessions() as session, session.begin():
            result = await work.bulk_archive(session, who, ids, reason, datetime.now(UTC))
        logger.info("inbound_mail_bulk_archived", count=len(result.archived))
        return dto.InboundMailBulkArchiveOut(archived=result.archived, skipped=result.skipped)

    async def create_lead(self, who: Principal, mail_id: int) -> dto.InboundMailLeadOut:
        now = datetime.now(UTC)
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            row = await work.lock(session, mail_id)
            await work.claim(session, row, who, now)
            existing = (
                await leads_repo.lead_by_email(session, row.from_email) if row.from_email else None
            )
            if existing is not None:
                await _note(session, existing, row, who)
                lead_id, created = existing.id, False
            else:
                lead = await _new_lead(session, row, now, web_lead_sla.due_at(cfg, now), who)
                lead_id, created = lead.id, True
            work.finish(row, "lead", who, now)
            await record_decision(session, row, "create_lead", who.actor)
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
            row = await work.lock(session, mail_id)
            await work.claim(session, row, who, now)
            work.finish(row, "archived", who, now)
            await record_decision(session, row, "archive_mailing", who.actor)
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

    async def not_spam(self, who: Principal, mail_id: int) -> None:
        """«Не спам → в очередь»: письмо становится обычным «Новое»."""
        async with self._sessions() as session, session.begin():
            row = await _spam_row(session, mail_id)
            row.status = "new"
            await audit.record(
                session, who.actor, "inbound_mail.not_spam", "inbound_mail", row.id, after={}
            )
        logger.info("inbound_mail_not_spam", mail_id=mail_id)

    async def discard(self, who: Principal, mail_id: int) -> None:
        """«Убрать» подозрительное письмо: в архив с причиной «Спам» (ничего не удаляется)."""
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            row = await _spam_row(session, mail_id)
            work.finish(row, "archived", who, now)
            row.archive_reason = SPAM_REASON
            await audit.record(
                session,
                who.actor,
                "inbound_mail.discard",
                "inbound_mail",
                row.id,
                after={"reason": SPAM_REASON},
            )
        logger.info("inbound_mail_discarded", mail_id=mail_id)

    async def reply(
        self,
        access: MailAccess,
        mail_id: int,
        text: str,
        *,
        reply_all: bool = False,
        awaiting: bool = False,
        to: str | None = None,
    ) -> dto.InboundMailReply:
        """Ответ на последнее входящее письмо записи; письмо берётся (первое действие) и после
        отправки — «Разобрано: ответ отправлен», если не «Ждём ответа»."""
        who, now = access.who, datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            row = await self._visible_row(session, access, mail_id, lock=True)
            if not access.full and row.assignee_id != who.user_id:
                raise ForbiddenError("mail is not yours", resource="mail_inbox")
            await work.claim(session, row, who, now)
            latest = await views.latest_incoming(session, row.id) or row
            if not row.from_email:
                raise ConflictError("mail has no sender address", field="from_email")
            mailbox = await self._mailbox()
            options = chain_addresses(await views.chain_messages(session, row.id), mailbox)
            address = (to or "").strip().lower() or reply_default(
                row.from_email.lower(), latest.from_email.lower(), latest.new_participant
            )
            if address not in options:  # адресат — только из цепочки: подделка `From` его не задаёт
                raise ValidationFailedError("reply address is not in the thread", field="to")
            subject = reply_subject(row.subject)
            headers = {
                "In-Reply-To": f"<{latest.message_id}>",
                "References": thread_references(latest.message_id, latest.references),
            }
            copy = reply_all_copy(latest.to_addrs or [], latest.cc_addrs or [], mailbox, address)
        sent = await self._mail.send_rendered(
            "inbound_reply",
            address,
            RenderedEmail(subject=subject, body=text.strip(), lang="ru"),
            requested_by=who.user_id,
            ref=(repo.REF_KIND, str(mail_id)),
            thread_headers=headers,
            cc=copy if reply_all else (),
        )
        await self._after_reply(who, mail_id, now, awaiting, copy if reply_all else [])
        logger.info("inbound_mail_replied", mail_id=mail_id, email_log_id=sent.id)
        return dto.InboundMailReply(
            id=sent.id,
            to_email=address,
            subject=subject,
            status=sent.status,
            created_at=sent.created_at,
            sent_at=None,
            by=dto.InboundMailPerson(id=who.user_id, name=who.full_name),
        )

    async def _after_reply(
        self, who: Principal, mail_id: int, now: datetime, awaiting: bool, copy: list[str]
    ) -> None:
        async with self._sessions() as session, session.begin():
            row = await work.lock(session, mail_id)
            await audit.record(
                session,
                who.actor,
                "inbound_mail.reply",
                "inbound_mail",
                row.id,
                after={"awaiting": awaiting, "copy": len(copy)},
            )
            mine = row.status == "in_work" and row.assignee_id == who.user_id
            if mine and not awaiting:
                work.finish(row, "replied", who, now)

    async def accept_registered(self, session: AsyncSession, event: Event) -> None:
        """`eds.letter.registered` с `source.crm_inbound_mail_id`: письмо → «Разобрано: ВХ».

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
        if row.status in ("new", "in_work", "registering"):
            # Новое письмо клиента после начала регистрации: итог ВХ записан, запись снова «Новое».
            newer_reply = row.registering_at is not None and row.activity_at > row.registering_at
            row.status, row.outcome = "done", "registered"
            row.handled_at = datetime.now(UTC)
            row.registering_at, row.thread_reply = None, False
            user = actor.get("crm_user_id")
            known = isinstance(user, int) and await users_repo.get(session, user) is not None
            row.handled_by = user if known and isinstance(user, int) else None
            who = audit.Actor(row.handled_by) if row.handled_by else audit.Actor.system()
            await record_decision(session, row, "register_incoming", who)
            if newer_reply:  # клиент ответил, пока ВХ создавался: письмо не уходит из виду
                row.status, row.thread_reply = "new", True
                row.outcome = row.handled_by = row.handled_at = None
        logger.info("inbound_mail_registered", mail_id=mail_id, number=row.eds_letter_number)


def _obj(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


async def _spam_row(session: AsyncSession, mail_id: int) -> InboundMail:
    row = await work.lock(session, mail_id)
    if row.status != "spam":
        raise work.handled(row)
    return row


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
