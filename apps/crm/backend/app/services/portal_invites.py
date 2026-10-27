"""Приглашение клиента в кабинет: итог для менеджера и «Отправить повторно другим каналом» (D1-9,
Q-FIX23-1).

Первое приглашение уходит из ERP при передаче клиента (`erp_handoff`): письмом, и/или Telegram —
событием боту CRM
(`erp_invite_delivery`). Раньше ошибка оставалась в логе, а менеджер не знал, что клиент так и не
получил приглашения.
Теперь каждая попытка — строка `client_notices` (`kind=portal_invite`) со статусом, каналом и
причиной словами, а карточка
клиента и лида отдаёт последнюю попытку, доступные каналы контакта и действие «повторить другим
каналом».

Состояния: письмо ERP отправляет сама — `sent` сразу; Telegram — `queued` с
`detail.telegram=pending`, пока бот не
доставит (`resolve_telegram`): `sent`, либо `failed` с причиной (бот заблокирован, контакт ни разу
не писал боту).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    Reason,
    UpstreamUnavailableError,
)
from app.domain.notice_errors import error_text
from app.integrations.erp import ErpClient, HandoffResult
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity
from app.models.notices import ClientNotice
from app.schemas.notices import InvitationOut
from app.security import audit
from app.security.principal import Principal
from app.services.erp_acceptance_code import contact_telegram

logger = structlog.get_logger(__name__)

KIND: Final = "portal_invite"
#: Как долго итог бота, обогнавший ответ ERP, ждёт свою попытку (и как долго «ждёт бота» попытка).
ORPHAN_WINDOW: Final = timedelta(minutes=10)
Channel = Literal["email", "telegram"]


@dataclass(frozen=True, slots=True)
class Reach:
    """Что у контакта есть для приглашения сейчас."""

    email: bool
    telegram: bool

    def channels(self) -> list[Channel]:
        return [c for c, ok in (("email", self.email), ("telegram", self.telegram)) if ok]  # type: ignore[misc]


def suggest(tried: list[str], reach: Reach) -> Literal["email", "telegram", "both"] | None:
    """Канал для «Отправить повторно другим каналом»: не тот, что уже пробовали, если есть."""
    available = reach.channels()
    others = [c for c in available if c not in tried]
    if others:
        return others[0]
    if len(available) == 2:
        return "both"
    return available[0] if available else None


async def primary_contact(session: AsyncSession, client_id: int) -> ClientContact | None:
    return await session.scalar(
        select(ClientContact)
        .where(ClientContact.client_id == client_id)
        .order_by(ClientContact.is_primary.desc(), ClientContact.id)
        .limit(1)
    )


async def telegram_of_contact(
    session: AsyncSession, client: Client, contact: ClientContact
) -> int | None:
    """Telegram, куда можно написать контакту: его привязка или проверенная привязка клиента (как у
    кода акцепта), а у
    основного контакта ещё и аккаунт лида клиента — так передача берёт `telegram_user_id`
    (`erp_handoff._telegram_of`).
    Приглашение — кнопка входа, ничего секретного в нём нет, поэтому непроверенный аккаунт лида
    подходит."""
    found = await contact_telegram(session, client, contact)
    if found is not None or not contact.is_primary or contact.telegram_identity_id is not None:
        return found
    return await session.scalar(
        select(TelegramIdentity.tg_user_id)
        .join(Lead, Lead.id == TelegramIdentity.lead_id)
        .where(Lead.client_id == client.id, TelegramIdentity.is_blocked.is_(False))
        .order_by(TelegramIdentity.id)
        .limit(1)
    )


async def reach_of(session: AsyncSession, client: Client, contact: ClientContact | None) -> Reach:
    """Email — если он есть; Telegram — если бот знает, куда писать контакту."""
    if contact is None:
        return Reach(False, False)
    return Reach(
        email=bool((contact.email or "").strip()),
        telegram=await telegram_of_contact(session, client, contact) is not None,
    )


def requested_channel(contact: ClientContact | None, reach: Reach) -> str:
    """Что просим у ERP: выбор менеджера на контакте, иначе всё, что у контакта есть (приоритет —
    Telegram и почта)."""
    preferred = contact.preferred_channel if contact is not None else None
    if preferred in ("email", "telegram", "both"):
        return preferred
    if reach.email and reach.telegram:
        return "both"
    return "email" if reach.email else "telegram"


def invite_channels(contact: ClientContact | None, reach: Reach) -> list[str]:
    """Список для `HandoffInvitePayload.channels`: предпочитаемый канал или всё доступное."""
    wanted = requested_channel(contact, reach)
    return ["telegram", "email"] if wanted == "both" else [wanted]


async def record_handoff(session: AsyncSession, client: Client, result: HandoffResult) -> None:
    """Итог приглашения из ответа передачи клиента в ERP — в транзакции передачи
    (`erp_handoff._complete`)."""
    contact = await primary_contact(session, client.id)
    reach = await reach_of(session, client, contact)
    sent = [c for c in result.invite_sent_via if c in ("email", "telegram")]
    requested = requested_channel(contact, reach)
    error = None if sent else _error_code(result.invite_error, reach)
    notice = _notice(client.id, contact, sent, requested, error, None)
    await _adopt_orphan(session, notice)
    session.add(notice)


def _error_code(erp_error: str | None, reach: Reach) -> str:
    """Код причины; контакт только с телефоном (нет ни почты, ни Telegram) важнее кода ERP."""
    if not reach.email and not reach.telegram:
        return "CONTACT_CHANNEL_REQUIRED"
    return erp_error or "CONTACT_CHANNEL_REQUIRED"


def _notice(
    client_id: int,
    contact: ClientContact | None,
    sent: list[str],
    requested: str,
    error: str | None,
    user_id: int | None,
) -> ClientNotice:
    telegram_pending = "telegram" in sent
    only_pending = telegram_pending and "email" not in sent
    if error is not None:
        status = "failed"
    elif only_pending:
        status = "queued"
    else:
        status = "sent"
    detail: dict[str, Any] = {"sent_via": sent}
    if telegram_pending:
        detail["telegram"] = "pending"
    channel = ("both" if len(sent) == 2 else sent[0]) if sent else requested
    return ClientNotice(
        kind=KIND,
        client_id=client_id,
        contact_id=contact.id if contact is not None else None,
        channel=channel,
        status=status,
        error=error,
        detail=detail,
        sent_at=datetime.now(UTC) if status == "sent" else None,
        requested_by_user_id=user_id,
    )


class PortalInviteService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], erp_client: ErpClient) -> None:
        self._sessions = sessions
        self._erp = erp_client

    async def current(self, session: AsyncSession, client_id: int) -> InvitationOut | None:
        """Последняя попытка приглашения и каналы контакта; `None` — клиента нет или приглашений не
        было."""
        client = await session.get(Client, client_id)
        if client is None:
            return None
        notice = await session.scalar(
            select(ClientNotice)
            .where(ClientNotice.client_id == client_id, ClientNotice.kind == KIND)
            .order_by(ClientNotice.id.desc())
            .limit(1)
        )
        contact = (
            await session.get(ClientContact, notice.contact_id)
            if notice is not None and notice.contact_id is not None
            else await primary_contact(session, client_id)
        )
        reach = await reach_of(session, client, contact)
        if notice is None:
            if client.erp_company_id is None:
                return None
            return _out_without_notice(client, contact, reach)
        return _out(notice, client, contact, reach)

    async def resend(
        self, who: Principal, client_id: int, channel: str, contact_id: int | None
    ) -> InvitationOut:
        """Повторное приглашение каналом; ошибка доставки — в ответе (`status=failed`), не 5xx."""
        async with self._sessions() as session:
            client = await session.get(Client, client_id)
            if client is None:
                raise NotFoundError("client not found")
            if client.erp_company_id is None:
                raise ConflictError("client is not in erp", reason=Reason.CLIENT_NOT_IN_ERP)
            contact = await self._contact(session, client, contact_id)
            reach = await reach_of(session, client, contact)
        sent: list[str] = []
        error: str | None = None
        if not reach.email and not reach.telegram:
            error = "CONTACT_CHANNEL_REQUIRED"
        else:
            sent, error = await self._ask_erp(client_id, channel, contact)
        async with self._sessions() as session, session.begin():
            await _lock_client(session, client_id)
            notice = _notice(client_id, contact, sent, channel, error, who.user_id)
            await _adopt_orphan(session, notice)
            session.add(notice)
            await session.flush()
            await session.refresh(notice)  # created_at — серверное значение
            await audit.record(
                session,
                who.actor,
                "client.invite_resend",
                "client",
                client_id,
                after={"channel": channel, "sent_via": sent, "error": error},
            )
            return _out(notice, client, contact, reach)

    async def _ask_erp(
        self, client_id: int, channel: str, contact: ClientContact | None
    ) -> tuple[list[str], str | None]:
        try:
            result = await self._erp.invite_client(
                client_id, channel, contact.id if contact is not None else None
            )
        except ConflictError as exc:
            if exc.details.get("reason") == Reason.CLIENT_NOT_IN_ERP:
                return [], "not_in_erp"
            if exc.details.get("reason") == Reason.ERP_NOT_CONFIGURED:
                return [], "erp_not_configured"
            raise
        except UpstreamUnavailableError:
            return [], "erp_unavailable"
        except DomainError as exc:
            logger.warning("invite_resend_erp_rejected", client_id=client_id, error=exc.message)
            return [], "erp_unavailable"
        sent = [c for c in result.sent_via if c in ("email", "telegram")]
        return sent, None if sent else (result.error or "CONTACT_CHANNEL_REQUIRED")

    @staticmethod
    async def _contact(
        session: AsyncSession, client: Client, contact_id: int | None
    ) -> ClientContact | None:
        if contact_id is None:
            return await primary_contact(session, client.id)
        contact = await session.get(ClientContact, contact_id)
        if contact is None or contact.client_id != client.id:
            raise NotFoundError("contact not found")
        return contact

    async def resolve_telegram(
        self, client_id: int, contact_id: int | None, error: str | None
    ) -> None:
        """Итог доставки приглашения ботом: `error=None` — сообщение ушло.

        Событие ERP может прийти раньше HTTP-ответа ERP, и строки попытки ещё нет: итог пишется
        строкой-сиротой (`detail.orphan`), а `record_handoff` / `resend` подставляют его в свою
        строку и удаляют сироту (`_adopt_orphan`). Сирота без своей попытки (приглашение из самой
        ERP) остаётся обычной записью истории.
        """
        cutoff = datetime.now(UTC) - ORPHAN_WINDOW
        async with self._sessions() as session, session.begin():
            await _lock_client(session, client_id)
            notice = await session.scalar(
                select(ClientNotice)
                .where(
                    ClientNotice.client_id == client_id,
                    ClientNotice.kind == KIND,
                    ClientNotice.detail["telegram"].astext == "pending",
                    ClientNotice.created_at >= cutoff,
                )
                .order_by(ClientNotice.id.desc())
                .limit(1)
                .with_for_update()
            )
            if notice is None:
                contact = await session.get(ClientContact, contact_id) if contact_id else None
                notice = _notice(client_id, contact, ["telegram"], "telegram", None, None)
                notice.detail = {**notice.detail, "orphan": True}
                session.add(notice)
            _apply_telegram_result(notice, error)


async def _lock_client(session: AsyncSession, client_id: int) -> None:
    """Блокировка клиента — та же, что у `ErpHandoffService._complete`: запись попытки и итог бота
    идут по очереди (порядок везде «клиент → строки»), иначе при READ COMMITTED сирота и ожидающая
    попытка не увидят друг друга."""
    await session.get(Client, client_id, with_for_update=True)


def _apply_telegram_result(notice: ClientNotice, error: str | None) -> None:
    """Итог доставки ботом в строку попытки: ушло — `sent`; не ушло — `failed`, если письмо тоже не
    ушло."""
    email_went = "email" in (notice.detail.get("sent_via") or [])
    notice.detail = {**notice.detail, "telegram": "failed" if error else "sent"}
    if error is None:
        notice.status, notice.error, notice.sent_at = "sent", None, datetime.now(UTC)
    elif email_went:
        notice.status, notice.sent_at = "sent", notice.sent_at or datetime.now(UTC)
        notice.detail = {**notice.detail, "telegram_error": error}
    else:
        notice.status, notice.error = "failed", error


async def _adopt_orphan(session: AsyncSession, notice: ClientNotice) -> None:
    """Итог бота уже записан сиротой (событие обогнало ответ ERP): подставить в новую попытку."""
    if notice.detail.get("telegram") != "pending":
        return
    conditions = [
        ClientNotice.client_id == notice.client_id,
        ClientNotice.kind == KIND,
        ClientNotice.detail["orphan"].astext == "true",
        ClientNotice.created_at >= datetime.now(UTC) - ORPHAN_WINDOW,
    ]
    if notice.contact_id is not None:
        conditions.append(ClientNotice.contact_id == notice.contact_id)
    orphan = await session.scalar(
        select(ClientNotice)
        .where(*conditions)
        .order_by(ClientNotice.id.desc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if orphan is None:
        return
    failed = orphan.detail.get("telegram") == "failed"
    _apply_telegram_result(notice, orphan.error if failed else None)
    await session.delete(orphan)


_EMAIL_ERRORS: Final = frozenset(
    {"CONTACT_EMAIL_REQUIRED", "EMAIL_DELIVERY_FAILED", "email_failed", "smtp_not_configured"}
)
_TELEGRAM_ERRORS: Final = frozenset(
    {
        "CONTACT_TELEGRAM_REQUIRED",
        "telegram_blocked",
        "telegram_failed",
        "no_telegram",
        "cabinet_not_configured",
        "bot_not_configured",
    }
)


def _failed_channels(error: str | None, channel: str) -> list[str]:
    """Какой канал подвёл по коду причины; неясно — все, что просили."""
    if error in _EMAIL_ERRORS:
        return ["email"]
    if error in _TELEGRAM_ERRORS:
        return ["telegram"]
    return ["email", "telegram"] if channel in ("both", "none") else [channel]


def _out(
    notice: ClientNotice, client: Client, contact: ClientContact | None, reach: Reach
) -> InvitationOut:
    sent = [c for c in (notice.detail.get("sent_via") or []) if c in ("email", "telegram")]
    tried = _failed_channels(notice.error, notice.channel) if notice.error else sent
    return InvitationOut(
        id=notice.id,
        channel=notice.channel,
        status=notice.status,
        error=notice.error,
        error_text=error_text(notice.error),
        created_at=notice.created_at,
        sent_at=notice.sent_at,
        contact_id=contact.id if contact is not None else notice.contact_id,
        contact_name=contact.full_name if contact is not None else None,
        sent_via=sent,
        available_channels=reach.channels(),
        suggested_channel=suggest(tried, reach),
        can_resend=client.erp_company_id is not None,
    )


def _out_without_notice(
    client: Client, contact: ClientContact | None, reach: Reach
) -> InvitationOut:
    """Клиент в ERP, а приглашений не было (передан до D1-9): показываем, куда можно пригласить."""
    now = datetime.now(UTC)
    return InvitationOut(
        id=0,
        channel="none",
        status="skipped",
        error=None,
        error_text=None,
        created_at=now,
        contact_id=contact.id if contact is not None else None,
        contact_name=contact.full_name if contact is not None else None,
        available_channels=reach.channels(),
        suggested_channel=suggest([], reach),
        can_resend=client.erp_company_id is not None,
    )
