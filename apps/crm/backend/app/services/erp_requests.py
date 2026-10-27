"""Заявка CRM → ERP задачей после коммита «Создать заявку» (CRM-03, W16-D1-2; шов 0.8.0).

Задача читает текущую заявку (`deals`), клиента, лида и контакт:

1. Клиента ещё нет в ERP (`erp_company_id` пуст) — сначала передача (`ErpHandoffService`, без
   заявки: `create_request: false`); её постоянная ошибка (нет согласия, ИНН другого клиента) —
   ошибка и заявки.
2. `POST /clients/{crm_client_id}/requests` с сутью, срочностью, контактом, файлом письма и
   менеджером заявки (`owner_user_id` — владелец сделки ERP, B-008). Идемпотентно по заявке CRM
   (`crm_request_id` = `deals.id`).
3. Итог — `deals.erp_request_status` / `erp_request_error`: `done` с `erp_deal_id` и номером ЗВ;
   постоянная ошибка (404, 422) — `failed` без автоповтора; временная — исключение, Procrastinate
   повторяет, на последней попытке — `failed`.

Событие `request.created` (в нём `crm_request_id`) могло прийти раньше ответа — тогда зеркало уже
связано с заявкой.
"""

from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    Reason,
    ValidationFailedError,
)
from app.integrations.erp import HandoffContactPayload
from app.integrations.erp_requests import (
    ClientRequestPayload,
    ClientRequestResult,
    ErpRequestClient,
)
from app.models.auth import User
from app.models.clients import Client, ClientContact
from app.models.deals import Deal
from app.models.leads import Lead, TelegramIdentity
from app.security import audit
from app.services.erp_handoff import ErpHandoffService

logger = structlog.get_logger(__name__)

Outcome = Literal["done", "failed", "skipped"]
MAX_ERROR_LEN = 500
_LANGUAGES = ("ru", "uz", "en")


@dataclass(frozen=True, slots=True)
class _Ready:
    payload: ClientRequestPayload | None
    client_id: int
    handoff_lead_id: int | None = None


class ErpRequestService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        client: ErpRequestClient,
        handoff: ErpHandoffService,
    ) -> None:
        self._sessions = sessions
        self._client = client
        self._handoff = handoff

    async def run(
        self, deal_id: int, actor_user_id: int | None, *, final_attempt: bool = False
    ) -> Outcome:
        ready = await self._prepare(deal_id)
        if isinstance(ready, str):
            return ready
        if ready.handoff_lead_id is not None:
            outcome = await self._hand_off(deal_id, ready, actor_user_id, final_attempt)
            if outcome != "done":
                return outcome
            ready = await self._prepare(deal_id)
            if isinstance(ready, str):
                return ready
        if ready.payload is None:
            return "skipped"
        try:
            result = await self._client.create_client_request(ready.payload)
        except (ConflictError, ValidationFailedError, NotFoundError) as exc:
            if exc.details.get("reason") == Reason.ERP_NOT_CONFIGURED:
                await self._transient(deal_id, exc, final_attempt)
                raise
            await self._fail(deal_id, _code(exc), exc.message)
            return "failed"
        except Exception as exc:
            await self._transient(deal_id, exc, final_attempt)
            raise
        await self._complete(deal_id, result)
        return "done"

    async def _prepare(self, deal_id: int) -> _Ready | Outcome:
        async with self._sessions() as session, session.begin():
            deal = await session.get(Deal, deal_id, with_for_update=True)
            if deal is None or deal.client_id is None or deal.request_summary is None:
                return "skipped"
            if deal.erp_request_status == "done" and deal.erp_deal_id is not None:
                return "skipped"  # устаревшая задача: заявка уже в ERP
            client = await session.get(Client, deal.client_id)
            if client is None:
                return "skipped"
            lead = await session.get(Lead, deal.lead_id) if deal.lead_id else None
            if client.erp_company_id is None:
                handoff_lead = (
                    lead
                    if lead is not None and lead.erased_at is None
                    else await _consenting_lead(session, client.id)
                )
                if handoff_lead is None:
                    _set(deal, "failed", Reason.HANDOFF_NO_CONSENT.value)
                    return "failed"
                client.erp_handoff_request = False  # заявку заводит эта задача, не передача
                return _Ready(None, client.id, handoff_lead_id=handoff_lead.id)
            payload = await _payload(session, deal, client, lead)
            return _Ready(payload, client.id)

    async def _hand_off(
        self, deal_id: int, ready: _Ready, actor_user_id: int | None, final_attempt: bool
    ) -> Outcome:
        """Передача клиента без заявки; временная ошибка летит (повтор задачи), постоянная — ошибка
        и заявки."""
        if ready.handoff_lead_id is None:
            return "skipped"
        try:
            outcome = await self._handoff.run(
                ready.client_id, ready.handoff_lead_id, actor_user_id, final_attempt=final_attempt
            )
        except Exception as exc:
            await self._transient(deal_id, exc, final_attempt)
            raise
        if outcome == "done":
            return "done"
        async with self._sessions() as session, session.begin():
            deal = await session.get(Deal, deal_id, with_for_update=True)
            client = await session.get(Client, deal.client_id) if deal and deal.client_id else None
            if client is not None and client.erp_company_id is not None:
                return "done"  # передачу уже сделала другая задача
            if deal is not None:
                _set(
                    deal,
                    "failed",
                    (client.erp_handoff_error if client else None) or "handoff_failed",
                )
        return "failed"

    async def _complete(self, deal_id: int, result: ClientRequestResult) -> None:
        async with self._sessions() as session, session.begin():
            deal = await session.get(Deal, deal_id, with_for_update=True)
            if deal is None:
                return
            other = await session.scalar(
                select(Deal.id).where(Deal.erp_deal_id == result.erp_request_id, Deal.id != deal.id)
            )
            if other is None:
                deal.erp_deal_id = result.erp_request_id
            else:  # зеркало завело событие без связи с заявкой (старый издатель): не задваиваем
                logger.warning("erp_request_mirror_exists", deal_id=deal.id, mirror_id=other)
            deal.erp_number = result.number or deal.erp_number
            deal.external_stage = deal.external_stage or "request"
            _set(deal, "done", None)
            lead = await session.get(Lead, deal.lead_id) if deal.lead_id else None
            if lead is not None:
                lead.erp_request_id = result.erp_request_id
                await bus_events.lead_updated(
                    session, lead, audit.Actor.system(), ["erp_request_id"]
                )
            await audit.record(
                session,
                audit.Actor.system(),
                "deal.erp_request_done",
                "deal",
                deal.id,
                after={"erp_deal_id": result.erp_request_id, "number": result.number},
            )

    async def _transient(self, deal_id: int, exc: BaseException, final_attempt: bool) -> None:
        logger.warning("erp_request_failed", deal_id=deal_id, error=str(exc), final=final_attempt)
        if final_attempt:
            await self._fail(deal_id, _code(exc), _detail(exc))
            return
        async with self._sessions() as session, session.begin():
            deal = await session.get(Deal, deal_id, with_for_update=True)
            if deal is not None and deal.erp_request_status != "done":
                _set(deal, "pending", _code(exc))

    async def _fail(self, deal_id: int, code: str, detail: str) -> None:
        logger.warning("erp_request_rejected", deal_id=deal_id, code=code, detail=detail)
        async with self._sessions() as session, session.begin():
            deal = await session.get(Deal, deal_id, with_for_update=True)
            if deal is None:
                return
            _set(deal, "failed", code)
            await audit.record(
                session,
                audit.Actor.system(),
                "deal.erp_request_failed",
                "deal",
                deal_id,
                after={"code": code, "detail": detail[:MAX_ERROR_LEN]},
            )


