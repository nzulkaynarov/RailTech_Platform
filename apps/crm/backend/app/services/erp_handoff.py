"""Передача клиента в бэк-офис ERP задачей после коммита (FIX-31, ADR-0022).

CONTRACTS §2 `POST /clients/handoff`. «Передать в бэк-офис» сначала коммитит клиента и стадию
лида, потом ставит задачу `erp_handoff_client`. Звонок в ERP внутри транзакции клиента был
причиной двух бед: таймаут ERP откатывал клиента, хотя ERP уже создал компанию (повтор рождал
дубль или вечные 409 по ИНН), а события ERP (`request.created`, `invite.sent`) приходили раньше,
чем клиент фиксировался.

Задача читает **текущее** состояние клиента и лида (как `ErpAccessService`), строит тело передачи,
зовёт ERP и пишет итог в `clients.erp_handoff_*` — его видит менеджер в карточке клиента:

* успех — `done`, `erp_company_id`, зеркало заявки (`deals.erp_deal_id`);
* постоянная ошибка (409 `INN_CONFLICT`, 422, нет согласия, неверный адрес ERP) — `failed` и код
  причины, **без автоповтора**: повтор ничего не изменит, менеджер исправляет данные и повторяет
  передачу сам;
* временная (ERP недоступен, 5xx, 401, коннектор ещё не настроен) — код причины в
  `erp_handoff_error`, задача пробрасывает исключение и Procrastinate повторяет; когда попытки
  кончились — `failed`.

Ошибки видны и в центре внешних сервисов (строка «Передача клиентов в ERP», ADR-0024).
"""

from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.backoffice import HandoffConsent, handoff_consent
from app.domain.erp_handoff import DONE, FAILED, PENDING, handoff_idempotency_key
from app.domain.errors import ConflictError, DomainError, Reason, ValidationFailedError
from app.integrations.erp import (
    ErpClient,
    HandoffCompanyPayload,
    HandoffConsentPayload,
    HandoffContactPayload,
    HandoffInvitePayload,
    HandoffNeedPayload,
    HandoffOwnerPayload,
    HandoffPayload,
    HandoffResult,
    handoff_payload_to_dict,
)
from app.models.auth import User
from app.models.clients import Client, ClientContact
from app.models.deals import Deal
from app.models.leads import Lead, TelegramIdentity
from app.security import audit
from app.services import deals as deals_service

logger = structlog.get_logger(__name__)

MAX_ERROR_LEN = 500
Outcome = Literal["done", "failed", "skipped"]
_LANGUAGES = ("ru", "uz", "en")


@dataclass(frozen=True, slots=True)
class _Prepared:
    payload: HandoffPayload
    key: str


