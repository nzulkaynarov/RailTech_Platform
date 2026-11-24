"""Отправка писем сотрудникам через коннектор «Почта» (M3-CRM-08, ARCHITECTURE §18).

`send()` — в пути запроса только рендер и запись в журнал `email_log`; само письмо уходит задачей
Procrastinate (`tasks/mail.py` → `deliver()`), чтобы медленный релей не держал запрос. Без
коннектора письмо не ставится: в журнале `skipped_no_smtp`, вызывающему — 409 `smtp_not_configured`
(«Настройте коннектор «Почта»»). Тело письма содержит временный пароль, поэтому до отправки лежит
в журнале только шифртекстом (`SECRETS_KEY`) и стирается после отправки или последней попытки.
Исключение (MAIL-2, DECISIONS 2026-11-11 п. 3): текст писем без секретов (документы, письма EDS
и ERP) хранится год ради «Почта · Отправленные» и «Отправить ещё раз» (`resend()`); письма со
входом, паролем, кодом или приглашением (`keeps_body()` — нет) стираются как прежде и не
повторяются.
Рассылки клиентам этим сервисом не делаются (ARCHITECTURE §18).

Выключатель «Почта» в центре внешних сервисов (ADR-0024) — пауза очереди: письмо остаётся в
журнале `queued` (тело шифртекстом) и не ставится в очередь, воркер `queued` не отправляет;
`resume_queued()` при включении ставит ожидающие письма в очередь заново.

Один отправитель ансамбля (W18A-P1, B-INB-6): письма ERP и EDS приходят запросом по шине
(`app/services/mail_requests.py`) и уходят тем же `deliver()` — с HTML, ответом на другой адрес
и вложениями по ссылке (`app/integrations/mail_attachments.py`). Временная ошибка (сеть, TLS,
вход, 4xx) оставляет строку `queued` с причиной и повторяется задачей; постоянная (5xx на адрес,
отправителя или данные, недоступное вложение) или последняя попытка — `failed` с причиной.
Итог письма другой системы с `notify` уходит ей событием `crm.mail.sent|failed` в той же
транзакции, что и статус (`app/bus/events.py`).
"""

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.config import Settings
from app.domain.errors import ConflictError, MailTemplateMissingError, Reason
from app.integrations.mail_attachments import AttachmentError, AttachmentFetcher
from app.integrations.smtp import SmtpProbeError, SmtpResolution, SmtpTransport, resolve_smtp
from app.models.email import EMAIL_STATUSES, EmailLog
from app.security.secrets_store import SecretCipher, SecretsStore
from app.services import bounces, mail_outgoing, mail_templates
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS: Final = 3
LOG_LIMIT: Final = 50
Enqueue = Callable[[int], Awaitable[object]]
Paused = Callable[[], Awaitable[bool]]
#: Письмо `queued` старше этого срока сборщик ставит в очередь снова (потерянная постановка).
SWEEP_AFTER: Final = timedelta(minutes=2)
#: Срок хранения текста отправленного письма (DECISIONS 2026-11-11 п. 3): дальше — только
#: адресат, тема и статус.
BODY_RETENTION: Final = timedelta(days=365)
#: Запас до конца срока ссылок на вложения: повтор, который не успеет скачать вложение, не
#: предлагается.
LINKS_MARGIN: Final = timedelta(minutes=10)
#: Назначения и шаблоны с секретом в тексте (временный пароль, ссылка или код входа,
#: приглашение): текст не хранится.
_SECRET_MAIL: Final = re.compile(
    r"invite|password|magic|login|otp|code|token|setup|reset|verif|2fa|auth|test"
)


def keeps_body(row: EmailLog) -> bool:
    """Хранить ли текст письма после отправки (просмотр и повтор): нет — у писем с секретом."""
    return not _SECRET_MAIL.search(f"{row.template} {row.purpose or ''}".lower())


