"""Клиенты (SPEC §5.2, §7.3): карточка, привязка Telegram с подтверждением, «Сделать клиентом».

Привязка идентичности к клиенту — только действием менеджера (verified_by/at).
Без неё бот работает в режиме prospect и документов клиента не видит.

«Сделать клиентом» = «Передать в бэк-офис» (ADR-0022): режим решает `domain/backoffice.py`
по факту «коннектор ERP настроен»; без коннектора поведение прежнее. Вызов ERP — M3-CRM-03.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.domain.backoffice import (
    BackofficeMode,
    HandoffConsent,
    decide_handoff,
    handoff_consent,
)
from app.domain.erp_handoff import ENQUEUE_FAILED, FAILED, PENDING
from app.domain.errors import (
    ConflictError,
    ForbiddenError,
    InvalidTransitionError,
    NotFoundError,
    Reason,
    ValidationFailedError,
)
from app.domain.lead_access import may_make_customer
from app.domain.stage_machine import stage_after_unlink
from app.domain.stages import OwnerMode, Stage, TransitionSource
from app.domain.triggers import TriggerCode
from app.models.auth import User
from app.models.clients import Client, ServiceRequest
from app.models.leads import Lead, TelegramIdentity
from app.models.qualification import Escalation
from app.repositories import events
from app.repositories import leads as leads_repo
from app.security import audit
from app.security.principal import Principal
from app.services import lead_parts, stages
from app.services.escalation import OPEN_STATUSES
from app.services.lead_messenger import LeadMessenger
from app.services.leads import LANGUAGES, ChatsChanged, notify_chats
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

CLEARABLE = frozenset({"inn", "segment", "notes", "owner_user_id"})
EDITABLE = CLEARABLE | {"name", "is_active"}

BackofficeModeProvider = Callable[[], Awaitable[BackofficeMode]]
# Поставить передачу в очередь (`tasks.erp_handoff`): (client_id, lead_id, user_id).
HandoffEnqueue = Callable[[int, int, int], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class _CustomerResult:
    """Итог транзакции «Сделать клиентом»: что сделать уже после коммита."""

    client_id: int
    enqueue: bool = False
    notify: bool = False
    chats: list[int] = field(default_factory=list)
    access_notice: bool = False
    language: str = "ru"


async def local_backoffice() -> BackofficeMode:
    """Без коннектора ERP (до M3-CRM-02/03) — прежнее поведение."""
    return BackofficeMode.LOCAL


class ClientService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService | None = None,
        messenger: LeadMessenger | None = None,
        on_chats_changed: ChatsChanged | None = None,
        backoffice_mode: BackofficeModeProvider = local_backoffice,
        erp_handoff_enqueue: HandoffEnqueue | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._messenger = messenger
        # Привязка/отвязка/«Сделать клиентом» меняют меню бота (вариант client) — сразу.
        self._on_chats_changed = on_chats_changed
        # Режим передачи в бэк-офис (ADR-0022): `integrations/erp.erp_connector_configured`.
        self._backoffice_mode = backoffice_mode
        self._erp_handoff_enqueue = erp_handoff_enqueue

    async def create(self, who: Principal, name: str, inn: str | None, segment: str | None) -> int:
        async with self._sessions() as session, session.begin():
            client = Client(name=name.strip(), inn=inn, segment=segment, owner_user_id=who.user_id)
            session.add(client)
            await session.flush()
            await audit.record(
                session, who.actor, "client.create", "client", client.id, after={"name": name}
            )
            await bus_events.client_created(session, client, who.actor)
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
                if fields := _snapshot_fields(after):
                    await bus_events.client_updated(session, client, who.actor, fields)
            # Деактивированный клиент — снова меню лида (`verified_client`), и наоборот.
            chats = (
                await leads_repo.chats_of_client(session, client_id) if "is_active" in after else []
            )
        await notify_chats(self._on_chats_changed, chats)

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
                    await bus_events.lead_updated(session, lead, who.actor, ["crm_client_id"])
            await audit.record(
                session,
                who.actor,
                "client.link_telegram",
                "client",
                client_id,
                after={"tg_user_id": tg_user_id},
            )
        await notify_chats(self._on_chats_changed, [tg_user_id])

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
            after: dict[str, Any] = {"tg_user_id": tg_user_id}
            if identity.lead_id is not None:
                after |= await _detach_lead(session, identity.lead_id, client_id, who)
            await audit.record(
                session, who.actor, "client.unlink_telegram", "client", client_id, after=after
            )
        await notify_chats(self._on_chats_changed, [tg_user_id])

    async def make_customer(
        self, who: Principal, lead_id: int, client_id: int | None, new_name: str | None
    ) -> int:
        """Лид → клиент («Передан в бэк-офис», ADR-0022): привязка лида и его Telegram, стадия
        `customer`. Повторная передача тому же клиенту ничего не меняет (идемпотентно).

        В режиме `erp` клиент и стадия коммитятся ПЕРВЫМИ, передача в ERP идёт задачей после коммита
        (`ErpHandoffService`, FIX-31): состояние «передаётся / передан / ошибка» — в карточке."""
        if client_id is None and not (new_name and new_name.strip()):
            raise ValidationFailedError(
                "choose a client or enter a new client name", field="client_id"
            )
        mode = await self._backoffice_mode()
        async with self._sessions() as session, session.begin():
            done = await self._make_customer_tx(session, who, lead_id, client_id, new_name, mode)
        if done.enqueue:
            await self._enqueue_handoff_task(done.client_id, lead_id, who.user_id)
        if done.notify:
            await notify_chats(self._on_chats_changed, done.chats)
        if done.access_notice:
            await self._notify_access(lead_id, done.language)
        return done.client_id

    async def _enqueue_handoff_task(self, client_id: int, lead_id: int, user_id: int) -> None:
        """Поставить передачу в очередь ПОСЛЕ коммита; не вышло — ошибка в карточке, не потеря."""
        if self._erp_handoff_enqueue is None:
            await self._mark_handoff_failed(client_id, Reason.ERP_NOT_CONFIGURED.value, "no queue")
            return
        try:
            await self._erp_handoff_enqueue(client_id, lead_id, user_id)
        except Exception as exc:
            logger.exception("erp_handoff_enqueue_failed", client_id=client_id, lead_id=lead_id)
            await self._mark_handoff_failed(client_id, ENQUEUE_FAILED, str(exc))

    async def _mark_handoff_failed(self, client_id: int, code: str, detail: str) -> None:
        async with self._sessions() as session, session.begin():
            client = await session.get(Client, client_id)
            if client is not None:
                client.erp_handoff_status = FAILED
                client.erp_handoff_error = code
                await audit.record(
                    session,
                    audit.Actor.system(),
                    "client.erp_handoff_failed",
                    "client",
                    client_id,
                    after={"code": code, "detail": detail[:500]},
                )

    async def _make_customer_tx(
        self,
        session: AsyncSession,
        who: Principal,
        lead_id: int,
        client_id: int | None,
        new_name: str | None,
        mode: BackofficeMode,
    ) -> "_CustomerResult":
        lead = await session.get(Lead, lead_id, with_for_update=True)
        if lead is None or lead.erased_at is not None:
            raise NotFoundError("lead not found")
        handoff = decide_handoff(
            Stage(lead.stage),
            mode,
            client_changed=client_id is None or lead.client_id != client_id,
            erp_synced=await _in_erp(session, client_id),
        )
        if not handoff.allowed:
            raise InvalidTransitionError(
                "close the deal (won) first", reason=Reason.DEAL_NOT_CLOSED
            )
        if not may_make_customer(
            stage=lead.stage,
            assigned_user_id=lead.assigned_user_id,
            user_id=who.user_id,
            is_admin=who.is_admin,
            mode=mode,
        ):
            raise ForbiddenError(
                "only the lead owner or an admin can do this", reason=Reason.NOT_LEAD_OWNER
            )
        if handoff.call_erp:
            _require_consent(lead)  # до создания клиента: нет согласия — ничего не меняем
            if self._erp_handoff_enqueue is None:
                raise ConflictError(
                    "erp connector is not configured", reason=Reason.ERP_NOT_CONFIGURED
                )
        if not handoff.call_erp and not handoff.changed and client_id is not None:
            return _CustomerResult(client_id)
        if client_id is None:
            client = Client(name=(new_name or "").strip(), owner_user_id=who.user_id)
            session.add(client)
            await session.flush()
            client_id = client.id
            await bus_events.client_created(session, client, who.actor)
        else:
            client = await _client(session, client_id)
        previous_client_id = lead.client_id
        lead.client_id = client_id
        if previous_client_id != client_id:
            await bus_events.lead_updated(session, lead, who.actor, ["crm_client_id"])
        if handoff.changed:  # повторная передача в ERP (resync) привязки не трогает
            await _bind_identities(session, lead_id, client_id, who)
        if handoff.call_erp:
            # Передачу делает задача после коммита; повтор после сбоя не теряет заявку.
            client.erp_handoff_request = client.erp_handoff_request or not handoff.resync
            client.erp_handoff_status, client.erp_handoff_error = PENDING, None
            await session.flush()

        if handoff.resync:
            # Только передача в ERP уже существующего клиента: владелец, стадия, сделки лида
            # и аудит `lead.make_customer` остаются как были.
            await audit.record(
                session,
                who.actor,
                "client.erp_handoff",
                "client",
                client_id,
                after={"lead_id": lead_id, "erp_handoff": PENDING},
            )
            return _CustomerResult(client_id, enqueue=True)

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
        after_data: dict[str, Any] = {"client_id": client_id, "backoffice": handoff.mode.value}
        if handoff.call_erp:
            after_data["erp_handoff"] = PENDING
        if client.erp_company_id is not None:
            after_data["erp_company_id"] = client.erp_company_id
        await audit.record(
            session, who.actor, "lead.make_customer", "lead", lead_id, after=after_data
        )
        await events.publish(session, "lead.updated", lead_id=lead_id)
        return _CustomerResult(
            client_id,
            enqueue=handoff.call_erp,
            notify=True,
            chats=await leads_repo.chats_of_lead(session, lead_id),
            access_notice=handoff.changed,
            language=lead.language,
        )

    async def _notify_access(self, lead_id: int, language: str) -> None:
        """Один раз при привязке: клиенту стали доступны документы и запросы (/help)."""
        if self._settings is None or self._messenger is None:
            return
        cfg = await self._settings.get()
        text = cfg.texts.client_access_granted.get(LANGUAGES.get(language, "ru"))
        try:
            await self._messenger.send(lead_id, text, {"notice": "client_access_granted"})
        except Exception:
            logger.exception("client_access_notice_failed", lead_id=lead_id)

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
                await _resolve_info_escalation(session, lead.id, request_id, now)
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
                LANGUAGES.get(language, "ru"),
                number=str(request_id),
                summary=summary[:200],
                resolution=resolution.strip(),
            )
            await self._messenger.send(lead.id, text, {"notice": "service_request_closed"})


async def _resolve_info_escalation(
    session: AsyncSession, lead_id: int, request_id: int, now: datetime
) -> None:
    """Info-эскалация о запросах закрывается с последним открытым запросом лида.

    Связи «эскалация ↔ запрос» в схеме нет: закрываем только info-эскалацию, все причины
    которой — `service_request`, и только если у лида не осталось других открытых
    запросов. Срочные и эскалации с другими причинами остаются у команды.
    """
    others = await session.scalar(
        select(ServiceRequest.id)
        .where(
            ServiceRequest.lead_id == lead_id,
            ServiceRequest.status == "open",
            ServiceRequest.id != request_id,
        )
        .limit(1)
    )
    if others is not None:
        return
    rows = (
        await session.scalars(
            select(Escalation)
            .where(
                Escalation.lead_id == lead_id,
                Escalation.status.in_(OPEN_STATUSES),
                Escalation.priority == "info",
            )
            .with_for_update()
        )
    ).all()
    for escalation in rows:
        if not only_service_request(escalation.reason_codes):
            continue
        escalation.status, escalation.resolved_at = "closed", now
        escalation.outcome = "service_request_closed"
        await events.publish(
            session, "escalation.updated", lead_id=lead_id, escalation_id=escalation.id
        )


def _snapshot_fields(changes: dict[str, Any]) -> list[str]:
    """Изменённые поля клиента в терминах снимка события (`notes` в него не входят)."""
    return ["owner" if name == "owner_user_id" else name for name in changes if name != "notes"]


def only_service_request(reason_codes: list[str] | None) -> bool:
    """Эскалация создана только запросом клиента (других причин нет)."""
    codes = set(reason_codes or ())
    return bool(codes) and codes <= {TriggerCode.SERVICE_REQUEST.value}


async def _detach_lead(
    session: AsyncSession, lead_id: int, client_id: int, who: Principal
) -> dict[str, Any]:
    """Последний подтверждённый Telegram лида отвязан — лид больше не клиент (SPEC §7.3)."""
    still_linked = await session.scalar(
        select(TelegramIdentity.id)
        .where(
            TelegramIdentity.lead_id == lead_id,
            TelegramIdentity.client_id == client_id,
            TelegramIdentity.verified_at.is_not(None),
        )
        .limit(1)
    )
    lead = await session.get(Lead, lead_id, with_for_update=True)
    if still_linked is not None or lead is None or lead.client_id != client_id:
        return {}
    lead.client_id = None
    await bus_events.lead_updated(session, lead, who.actor, ["crm_client_id"])
    changes: dict[str, Any] = {"lead_id": lead_id, "lead_client_cleared": True}
    if lead.stage == Stage.CUSTOMER:
        target = stage_after_unlink(await lead_parts.history(session, lead_id))
        await stages.transition(
            session,
            lead,
            target,
            TransitionSource.USER,
            reason="telegram unlinked from client",
            actor_user_id=who.user_id,
        )
        changes["stage"] = target.value
    await events.publish(session, "lead.updated", lead_id=lead_id)
    return changes


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


def _require_consent(lead: Lead) -> HandoffConsent:
    """Согласие лида для ERP (I-13): время и версия — из лида, иначе 422 «нет согласия»."""
    consent = handoff_consent(lead.consent_given_at, lead.consent_version)
    if consent is None:
        raise ValidationFailedError(
            "lead has not given consent to data processing",
            reason=Reason.HANDOFF_NO_CONSENT,
            field="consent",
        )
    return consent


async def _in_erp(session: AsyncSession, client_id: int | None) -> bool:
    """Есть ли клиент в ERP (`erp_company_id`); новый клиент — ещё нет, но и передача настоящая."""
    if client_id is None:
        return True
    return (
        await session.scalar(select(Client.erp_company_id).where(Client.id == client_id))
        is not None
    )


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
