"""«Создать заявку» из лида и из клиента (CRM-03, W16-D1-2; SPEC-v3 §3.1 шаг 2, §7.2).

Одна транзакция CRM: лид → клиент (компания с ИНН — существующая или новая), контакт с каналом
(e-mail не обязателен), заявка — строка `deals` с сутью, срочностью, контактом и файлом письма
директору (id файла EDS); стадия лида — `customer` из любой активной стадии, менеджер —
ответственный за переписку, диалог ведёт бот (сервисный режим), активная передача закрывается. В ERP
заявка уходит задачей после коммита (`tasks/erp_requests.py`, `services/erp_requests.py`): клиента,
ещё не переданного в ERP, задача сначала передаёт, затем создаёт заявку (шов 0.8.0); ERP
регистрирует письмо ВХ директору в EDS. Согласие обязательно: из бота или отметка сотрудника (D-8).
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.domain.backoffice import BackofficeMode
from app.domain.client_requests import may_create_request
from app.domain.erp_handoff import PENDING
from app.domain.errors import (
    ConflictError,
    ForbiddenError,
    InvalidTransitionError,
    NotFoundError,
    Reason,
    ValidationFailedError,
)
from app.domain.stages import OwnerMode, Stage, TransitionSource
from app.models.clients import Client, ClientContact
from app.models.deals import Deal
from app.models.leads import Lead
from app.repositories import events
from app.repositories import leads as leads_repo
from app.schemas.client_requests import RequestCreate, RequestCreated
from app.security import audit
from app.security.principal import Principal
from app.services import deals as deals_service
from app.services import lead_parts, stages
from app.services.clients import _bind_identities, _require_consent
from app.services.lead_consent import LeadConsentService
from app.services.leads import ChatsChanged, notify_chats
from app.services.request_contacts import request_contact as _contact

logger = structlog.get_logger(__name__)

BackofficeModeProvider = Callable[[], Awaitable[BackofficeMode]]
# Поставить заявку в ERP (`tasks.erp_requests`): (deal_id, client_id, user_id).
RequestEnqueue = Callable[[int, int, int], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class _Done:
    result: RequestCreated
    chats: list[int] = field(default_factory=list)

    @property
    def created(self) -> bool:
        return self.result.created


class ClientRequestService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        backoffice_mode: BackofficeModeProvider,
        enqueue: RequestEnqueue | None,
        on_chats_changed: ChatsChanged | None = None,
    ) -> None:
        self._sessions = sessions
        self._mode = backoffice_mode
        self._enqueue = enqueue
        self._on_chats_changed = on_chats_changed
        self._consent = LeadConsentService(sessions)

    async def create_from_lead(
        self, who: Principal, lead_id: int, body: RequestCreate
    ) -> RequestCreated:
        """«Создать заявку» из лида: лид становится клиентом, заявка уходит в ERP задачей после
        коммита."""
        await self._require_erp()
        if body.consent is not None:
            await self._consent.record(who, lead_id, body.consent.method, body.consent.comment)
        try:
            async with self._sessions() as session, session.begin():
                done = await self._from_lead_tx(session, who, lead_id, body)
        except IntegrityError:
            # Параллельный повтор с тем же `request_key` вставил заявку первым (UNIQUE) — отдаём её.
            done = await self._repeat(body.request_key, lead_id=lead_id)
        return await self._after_commit(done, who)

    async def create_for_client(
        self, who: Principal, client_id: int, body: RequestCreate
    ) -> RequestCreated:
        """«Новая заявка для клиента»: из карточки клиента; лид клиента (последний) — для ленты и
        бота."""
        await self._require_erp()
        if body.client_id not in (None, client_id):
            raise ValidationFailedError("client_id does not match the client", field="client_id")
        try:
            async with self._sessions() as session, session.begin():
                done = await self._for_client_tx(session, who, client_id, body)
        except IntegrityError:
            done = await self._repeat(body.request_key, client_id=client_id)
        return await self._after_commit(done, who)

    async def _repeat(
        self, key: uuid.UUID, *, lead_id: int | None = None, client_id: int | None = None
    ) -> _Done:
        async with self._sessions() as session:
            done = await _existing(session, key, lead_id=lead_id, client_id=client_id)
        if done is None:
            raise ConflictError("request was not created, retry", reason=Reason.REQUEST_KEY_REUSED)
        return done

    async def _for_client_tx(
        self, session: AsyncSession, who: Principal, client_id: int, body: RequestCreate
    ) -> _Done:
        client = await session.get(Client, client_id, with_for_update=True)
        if client is None:
            raise NotFoundError("client not found")
        repeat = await _existing(session, body.request_key, client_id=client.id)
        if repeat is not None:
            return repeat
        lead = await _latest_lead(session, client.id)
        if client.erp_company_id is None:
            # Клиент ещё не в ERP: задача передаст его — нужно согласие лида (ERP его не
            # выдумывает).
            if lead is None:
                raise ValidationFailedError(
                    "client has no lead with consent",
                    reason=Reason.HANDOFF_NO_CONSENT,
                    field="consent",
                )
            _require_consent(lead)
        contact = await _contact(session, client, lead, body.contact, who)
        deal = await _request_row(session, client, lead, contact, body, who)
        await audit.record(
            session,
            who.actor,
            "client.create_request",
            "client",
            client.id,
            after=_audit(deal, lead),
        )
        return _Done(
            RequestCreated(client_id=client.id, deal_id=deal.id, lead_id=lead.id if lead else None)
        )

    async def _require_erp(self) -> None:
        if await self._mode() != BackofficeMode.ERP or self._enqueue is None:
            raise ConflictError("erp connector is not configured", reason=Reason.ERP_NOT_CONFIGURED)

    async def _after_commit(self, done: _Done, who: Principal) -> RequestCreated:
        result = done.result
        if not done.created:
            return result  # повтор с тем же `request_key`: та же заявка, без второй задачи
        try:
            if self._enqueue is None:  # проверено `_require_erp`; на случай гонки с отключением
                raise RuntimeError("erp request queue is not configured")
            await self._enqueue(result.deal_id, result.client_id, who.user_id)
        except Exception as exc:
            logger.exception("erp_request_enqueue_failed", deal_id=result.deal_id)
            await self._mark_failed(result.deal_id, str(exc))
            result = result.model_copy(update={"erp_request_status": "failed"})
        if done.chats:
            await notify_chats(self._on_chats_changed, done.chats)
        return result

    async def _mark_failed(self, deal_id: int, detail: str) -> None:
        async with self._sessions() as session, session.begin():
            deal = await session.get(Deal, deal_id, with_for_update=True)
            if deal is not None:
                deal.erp_request_status, deal.erp_request_error = "failed", "enqueue_failed"
                await audit.record(
                    session,
                    audit.Actor.system(),
                    "deal.erp_request_failed",
                    "deal",
                    deal_id,
                    after={"code": "enqueue_failed", "detail": detail[:500]},
                )

    async def _from_lead_tx(
        self, session: AsyncSession, who: Principal, lead_id: int, body: RequestCreate
    ) -> _Done:
        lead = await leads_repo.get_lead(session, lead_id, for_update=True)
        if lead is None or lead.erased_at is not None:
            raise NotFoundError("lead not found")
        repeat = await _existing(session, body.request_key, lead_id=lead.id)
        if repeat is not None:
            return repeat
        if not may_create_request(lead.stage):
            raise InvalidTransitionError(
                f"a request is not created from stage {lead.stage}",
                reason=Reason.REQUEST_NOT_ALLOWED,
            )
        if not who.is_admin and lead.assigned_user_id not in (None, who.user_id):
            raise ForbiddenError(
                "only the lead owner or an admin can do this", reason=Reason.NOT_LEAD_OWNER
            )
        _require_consent(lead)
        before = lead_parts.snapshot(lead)
        client = await _client_for(session, lead, body, who)
        contact = await _contact(session, client, lead, body.contact, who)
        if lead.client_id != client.id:
            await _bind_identities(session, lead.id, client.id, who)
            lead.client_id = client.id
            await bus_events.lead_updated(session, lead, who.actor, ["crm_client_id"])
        await _become_customer(session, lead, who)
        deal = await _request_row(session, client, lead, contact, body, who)
        await audit.record(
            session, who.actor, "lead.create_request", "lead", lead.id, after=_audit(deal, lead)
        )
        await events.publish(session, "lead.updated", lead_id=lead.id)
        changed = before != lead_parts.snapshot(lead)
        return _Done(
            RequestCreated(client_id=client.id, deal_id=deal.id, lead_id=lead.id),
            chats=await leads_repo.chats_of_lead(session, lead.id) if changed else [],
        )


async def _existing(
    session: AsyncSession,
    key: uuid.UUID,
    *,
    lead_id: int | None = None,
    client_id: int | None = None,
) -> _Done | None:
    """Заявка с этим `request_key` (идемпотентность «Создать заявку»): та же форма — та же заявка;
    ключ чужого лида или клиента — 409 `request_key_reused`."""
    deal = await session.scalar(select(Deal).where(Deal.request_key == key))
    if deal is None:
        return None
    if (lead_id is not None and deal.lead_id != lead_id) or (
        client_id is not None and deal.client_id != client_id
    ):
        raise ConflictError(
            "request_key belongs to another request", reason=Reason.REQUEST_KEY_REUSED
        )
    status = (
        deal.erp_request_status
        if deal.erp_request_status in ("pending", "done", "failed")
        else "pending"
    )
    return _Done(
        RequestCreated(
            client_id=deal.client_id or 0,
            deal_id=deal.id,
            lead_id=deal.lead_id,
            erp_request_status=status,
            created=False,
        )
    )


async def _latest_lead(session: AsyncSession, client_id: int) -> Lead | None:
    return await session.scalar(
        select(Lead)
        .where(Lead.client_id == client_id, Lead.erased_at.is_(None))
        .order_by(Lead.consent_given_at.is_(None), Lead.id.desc())
        .limit(1)
    )


async def _client_for(
    session: AsyncSession, lead: Lead, body: RequestCreate, who: Principal
) -> Client:
    """Клиент заявки: выбранный (автопоиск), клиент лида или новая компания из формы."""
    client_id = body.client_id or (lead.client_id if body.company is None else None)
    if client_id is not None:
        client = await session.get(Client, client_id, with_for_update=True)
        if client is None:
            raise NotFoundError("client not found")
        if body.company is not None and body.company.inn and not client.inn:
            client.inn = body.company.inn.strip()
            await bus_events.client_updated(session, client, who.actor, ["inn"])
        return client
    if body.company is None:
        raise ValidationFailedError("choose a client or enter the company", field="company")
    client = Client(
        name=body.company.name.strip(),
        inn=(body.company.inn or "").strip() or None,
        owner_user_id=who.user_id,
    )
    session.add(client)
    await session.flush()
    await bus_events.client_created(session, client, who.actor)
    return client


async def _become_customer(session: AsyncSession, lead: Lead, who: Principal) -> None:
    """Лид → клиент: менеджер — ответственный за переписку, диалог ведёт бот, активная передача
    закрыта."""
    if lead.stage != Stage.CUSTOMER:
        lead.assigned_user_id = lead.assigned_user_id or who.user_id
        lead.owner_mode = OwnerMode.BOT.value
        lead.snoozed_until = None
        await stages.transition(
            session,
            lead,
            Stage.CUSTOMER,
            TransitionSource.USER,
            reason="request created",
            actor_user_id=who.user_id,
        )
    escalation = await lead_parts.active_escalation(session, lead.id)
    if escalation is not None:
        escalation.status, escalation.resolved_at = "closed", datetime.now(UTC)
        escalation.outcome = "request_created"


async def _request_row(
    session: AsyncSession,
    client: Client,
    lead: Lead | None,
    contact: ClientContact,
    body: RequestCreate,
    who: Principal,
) -> Deal:
    """Заявка CRM: открытая сделка лида без заявки ERP (Q-021) или новая строка."""
    deal = await deals_service.open_deal(session, lead.id) if lead is not None else None
    if deal is None or deal.erp_deal_id is not None or deal.erp_request_status is not None:
        deal = Deal(
            lead_id=lead.id if lead else None,
            client_id=client.id,
            title=f"Заявка: {client.name}"[:255],
            product_key=lead.product_interest[0] if lead and lead.product_interest else None,
            currency=await deals_service.default_currency(session),
            stage="open",
        )
        session.add(deal)
    deal.client_id = client.id
    deal.request_key = body.request_key
    deal.owner_user_id = who.user_id
    deal.request_summary = body.summary.strip()
    deal.request_urgency = body.urgency
    deal.request_letter_file_id = body.letter_file_id
    deal.request_contact_id = contact.id
    deal.erp_request_status, deal.erp_request_error = PENDING, None
    await session.flush()
    return deal


def _audit(deal: Deal, lead: Lead | None) -> dict[str, object]:
    return {
        "deal_id": deal.id,
        "client_id": deal.client_id,
        "lead_id": lead.id if lead else None,
        "urgency": deal.request_urgency,
        "letter_file": deal.request_letter_file_id is not None,
        "erp_request": PENDING,
    }
