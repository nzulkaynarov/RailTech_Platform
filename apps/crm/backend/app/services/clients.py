"""Клиенты (SPEC §5.2, §7.3): карточка, привязка Telegram с подтверждением, «Сделать клиентом».

Привязка идентичности к клиенту — только действием менеджера (verified_by/at).
Без неё бот работает в режиме prospect и документов клиента не видит.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import (
    ConflictError,
    ForbiddenError,
    InvalidTransitionError,
    NotFoundError,
    Reason,
    ValidationFailedError,
)
from app.domain.lead_access import may_make_customer
from app.domain.stages import OwnerMode, Stage, TransitionSource
from app.models.auth import User
from app.models.clients import Client, ServiceRequest
from app.models.leads import Lead, TelegramIdentity
from app.models.qualification import Escalation
from app.repositories import events
from app.security import audit
from app.security.principal import Principal
from app.services import stages
from app.services.escalation import OPEN_STATUSES
from app.services.lead_messenger import LeadMessenger
from app.services.leads import LANGUAGES
from app.services.settings import SettingsService

CLEARABLE = frozenset({"inn", "segment", "notes", "owner_user_id"})
EDITABLE = CLEARABLE | {"name", "is_active"}


class ClientService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService | None = None,
        messenger: LeadMessenger | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._messenger = messenger

    async def create(self, who: Principal, name: str, inn: str | None, segment: str | None) -> int:
        async with self._sessions() as session, session.begin():
            client = Client(name=name.strip(), inn=inn, segment=segment, owner_user_id=who.user_id)
            session.add(client)
            await session.flush()
            await audit.record(
                session, who.actor, "client.create", "client", client.id, after={"name": name}
            )
            return client.id

    async def update(self, who: Principal, client_id: int, changes: dict[str, Any]) -> None:
        """Изменить поля клиента; `None` очищает необязательное поле (ИНН, сегмент, владелец)."""
        unknown = set(changes) - EDITABLE
        if unknown:
            raise ValidationFailedError("unknown client fields", field=sorted(unknown)[0])
        async with self._sessions() as session, session.begin():
            client = await _client(session, client_id)
            owner = changes.get("owner_user_id")
            if owner is not None:
                user = await session.get(User, owner)
                if user is None or not user.is_active:
                    raise ValidationFailedError(
                        "choose an active user",
                        reason=Reason.INACTIVE_COLLEAGUE,
                        field="owner_user_id",
                    )
            before, after = {}, {}
            for field, value in changes.items():
                if value is None and field not in CLEARABLE:
                    continue
                if getattr(client, field) != value:
                    before[field], after[field] = getattr(client, field), value
                    setattr(client, field, value)
            if after:
                await audit.record(
                    session,
                    who.actor,
                    "client.update",
                    "client",
                    client_id,
                    before=before,
                    after=after,
                )

    async def link_identity(self, who: Principal, client_id: int, tg_user_id: int) -> None:
        """Подтверждение менеджером: этот Telegram-аккаунт принадлежит клиенту."""
        async with self._sessions() as session, session.begin():
            await _client(session, client_id)
            identity = await _identity(session, tg_user_id)
            if identity.client_id not in (None, client_id):
                raise ConflictError(
                    "telegram account is linked to another client",
                    reason=Reason.TELEGRAM_LINKED_ELSEWHERE,
                )
            identity.client_id = client_id
            identity.verified_by_user_id = who.user_id
            identity.verified_at = datetime.now(UTC)
            if identity.lead_id is not None:
                lead = await session.get(Lead, identity.lead_id, with_for_update=True)
                if lead is not None and lead.client_id is None:
                    lead.client_id = client_id
            await audit.record(
                session,
                who.actor,
                "client.link_telegram",
                "client",
                client_id,
                after={"tg_user_id": tg_user_id},
            )

    async def unlink_identity(self, who: Principal, client_id: int, tg_user_id: int) -> None:
        async with self._sessions() as session, session.begin():
            identity = await _identity(session, tg_user_id)
            if identity.client_id != client_id:
                raise NotFoundError("identity is not linked to this client")
            identity.client_id, identity.verified_at, identity.verified_by_user_id = (
                None,
                None,
                None,
            )
            await audit.record(
                session,
                who.actor,
                "client.unlink_telegram",
                "client",
                client_id,
                after={"tg_user_id": tg_user_id},
            )

    async def make_customer(
        self, who: Principal, lead_id: int, client_id: int | None, new_name: str | None
    ) -> int:
        """Лид после сделки → клиент: привязка лида и его Telegram, стадия won → customer."""
        if client_id is None and not (new_name and new_name.strip()):
            raise ValidationFailedError(
                "choose a client or enter a new client name", field="client_id"
            )
        async with self._sessions() as session, session.begin():
            lead = await session.get(Lead, lead_id, with_for_update=True)
            if lead is None or lead.erased_at is not None:
                raise NotFoundError("lead not found")
            if lead.stage not in (Stage.WON, Stage.CUSTOMER):
                raise InvalidTransitionError(
                    "close the deal (won) first", reason=Reason.DEAL_NOT_CLOSED
                )
            if not may_make_customer(
                stage=lead.stage,
                assigned_user_id=lead.assigned_user_id,
                user_id=who.user_id,
                is_admin=who.is_admin,
            ):
                raise ForbiddenError(
                    "only the lead owner or an admin can do this", reason=Reason.NOT_LEAD_OWNER
                )
            if client_id is None:
                client = Client(name=(new_name or "").strip(), owner_user_id=who.user_id)
                session.add(client)
                await session.flush()
                client_id = client.id
            else:
                await _client(session, client_id)
            lead.client_id = client_id
            await _bind_identities(session, lead_id, client_id, who)
            # Сервисный режим ведёт бот (BUSINESS §5): документы и вопросы клиента — без менеджера.
            lead.owner_mode = OwnerMode.BOT.value
            lead.snoozed_until = None
            await stages.transition(
                session,
                lead,
                Stage.CUSTOMER,
                TransitionSource.USER,
                reason="linked to client",
                actor_user_id=who.user_id,
            )
            await audit.record(
                session,
                who.actor,
                "lead.make_customer",
                "lead",
                lead_id,
                after={"client_id": client_id},
            )
            await events.publish(session, "lead.updated", lead_id=lead_id)
            return client_id

    async def close_service_request(self, who: Principal, request_id: int, resolution: str) -> None:
        """Закрыть запрос клиента с итогом: клиент получает ответ в боте (ADR-0015)."""
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            row = await session.get(ServiceRequest, request_id, with_for_update=True)
            if row is None:
                raise NotFoundError("service request not found")
            if row.status != "open":
                raise ConflictError(
                    "service request is already closed", reason=Reason.SERVICE_REQUEST_CLOSED
                )
            row.status, row.closed_by = "closed", who.user_id
            row.resolution, row.closed_at = resolution.strip(), now
            lead = await session.get(Lead, row.lead_id) if row.lead_id else None
            if lead is not None:
                await _resolve_info_escalation(session, lead.id, now)
            await audit.record(
                session,
                who.actor,
                "client.close_request",
                "service_request",
                request_id,
                after={"resolution": row.resolution},
            )
            summary, language = row.summary, lead.language if lead else "ru"
        if lead is not None and self._settings is not None and self._messenger is not None:
            cfg = await self._settings.get()
            text = cfg.texts.service_request_closed.get(
                LANGUAGES.get(language, "ru"), summary=summary[:200], resolution=resolution.strip()
            )
            await self._messenger.send(lead.id, text, {"notice": "service_request_closed"})


async def _resolve_info_escalation(session: AsyncSession, lead_id: int, now: datetime) -> None:
    """Информационная эскалация о запросе закрывается вместе с ним; срочные — нет."""
    escalation = (
        await session.scalars(
            select(Escalation).where(
                Escalation.lead_id == lead_id,
                Escalation.status.in_(OPEN_STATUSES),
                Escalation.priority == "info",
            )
        )
    ).first()
    if escalation is not None:
        escalation.status, escalation.resolved_at = "closed", now
        escalation.outcome = "service_request_closed"
        await events.publish(
            session, "escalation.updated", lead_id=lead_id, escalation_id=escalation.id
        )


async def _bind_identities(
    session: AsyncSession, lead_id: int, client_id: int, who: Principal
) -> None:
    """Telegram лида → клиент с подтверждением; чужая привязка не перезаписывается молча."""
    identities = (
        await session.scalars(
            select(TelegramIdentity).where(TelegramIdentity.lead_id == lead_id).with_for_update()
        )
    ).all()
    for identity in identities:
        if identity.client_id is not None and identity.client_id != client_id:
            raise ConflictError(
                "telegram account is linked to another client",
                reason=Reason.TELEGRAM_LINKED_ELSEWHERE,
                client_id=identity.client_id,
            )
    for identity in identities:
        identity.client_id = client_id
        identity.verified_by_user_id, identity.verified_at = who.user_id, datetime.now(UTC)


async def _client(session: AsyncSession, client_id: int) -> Client:
    client = await session.get(Client, client_id)
    if client is None:
        raise NotFoundError("client not found")
    return client


async def _identity(session: AsyncSession, tg_user_id: int) -> TelegramIdentity:
    identity = (
        await session.scalars(
            select(TelegramIdentity)
            .where(TelegramIdentity.tg_user_id == tg_user_id)
            .with_for_update()
        )
    ).first()
    if identity is None:
        raise NotFoundError(
            "telegram account has never written to the bot", reason=Reason.TELEGRAM_UNKNOWN
        )
    return identity