def _set(deal: Deal, status: str, error: str | None) -> None:
    deal.erp_request_status = status
    deal.erp_request_error = error[:MAX_ERROR_LEN] if error else None


def _code(exc: BaseException) -> str:
    reason = exc.details.get("reason") if isinstance(exc, DomainError) else None
    return str(reason) if reason else type(exc).__name__


def _detail(exc: BaseException) -> str:
    return exc.message if isinstance(exc, DomainError) else str(exc)


async def _consenting_lead(session: AsyncSession, client_id: int) -> Lead | None:
    return await session.scalar(
        select(Lead)
        .where(
            Lead.client_id == client_id,
            Lead.erased_at.is_(None),
            Lead.consent_given_at.is_not(None),
        )
        .order_by(Lead.id.desc())
        .limit(1)
    )


async def _payload(
    session: AsyncSession, deal: Deal, client: Client, lead: Lead | None
) -> ClientRequestPayload:
    owner = await session.get(User, deal.owner_user_id) if deal.owner_user_id else None
    contact = (
        await session.get(ClientContact, deal.request_contact_id)
        if deal.request_contact_id
        else None
    )
    language = lead.language if lead is not None and lead.language in _LANGUAGES else "ru"
    return ClientRequestPayload(
        crm_client_id=client.id,
        crm_request_id=deal.id,
        crm_lead_id=lead.id if lead else None,
        summary=(deal.request_summary or "")[:5000],
        urgency=deal.request_urgency or "normal",
        owner_crm_user_id=deal.owner_user_id or 0,
        owner_name=(owner.full_name if owner else None) or "Менеджер",
        contact=await _contact_payload(session, contact, language) if contact else None,
        product_interest=tuple(lead.product_interest or []) if lead else (),
        letter_file_id=deal.request_letter_file_id,
    )


async def _contact_payload(
    session: AsyncSession, contact: ClientContact, language: str
) -> HandoffContactPayload:
    identity = (
        await session.get(TelegramIdentity, contact.telegram_identity_id)
        if contact.telegram_identity_id
        else None
    )
    telegram = identity.tg_user_id if identity else None
    preferred = (
        "both"
        if telegram and contact.email
        else ("email" if contact.email and not telegram else "telegram")
    )
    return HandoffContactPayload(
        crm_contact_id=contact.id,
        name=contact.full_name,
        phone=contact.phone_e164 or "",
        email=contact.email or "",
        telegram_user_id=telegram,
        language=language,
        is_primary=contact.is_primary,
        preferred_channel=preferred,
    )