class ErpHandoffService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], erp_client: ErpClient) -> None:
        self._sessions = sessions
        self._client = erp_client

    async def run(
        self,
        client_id: int,
        lead_id: int,
        actor_user_id: int | None,
        *,
        final_attempt: bool = False,
    ) -> Outcome:
        """Передать клиента в ERP: постоянная ошибка записана и не повторяется, временная летит."""
        prepared = await self._prepare(client_id, lead_id, actor_user_id)
        if isinstance(prepared, str):
            return prepared
        try:
            result = await self._client.handoff_client(
                prepared.payload, idempotency_key=prepared.key
            )
        except (ConflictError, ValidationFailedError) as exc:
            if exc.details.get("reason") == Reason.ERP_NOT_CONFIGURED:
                await self._transient(client_id, exc, final_attempt)  # подключат — повтор пройдёт
                raise
            await self._fail(client_id, _code(exc), exc.message)
            return "failed"
        except Exception as exc:
            await self._transient(client_id, exc, final_attempt)
            raise
        await self._complete(client_id, lead_id, prepared.payload.create_request, result)
        return "done"

    async def mark_failed(self, client_id: int, code: str, detail: str) -> None:
        """Ошибка постановки задачи в очередь: запись в карточку клиента."""
        await self._fail(client_id, code, detail)

    async def _prepare(
        self, client_id: int, lead_id: int, actor_user_id: int | None
    ) -> _Prepared | Outcome:
        async with self._sessions() as session, session.begin():
            client = await session.get(Client, client_id, with_for_update=True)
            lead = await session.get(Lead, lead_id)
            if client is None or lead is None or lead.erased_at is not None:
                return "skipped"
            if client.erp_handoff_status == DONE and client.erp_company_id is not None:
                return "skipped"  # устаревшая задача: клиент уже передан
            consent = handoff_consent(lead.consent_given_at, lead.consent_version)
            if consent is None:
                _set_state(client, FAILED, Reason.HANDOFF_NO_CONSENT.value)
                return "failed"
            _set_state(client, PENDING, None)
            payload = await _build_payload(
                session,
                client,
                lead,
                actor_user_id,
                consent,
                create_request=client.erp_handoff_request,
            )
            return _Prepared(
                payload, handoff_idempotency_key(client.id, handoff_payload_to_dict(payload))
            )

    async def _complete(
        self, client_id: int, lead_id: int, create_request: bool, result: HandoffResult
    ) -> None:
        async with self._sessions() as session, session.begin():
            client = await session.get(Client, client_id, with_for_update=True)
            lead = await session.get(Lead, lead_id)
            if client is None:
                return
            client.erp_company_id = result.erp_company_id
            client.erp_handoff_request = False
            _set_state(client, DONE, None)
            erp_deal_id = None
            if create_request and result.erp_request_id and lead is not None:
                await _mirror_request(session, client, lead, result.erp_request_id)
                erp_deal_id = result.erp_request_id
                # Результат передачи — отдельно от сделок лида: поздние заявки клиента из Cabinet
                # привязываются к тому же лиду, и «последняя сделка» — уже не его заявка (D-10).
                lead.erp_request_id = result.erp_request_id
            await audit.record(
                session,
                audit.Actor.system(),
                "client.erp_handoff_done",
                "client",
                client_id,
                after={
                    "erp_company_id": result.erp_company_id,
                    "erp_deal_id": erp_deal_id,
                    "lead_id": lead_id,
                    "invite_sent_via": result.invite_sent_via,
                },
            )

    async def _transient(self, client_id: int, exc: BaseException, final_attempt: bool) -> None:
        logger.warning(
            "erp_handoff_failed", client_id=client_id, error=str(exc), final=final_attempt
        )
        if final_attempt:
            await self._fail(client_id, _code(exc), _detail(exc))
            return
        async with self._sessions() as session, session.begin():
            client = await session.get(Client, client_id, with_for_update=True)
            if client is not None and client.erp_handoff_status != DONE:
                _set_state(client, PENDING, _code(exc))

    async def _fail(self, client_id: int, code: str, detail: str) -> None:
        logger.warning("erp_handoff_rejected", client_id=client_id, code=code, detail=detail)
        async with self._sessions() as session, session.begin():
            client = await session.get(Client, client_id, with_for_update=True)
            if client is None:
                return
            _set_state(client, FAILED, code)
            await audit.record(
                session,
                audit.Actor.system(),
                "client.erp_handoff_failed",
                "client",
                client_id,
                after={"code": code, "detail": detail[:MAX_ERROR_LEN]},
            )


def _set_state(client: Client, status: str, error: str | None) -> None:
    client.erp_handoff_status = status
    client.erp_handoff_error = error[:MAX_ERROR_LEN] if error else None


def _code(exc: BaseException) -> str:
    reason = exc.details.get("reason") if isinstance(exc, DomainError) else None
    return str(reason) if reason else type(exc).__name__


def _detail(exc: BaseException) -> str:
    return exc.message if isinstance(exc, DomainError) else str(exc)


async def _build_payload(
    session: AsyncSession,
    client: Client,
    lead: Lead,
    actor_user_id: int | None,
    consent: HandoffConsent,
    *,
    create_request: bool,
) -> HandoffPayload:
    identities = list(
        await session.scalars(select(TelegramIdentity).where(TelegramIdentity.lead_id == lead.id))
    )
    contacts = await _contacts_payload(session, client, lead, identities)
    channels = [
        channel
        for channel, present in (
            ("telegram", any(c.telegram_user_id for c in contacts)),
            ("email", any(c.email for c in contacts)),
        )
        if present
    ] or ["telegram"]
    language = lead.language if lead.language in _LANGUAGES else "ru"
    return HandoffPayload(
        crm_client_id=client.id,
        crm_lead_id=lead.id,
        company=HandoffCompanyPayload(
            name=client.name, inn=client.inn or "", segment=client.segment or "", language=language
        ),
        contacts=contacts,
        need=HandoffNeedPayload(
            summary=(lead.need_summary or lead.display_name or "Заявка из CRM")[:5000],
            product_interest=lead.product_interest or [],
        ),
        owner=await _owner(session, lead, actor_user_id),
        consent=HandoffConsentPayload(
            given_at=consent.given_at.isoformat(), version=consent.version
        ),
        # Resync: заявку закрыли ещё в режиме local — новую не заводим.
        create_request=create_request,
        invite=HandoffInvitePayload(channels=channels),
    )


