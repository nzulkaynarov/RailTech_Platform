"""Отправка писем сотрудникам через коннектор «Почта» (M3-CRM-08, ARCHITECTURE §18).

`send()` — в пути запроса только рендер и запись в журнал `email_log`; само письмо уходит задачей
Procrastinate (`tasks/mail.py` → `deliver()`), чтобы медленный релей не держал запрос. Без
коннектора письмо не ставится: в журнале `skipped_no_smtp`, вызывающему — 409 `smtp_not_configured`
(«Настройте коннектор «Почта»»). Тело письма содержит временный пароль, поэтому до отправки лежит
в журнале только шифртекстом (`SECRETS_KEY`) и стирается после отправки или последней попытки.
Рассылки клиентам этим сервисом не делаются (ARCHITECTURE §18).

Выключатель «Почта» в центре внешних сервисов (ADR-0024) — пауза очереди: письмо остаётся в
журнале `queued` (тело шифртекстом) и не ставится в очередь, воркер `queued` не отправляет;
`resume_queued()` при включении ставит ожидающие письма в очередь заново.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import ConflictError, MailTemplateMissingError, Reason
from app.integrations.smtp import SmtpProbeError, SmtpResolution, SmtpTransport, resolve_smtp
from app.models.email import EMAIL_STATUSES, EmailLog
from app.security.secrets_store import SecretCipher, SecretsKeyError, SecretsStore
from app.services import mail_templates
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS: Final = 3
LOG_LIMIT: Final = 50
Enqueue = Callable[[int], Awaitable[object]]
Paused = Callable[[], Awaitable[bool]]


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

    @property
    def transport(self) -> SmtpTransport:
        return self._transport

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
        row = EmailLog(
            to_email=to.strip().lower(),
            subject=rendered.subject,
            template=template,
            lang=rendered.lang,
            status="queued",
            user_id=user_id,
            requested_by=requested_by,
        )
        connection = (await self.resolution()).connection
        if connection is None or self._cipher is None:
            row.status = "skipped_no_smtp"
            row.error = "smtp_not_configured" if connection is None else "secrets_key_missing"
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
        """Задача очереди: отправить письмо `queued`. Сбой — `failed` с причиной, повтор по ретраям.

        Возвращает True, если письмо ушло; False — нечего отправлять (не `queued`).
        Исключение `SmtpProbeError` пробрасывается, пока остаются попытки.
        """
        if await self._paused():
            logger.info("email_delivery_paused", email_log_id=email_log_id)
            return False
        async with self._sessions() as session:
            row = await session.get(EmailLog, email_log_id)
            if row is None or row.status != "queued":
                return False
            to, subject, ciphertext, attempts = (
                row.to_email,
                row.subject,
                row.body_ciphertext,
                row.attempts,
            )
        attempt = attempts + 1
        last = attempt >= self._max_attempts
        if ciphertext is None:
            await self._finish(email_log_id, "failed", "body_expired", attempts=attempt)
            return False
        connection = (await self.resolution()).connection
        if connection is None or self._cipher is None:
            await self._finish(email_log_id, "failed", "smtp_not_configured", attempts=attempt)
            return False
        try:
            body = self._cipher.decrypt(ciphertext)
        except SecretsKeyError:
            await self._finish(email_log_id, "failed", "secrets_key_changed", attempts=attempt)
            return False
        try:
            await self._transport.send(connection, to, subject, body)
        except SmtpProbeError as exc:
            logger.warning(
                "email_send_failed", email_log_id=email_log_id, kind=exc.kind, attempt=attempt
            )
            error = f"{exc.kind}: {exc.detail}" if exc.detail else exc.kind
            await self._finish(email_log_id, "failed", error, attempts=attempt, clear_body=last)
            if last:
                return False
            raise
        await self._finish(email_log_id, "sent", None, attempts=attempt, clear_body=True)
        logger.info("email_sent", email_log_id=email_log_id)
        return True

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
    ) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(EmailLog, email_log_id)
            if row is None:
                return
            row.status, row.error = status, error
            if attempts is not None:
                row.attempts = attempts
            if status == "sent":
                row.sent_at = datetime.now(UTC)
            if clear_body or status == "sent":
                row.body_ciphertext = None


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
    )
