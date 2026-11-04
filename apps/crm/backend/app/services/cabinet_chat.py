"""Чат кабинета (CHAT-1, ADR-0023): канал `cabinet` в той же очереди «Сообщения», что и Telegram.

Входящее — событие `uz.railtech.erp.cabinet.message_posted.v1` в транзакции записи inbox шины:

* беседа `cabinet` одна на клиента и на компанию ERP (частичные уникальные индексы; создание — под
  advisory-блокировкой компании, параллельные обработчики не заводят вторую);
* клиент — по `crm_client_id` события, иначе по `clients.erp_company_id`. Не нашёлся — сообщение не
  теряется: беседа заводится на компанию ERP, якорем становится новый лид `source=cabinet` с
  названием компании, сообщение ждёт менеджера в «Требуют внимания»; когда компания станет
  клиентом, беседа и лид привязываются к нему на следующем сообщении;
* якорный лид — тот, к которому беседа привязана; новой беседе — лид клиента с последней
  активностью, нет лида — новый лид `source=cabinet`, стадия `customer`, ответственный — владелец
  клиента. Якорь не переезжает с каждым сообщением (история беседы — у одного лида); обезличенный
  якорь заменяется;
* бот-ИИ входящее кабинета не обрабатывает: лид у человека (`human`) — сообщение сразу в «Мои»
  (ждёт ответа), иначе эскалация с причиной `cabinet_message` и SLA (пост в канале команды — после
  коммита, `dispatch`);
* повтор того же сообщения (тот же `client_message_id` в беседе) — без второй записи.

Ответ менеджера уходит в канал последнего входящего сообщения клиента (`LeadService.reply`); в
кабинет — `send_reply`: строка сообщения и событие `uz.railtech.crm.cabinet.message_sent.v1` одной
транзакцией.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Final

import structlog
from rt_bus import Event
from rt_contracts.events.erp import CabinetMessagePostedV1
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.domain.stages import OwnerMode, Stage
from app.domain.triggers import TriggerSignals, evaluate
from app.models.auth import User
from app.models.clients import Client
from app.models.leads import Conversation, Lead
from app.repositories import cabinet_chat as repo
from app.repositories import crm as crm_repo
from app.security.audit import Actor
from app.services import escalation, message_log
from app.services.lead_messenger import DeliveryError
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

POSTED_TYPE: Final = "uz.railtech.erp.cabinet.message_posted.v1"
CABINET_SOURCE: Final = repo.CABINET

EscalationHook = Callable[[int, bool], Awaitable[object]]


class CabinetCompanyMismatchError(Exception):
    """Беседа кабинета клиента — другой компании ERP, чем событие (сопоставление разошлось)."""


class CabinetChatService:
    def __init__(self, settings: SettingsService, on_escalation: EscalationHook | None) -> None:
        self._settings = settings
        self._on_escalation = on_escalation
        # Эскалация, открытая обработкой события: пост в канале — после коммита (`dispatch`).
        self._pending: dict[str, tuple[int, bool]] = {}

    async def accept(self, session: AsyncSession, event: Event) -> None:
        """Сообщение кабинета → беседа `cabinet` и очередь «Сообщения»; в транзакции inbox."""
        data = CabinetMessagePostedV1.model_validate(event.data)
        payload = data.payload
        company = data.erp_company_id
        lock = func.hashtextextended(f"cabinet-chat:{company}", 0)
        await session.execute(select(func.pg_advisory_xact_lock(lock)))
        client = await repo.client_of(session, data.crm_client_id, company)
        conversation = await repo.cabinet_conversation(
            session, client.id if client is not None else None, company
        )
        if conversation is not None and conversation.erp_company_id not in (None, company):
            # Клиент CRM уже ведёт беседу с другой компанией ERP: в чужую ленту не пишем — событие в
            # failed (журнал шины), разбирается сопоставление клиента и компании.
            raise CabinetCompanyMismatchError(
                f"cabinet conversation {conversation.id} belongs to erp company "
                f"{conversation.erp_company_id}, event is for {company}"
            )
        key = payload.client_message_id
        if conversation is not None and await repo.inbound_by_key(session, conversation.id, key):
            logger.info("cabinet_message_duplicate", erp_company_id=company)
            return
        now = datetime.now(UTC)
        lead = await self._anchor(session, client, conversation, payload.company_name)
        conversation = await _attach(session, conversation, lead, client, company)
        await message_log.add(
            session, conversation, role="lead", text=payload.text, meta=_inbound_meta(data)
        )
        lead.last_lead_msg_at = now
        await self._escalate(session, lead, str(event.id), now)
        logger.info(
            "cabinet_message_accepted",
            lead_id=lead.id,
            erp_company_id=company,
            client_found=client is not None,
        )

    async def dispatch(self, event_id: str) -> None:
        """После коммита обработки: пост эскалации в канале команды и проверка SLA."""
        pending = self._pending.pop(event_id, None)
        if pending is None or self._on_escalation is None:
            return
        escalation_id, is_new = pending
        try:
            await self._on_escalation(escalation_id, is_new)
        except Exception as exc:  # noqa: BLE001 — очередь недоступна; передача видна в Платформе
            logger.warning("cabinet_escalation_notify_failed", error=type(exc).__name__)

    async def _anchor(
        self,
        session: AsyncSession,
        client: Client | None,
        conversation: Conversation | None,
        company_name: str,
    ) -> Lead:
        if conversation is not None:
            current = await session.get(Lead, conversation.lead_id, with_for_update=True)
            if current is not None and current.erased_at is None:
                if client is not None and current.client_id is None:
                    _adopt(current, client)
                return current
        if client is not None:
            found = await repo.anchor_lead(session, client.id)
            if found is not None:
                return found
        return await _new_lead(session, client, company_name)

    async def _escalate(
        self, session: AsyncSession, lead: Lead, event_id: str, now: datetime
    ) -> None:
        if lead.owner_mode == OwnerMode.HUMAN:
            return  # беседа у человека — сообщение в «Мои» (ждёт ответа), без передачи
        cfg = await self._settings.get()
        hits = evaluate(TriggerSignals(cabinet_message=True), cfg.escalation.triggers())
        applied = await escalation.apply(session, lead, hits, cfg, now)
        if applied is not None:
            self._pending[event_id] = (applied.escalation_id, applied.plan.is_new)


def _inbound_meta(data: CabinetMessagePostedV1) -> dict[str, Any]:
    payload = data.payload
    meta: dict[str, Any] = {
        "channel": CABINET_SOURCE,
        "client_message_id": payload.client_message_id,
        "author_name": payload.author.name,
        "erp_contact_id": payload.author.erp_contact_id,
        "crm_contact_id": payload.author.crm_contact_id,
        "erp_message_id": payload.erp_message_id,
    }
    if payload.context is not None:
        meta["context"] = {
            "kind": payload.context.kind.value,
            "erp_id": payload.context.erp_id,
            "number": payload.context.number,
        }
    return meta


def _adopt(lead: Lead, client: Client) -> None:
    """Компания стала клиентом: лид беседы (заведённый без клиента) привязывается к нему."""
    lead.client_id = client.id
    if lead.assigned_user_id is None:
        lead.assigned_user_id = client.owner_user_id


async def _new_lead(session: AsyncSession, client: Client | None, company_name: str) -> Lead:
    name = (client.name if client is not None else company_name).strip()[:255]
    lead = Lead(
        display_name=name,
        company_name=name or None,
        source=CABINET_SOURCE,
        stage=Stage.CUSTOMER.value if client is not None else Stage.NEW.value,
        client_id=client.id if client is not None else None,
        assigned_user_id=client.owner_user_id if client is not None else None,
    )
    session.add(lead)
    await session.flush()
    await bus_events.lead_created(session, lead, Actor.system())
    return lead


async def _attach(
    session: AsyncSession,
    conversation: Conversation | None,
    lead: Lead,
    client: Client | None,
    company: int,
) -> Conversation:
    """Беседа кабинета на якорном лиде: новая или прежняя (открытая, с клиентом и компанией)."""
    if conversation is None:
        conversation = Conversation(
            lead_id=lead.id,
            channel=CABINET_SOURCE,
            tg_chat_id=None,
            client_id=client.id if client is not None else None,
            erp_company_id=company,
        )
        session.add(conversation)
        await session.flush()
        return conversation
    conversation.lead_id = lead.id
    conversation.is_open = True
    if client is not None and conversation.client_id is None:
        conversation.client_id = client.id
    if conversation.erp_company_id is None:
        conversation.erp_company_id = company
    await session.flush()
    return conversation


async def send_reply(
    sessions: async_sessionmaker[AsyncSession],
    lead_id: int,
    text: str,
    key: str | None,
    *,
    sent_by_user_id: int,
) -> tuple[int, bool]:
    """Ответ менеджера в кабинет: сообщение и `cabinet.message_sent` одной транзакцией.

    Возвращает (id сообщения, доставлено этим вызовом). Ключ повтора занят — прежний ответ, без
    второго сообщения (advisory-блокировка на лид и ключ, как у ответа в Telegram)."""
    async with sessions() as session, session.begin():
        if key is not None:
            lock = func.hashtextextended(f"reply:{lead_id}:{key}", 0)
            await session.execute(select(func.pg_advisory_xact_lock(lock)))
            found = await crm_repo.reply_by_key(session, lead_id, key)
            if found is not None:
                return found.id, False
        conversation = await repo.open_cabinet_conversation(session, lead_id)
        lead = await session.get(Lead, lead_id, with_for_update=True)
        if conversation is None or conversation.erp_company_id is None or lead is None:
            raise DeliveryError("cabinet conversation is closed")
        meta: dict[str, Any] = {"mode": "manager", "channel": CABINET_SOURCE, "delivery": "sent"}
        if key is not None:
            meta["client_message_id"] = key
        message = await message_log.add(
            session,
            conversation,
            role="manager",
            text=text,
            sent_by_user_id=sent_by_user_id,
            meta=meta,
        )
        user = await session.get(User, sent_by_user_id)
        await bus_events.cabinet_message_sent(
            session,
            lead,
            message,
            erp_company_id=conversation.erp_company_id,
            crm_client_id=conversation.client_id,
            manager_name=user.full_name if user is not None else None,
            actor=Actor(sent_by_user_id, "user"),
        )
        lead.last_human_msg_at = datetime.now(UTC)
        return message.id, True


async def erase_for_lead(session: AsyncSession, lead: Lead) -> dict[str, Any] | None:
    """Обезличивание лида (/delete): в кабинете стираются только сообщения этого человека (его
    контакты клиента). Беседа кабинета живёт на клиенте: якорь переходит на другой лид клиента или
    новый лид по правилу якоря. Возвращает `cabinet` для `lead.erased` (или None — стирать нечего).
    Вызывать в транзакции обезличивания до `erase_lead` (иначе беседа ушла бы вместе с лидом)."""
    conversations = await repo.cabinet_conversations_of(session, lead)
    contacts = await repo.person_contacts(session, lead.id)
    erp_contacts = await repo.erase_authors(session, [c.id for c in conversations], contacts)
    for conversation in conversations:
        if conversation.lead_id != lead.id:
            continue
        client = (
            await session.get(Client, conversation.client_id) if conversation.client_id else None
        )
        anchor = await repo.anchor_lead(session, client.id, exclude=lead.id) if client else None
        if anchor is None:
            anchor = await _new_lead(session, client, lead.company_name or "")
        conversation.lead_id = anchor.id
    await session.flush()
    companies = {c.erp_company_id for c in conversations if c.erp_company_id is not None}
    if not erp_contacts or len(companies) != 1:
        return None
    return {"erp_company_id": companies.pop(), "scope": "authors", "erp_contact_ids": erp_contacts}