async def _owner(
    session: AsyncSession, lead: Lead, actor_user_id: int | None
) -> HandoffOwnerPayload:
    owner = await session.get(User, lead.assigned_user_id) if lead.assigned_user_id else None
    actor = await session.get(User, actor_user_id) if actor_user_id else None
    name = (owner.full_name if owner else None) or (actor.full_name if actor else None)
    return HandoffOwnerPayload(
        crm_user_id=lead.assigned_user_id or actor_user_id or 0, name=name or "Менеджер"
    )


async def _contacts_payload(
    session: AsyncSession, client: Client, lead: Lead, identities: list[TelegramIdentity]
) -> list[HandoffContactPayload]:
    rows = list(
        await session.scalars(
            select(ClientContact)
            .where(ClientContact.client_id == client.id)
            .order_by(ClientContact.is_primary.desc(), ClientContact.id)
        )
    )
    primary_identity = identities[0] if identities else None
    if not rows:
        primary = ClientContact(
            client_id=client.id,
            full_name=lead.display_name or client.name,
            phone_e164=primary_identity.phone_e164
            if primary_identity and primary_identity.phone_e164
            else lead.phone_e164,
            email=lead.email,
            telegram_identity_id=primary_identity.id if primary_identity else None,
            is_primary=True,
        )
        session.add(primary)
        await session.flush()
        rows = [primary]
    language = lead.language if lead.language in _LANGUAGES else "ru"
    out = []
    for row in rows:
        tg_user_id = _telegram_of(row, identities, primary_identity)
        preferred = _preferred_channel(bool(tg_user_id), bool(row.email))
        out.append(
            HandoffContactPayload(
                crm_contact_id=row.id,
                name=row.full_name,
                phone=row.phone_e164 or "",
                email=row.email or "",
                telegram_user_id=tg_user_id,
                language=language,
                is_primary=row.is_primary,
                preferred_channel=preferred,
            )
        )
    return out


def _preferred_channel(has_telegram: bool, has_email: bool) -> str:
    if has_telegram and has_email:
        return "both"
    return "email" if has_email else "telegram"


def _telegram_of(
    contact: ClientContact, identities: list[TelegramIdentity], primary: TelegramIdentity | None
) -> int | None:
    for identity in identities:
        if identity.id == contact.telegram_identity_id:
            return identity.tg_user_id
    return primary.tg_user_id if primary and contact.is_primary else None


async def _free_open_deal(session: AsyncSession, lead: Lead) -> Deal:
    """Открытая сделка лида без заявки ERP; занятую (`erp_deal_id`) не перезаписываем — новая."""
    deal = await deals_service.open_deal(session, lead.id)
    if deal is not None and deal.erp_deal_id is None:
        return deal
    deal = Deal(
        lead_id=lead.id,
        client_id=lead.client_id,
        title=await deals_service.title_for(session, lead),
        product_key=lead.product_interest[0] if lead.product_interest else None,
        currency=await deals_service.default_currency(session),
        owner_user_id=lead.assigned_user_id,
        stage="open",
    )
    session.add(deal)
    await session.flush()
    return deal


async def _mirror_request(
    session: AsyncSession, client: Client, lead: Lead, erp_deal_id: int
) -> None:
    """Зеркало заявки ERP. Событие `request.created` могло прийти раньше ответа — тогда зеркало
    уже есть."""
    stmt = select(Deal).where(Deal.erp_deal_id == erp_deal_id).limit(1).with_for_update()
    deal = await session.scalar(stmt)
    if deal is None:
        try:
            # Уникальный `deals.erp_deal_id` (FIX-33): если событие успело создать зеркало между
            # проверкой и записью, вставка падает в savepoint, и берём созданное событием.
            async with session.begin_nested():
                deal = await _free_open_deal(session, lead)
                deal.erp_deal_id = erp_deal_id
                deal.external_stage = "request"
                await session.flush()
        except IntegrityError:
            deal = await session.scalar(stmt)
            if deal is None:
                raise
    if deal.client_id is None:
        deal.client_id = client.id
    if deal.lead_id is None:
        deal.lead_id = lead.id
    await session.flush()