def can_resend(row: EmailLog, now: datetime | None = None) -> bool:
    """«Отправить ещё раз» (MAIL-2): письмо не в очереди, текст хранится, нет секрета, а ссылки на
    вложения (письма ERP и EDS) ещё живы — иначе документ отправляют заново из его карточки."""
    if row.status == "queued" or row.body_ciphertext is None or not keeps_body(row):
        return False
    if row.links_ciphertext is None:
        return True
    border = (now or datetime.now(UTC)) + LINKS_MARGIN
    return row.links_expire_at is not None and row.links_expire_at > border


async def _never_paused() -> bool:
    return False


@dataclass(frozen=True, slots=True)
class EmailLogView:
    id: int
    to_email: str
    subject: str
    template: str
    lang: str
    status: str
    error: str | None
    attempts: int
    user_id: int | None
    requested_by: int | None
    created_at: datetime
    sent_at: datetime | None
    source: str = "crm"
    purpose: str | None = None
    attachments: int = 0
    bounce: dict[str, object] | None = None


class MailService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        store: SecretsStore,
        cipher: SecretCipher | None,
        config: Settings,
        settings: SettingsService,
        transport: SmtpTransport,
        enqueue: Enqueue,
        *,
        max_attempts: int = MAX_ATTEMPTS,
        paused: Paused = _never_paused,
        fetcher: AttachmentFetcher | None = None,
    ) -> None:
        self._sessions = sessions
        self._store = store
        self._cipher = cipher
        self._config = config
        self._settings = settings
        self._transport = transport
        self._enqueue = enqueue
        self._max_attempts = max_attempts
        self._paused = paused
        self._fetcher = fetcher

    @property
    def transport(self) -> SmtpTransport:
        return self._transport

    @property
    def cipher(self) -> SecretCipher | None:
        return self._cipher

    async def enqueue(self, email_log_ids: list[int]) -> int:
        """Поставить строки в очередь отправки (после коммита их записи); пауза — не ставить."""
        if not email_log_ids or await self._paused():
            return 0
        for email_log_id in email_log_ids:
            await self._enqueue(email_log_id)
        return len(email_log_ids)

    async def resolution(self) -> SmtpResolution:
        return await resolve_smtp(self._store, self._config, self._settings)

    async def configured(self) -> bool:
        return (await self.resolution()).connection is not None

    async def ensure_configured(self) -> None:
        """Понятная ошибка там, где письмо ожидается, — до смены пароля, а не после."""
        if not await self.configured():
            raise ConflictError(
                "smtp connector is not configured", reason=Reason.SMTP_NOT_CONFIGURED
            )
        if self._cipher is None:
            raise ConflictError("SECRETS_KEY is not set", reason=Reason.SECRETS_KEY_MISSING)

    async def send(
        self,
        template: str,
        to: str,
        context: Mapping[str, str],
        *,
        lang: str | None = None,
        user_id: int | None = None,
        requested_by: int | None = None,
    ) -> EmailLogView:
        """Рендер → строка журнала `queued` (тело шифртекстом) → задача очереди.

        Без коннектора: строка `skipped_no_smtp` и 409 `smtp_not_configured`.
        """
        try:
            rendered = mail_templates.render(template, lang, **context)
        except mail_templates.TemplateMissingError as exc:
            # Ошибка развёртывания (нет каталога шаблонов): понятный ответ API, детали — в лог.
            logger.error("mail_template_missing", template=template, lang=lang, error=str(exc))
            raise MailTemplateMissingError from exc
        return await self.send_rendered(
            template, to, rendered, user_id=user_id, requested_by=requested_by
        )

    async def send_rendered(
        self,
        template: str,
        to: str,
        rendered: mail_templates.RenderedEmail,
        *,
        user_id: int | None = None,
        requested_by: int | None = None,
        ref: tuple[str, str] | None = None,
        thread_headers: dict[str, str] | None = None,
        cc: Sequence[str] = (),
    ) -> EmailLogView:
        """Письмо с уже готовым текстом (клиентские тексты D1-9 — `domain/client_texts.py`): та же
        очередь,
        тот же журнал и те же ошибки, что у `send`; `template` — метка в журнале."""
        row = EmailLog(
            to_email=to.strip().lower(),
            subject=rendered.subject,
            template=template,
            lang=rendered.lang,
            status="queued",
            user_id=user_id,
            requested_by=requested_by,
            ref_kind=ref[0] if ref else None,
            ref_id=ref[1] if ref else None,
            # Ответ в ту же цепочку (W18A-P2): `In-Reply-To`, `References`.
            thread_headers={**(thread_headers or {}), **({"Cc": ", ".join(cc)} if cc else {})}
            or None,
        )
        connection = (await self.resolution()).connection
        if connection is None or self._cipher is None:
            row.status = "skipped_no_smtp"
            row.error = "smtp_not_configured" if connection is None else "secrets_key_missing"
            # СЦ-3: письмо без секрета хранится, чтобы уйти после подключения почты («Отправить»).
            if connection is None and self._cipher is not None and keeps_body(row):
                row.body_ciphertext = self._cipher.encrypt(rendered.body)
            view = await self._insert(row)
            logger.warning("email_skipped_no_smtp", template=template, email_log_id=view.id)
            if connection is None:
                raise ConflictError(
                    "smtp connector is not configured", reason=Reason.SMTP_NOT_CONFIGURED
                )
            raise ConflictError("SECRETS_KEY is not set", reason=Reason.SECRETS_KEY_MISSING)
        row.body_ciphertext = self._cipher.encrypt(rendered.body)
        view = await self._insert(row)
        if await self._paused():
            logger.info("email_held_paused", template=template, email_log_id=view.id)
            return view
        try:
            await self._enqueue(view.id)
        except Exception as exc:
            logger.error("email_enqueue_failed", email_log_id=view.id, exc_info=True)
            await self._finish(view.id, "failed", f"queue: {type(exc).__name__}", clear_body=True)
            raise
        logger.info("email_queued", template=template, email_log_id=view.id, user_id=user_id)
        return view

    async def deliver(self, email_log_id: int) -> bool:
        """Задача очереди: отправить письмо `queued`.

        Возвращает True, если письмо ушло; False — отправлять нечего или итог «ошибка».
        Временная ошибка бросается дальше (повтор задачи), пока остаются попытки; строка остаётся
        `queued` с причиной в `error`.
        """
        if await self._paused():
            logger.info("email_delivery_paused", email_log_id=email_log_id)
            return False
        async with self._sessions() as session:
            row = await session.get(EmailLog, email_log_id)
            if row is None or row.status != "queued":
                return False
            attempt = row.attempts + 1
            try:
                outgoing = mail_outgoing.decode(row, self._cipher)
            except mail_outgoing.UndeliverableError as exc:
                outgoing, reason = None, exc.reason
        if outgoing is None:
            await self._finish(email_log_id, "failed", reason, attempts=attempt, clear_body=True)
            return False
        last = attempt >= self._max_attempts
        connection = (await self.resolution()).connection
        if connection is None:
            await self._finish(email_log_id, "failed", "smtp_not_configured", attempts=attempt)
            return False
        try:
            files = await mail_outgoing.download(self._fetcher, outgoing.refs)
            message_id = await mail_outgoing.send(self._transport, connection, outgoing, files)
        except (SmtpProbeError, AttachmentError) as exc:
            error = mail_outgoing.error_text(exc)
            return await self._failed_attempt(
                email_log_id, attempt, error, last or exc.permanent, exc
            )
        except Exception as exc:  # noqa: BLE001 — непредвиденный сбой отправки — тоже попытка
            error = f"unexpected: {type(exc).__name__}"
            return await self._failed_attempt(email_log_id, attempt, error, last, exc)
        await self._finish(email_log_id, "sent", None, attempts=attempt, message_id=message_id)
        logger.info("email_sent", email_log_id=email_log_id)
        return True

    async def is_undeliverable(self, email: str | None) -> bool:
        """The address bounced for good: automatic mail to it is skipped until it is edited."""
        async with self._sessions() as session:
            return await bounces.is_blocked(session, email)

    async def _failed_attempt(
        self, email_log_id: int, attempt: int, error: str, final: bool, exc: Exception
    ) -> bool:
        """Неудачная попытка считается всегда (иначе строка `queued` без роста `attempts`
        крутилась бы у сборщика вечно): последняя или постоянная — `failed` с причиной, иначе
        повтор задачи."""
        logger.warning(
            "email_send_failed",
            email_log_id=email_log_id,
            error=error,
            attempt=attempt,
            final=final,
        )
        status = "failed" if final else "queued"
        await self._finish(email_log_id, status, error, attempts=attempt)
        if final:
            return False
        raise exc

    async def sweep(self, now: datetime | None = None) -> int:
        """Сборщик: письма `queued` с телом, которые давно не ушли (постановка потерялась после
        коммита), — снова в очередь. Повторная постановка безопасна: задача с блокировкой по
        строке, а отправленная строка уже не `queued`."""
        await self.purge_bodies(now)
        if await self._paused():
            return 0
        border = (now or datetime.now(UTC)) - SWEEP_AFTER
        async with self._sessions() as session:
            ids = (
                await session.scalars(
                    select(EmailLog.id)
                    .where(
                        EmailLog.status == "queued",
                        EmailLog.body_ciphertext.is_not(None),
                        EmailLog.updated_at < border,
                    )
                    .order_by(EmailLog.id)
                    .limit(200)
                )
            ).all()
        for email_log_id in ids:
            await self._enqueue(email_log_id)
        if ids:
            logger.info("email_queue_swept", count=len(ids))
        return len(ids)

    async def purge_bodies(self, now: datetime | None = None) -> int:
        """Текст писем старше срока хранения стирается; адресат, тема, статус и ссылка на документ
        остаются."""
        border = (now or datetime.now(UTC)) - BODY_RETENTION
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(EmailLog)
                .where(
                    EmailLog.status.in_(("sent", "failed", "skipped_no_smtp")),
                    EmailLog.created_at < border,
                    EmailLog.body_ciphertext.is_not(None),
                )
                .values(body_ciphertext=None, html_ciphertext=None, links_ciphertext=None)
            )
        purged = int(getattr(result, "rowcount", 0) or 0)
        if purged:
            logger.info("email_bodies_purged", count=purged)
        return purged

    async def resend(self, email_log_id: int, requested_by: int | None) -> EmailLogView:
        """«Отправить ещё раз» (MAIL-2): новая строка журнала с тем же адресатом, темой, текстом и
        вложениями — в очередь. Исходная строка не меняется; итог повтора в шину не уходит (у копии
        нет ключа запроса)."""
        async with self._sessions() as session:
            row = await session.get(EmailLog, email_log_id)
            if row is None or not can_resend(row):
                raise ConflictError("mail cannot be resent", reason=Reason.MAIL_NOT_RESENDABLE)
            copy = EmailLog(
                to_email=row.to_email,
                subject=row.subject,
                template=row.template,
                lang=row.lang,
                status="queued",
                user_id=row.user_id,
                requested_by=requested_by,
                body_ciphertext=row.body_ciphertext,
                html_ciphertext=row.html_ciphertext,
                links_ciphertext=row.links_ciphertext,
                links_expire_at=row.links_expire_at,
                attachments=row.attachments,
                source=row.source,
                purpose=row.purpose,
                ref_kind=row.ref_kind,
                ref_id=row.ref_id,
                reply_to=row.reply_to,
                thread_headers=row.thread_headers,
            )
        await self.ensure_configured()
        view = await self._insert(copy)
        if not await self._paused():
            await self._enqueue(view.id)
        logger.info("email_resent", email_log_id=view.id, original_id=email_log_id)
        return view

    async def _missed(self, session: AsyncSession) -> list[EmailLog]:
        """Письма, не ушедшие, пока почта не была настроена, и которые можно отправить сейчас
        (СЦ-3): текст хранится, секрета нет, ссылки живы. Письма EDS отправляются из документа."""
        now = datetime.now(UTC)
        rows = (
            await session.scalars(
                select(EmailLog)
                .where(
                    EmailLog.status == "skipped_no_smtp",
                    EmailLog.error == "smtp_not_configured",
                    EmailLog.source.is_distinct_from("eds"),
                    EmailLog.body_ciphertext.is_not(None),
                )
                .order_by(EmailLog.id)
            )
        ).all()
        return [row for row in rows if can_resend(row, now)]

    async def missed_count(self) -> int:
        async with self._sessions() as session:
            return len(await self._missed(session))

    async def send_missed(self, requested_by: int | None) -> int:
        """«Отправить» пропущенные письма: та же строка журнала снова в очереди — итог уйдёт в шину
        с исходным ключом запроса. На паузе почты строки ждут `resume_queued`, как у `resend`."""
        await self.ensure_configured()
        async with self._sessions() as session, session.begin():
            rows = await self._missed(session)
            for row in rows:
                row.status, row.error, row.attempts = "queued", None, 0
                row.requested_by = requested_by
            ids = [row.id for row in rows]
        if ids and not await self._paused():
            for email_log_id in ids:
                await self._enqueue(email_log_id)
        logger.info("email_missed_requeued", count=len(ids))
        return len(ids)

    async def resume_queued(self) -> int:
        """После паузы: письма `queued` с телом — снова в очередь. Возвращает их число."""
        async with self._sessions() as session:
            ids = (
                await session.scalars(
                    select(EmailLog.id)
                    .where(EmailLog.status == "queued", EmailLog.body_ciphertext.is_not(None))
                    .order_by(EmailLog.id)
                )
            ).all()
        for email_log_id in ids:
            await self._enqueue(email_log_id)
        logger.info("email_queue_resumed", count=len(ids))
        return len(ids)

    async def list_log(
        self, status: str | None = None, limit: int = LOG_LIMIT
    ) -> list[EmailLogView]:
        stmt = (
            select(EmailLog).order_by(EmailLog.created_at.desc(), EmailLog.id.desc()).limit(limit)
        )
        if status in EMAIL_STATUSES:
            stmt = stmt.where(EmailLog.status == status)
        async with self._sessions() as session:
            rows = (await session.scalars(stmt)).all()
        return [_view(row) for row in rows]

    async def _insert(self, row: EmailLog) -> EmailLogView:
        async with self._sessions() as session, session.begin():
            session.add(row)
            await session.flush()
            await session.refresh(row)  # server_default: created_at, attempts
            return _view(row)

    async def _finish(
        self,
        email_log_id: int,
        status: str,
        error: str | None,
        *,
        attempts: int | None = None,
        clear_body: bool = False,
        message_id: str | None = None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(EmailLog, email_log_id)
            if row is None:
                return
            row.status, row.error = status, error
            if attempts is not None:
                row.attempts = attempts
            if message_id:
                row.message_id = message_id[:255]
            if status == "sent":
                row.sent_at = datetime.now(UTC)
            if clear_body or (status in ("sent", "failed") and not keeps_body(row)):
                row.body_ciphertext = None
                row.html_ciphertext = None
                row.links_ciphertext = None
            if status in ("sent", "failed"):
                await bus_events.mail_result(session, row)


def _view(row: EmailLog) -> EmailLogView:
    return EmailLogView(
        id=row.id,
        to_email=row.to_email,
        subject=row.subject,
        template=row.template,
        lang=row.lang,
        status=row.status,
        error=row.error,
        attempts=row.attempts,
        user_id=row.user_id,
        requested_by=row.requested_by,
        created_at=row.created_at,
        sent_at=row.sent_at,
        source=row.source or "crm",
        purpose=row.purpose,
        attachments=len(row.attachments or []),
        bounce={"reason": row.bounce_reason, "status": row.bounce_status, "at": row.bounced_at}
        if row.bounced_at is not None and row.bounce_reason
        else None,
    )
