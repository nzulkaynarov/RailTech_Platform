"""Обезличивание лида и чат кабинета (CHAT-1, CHAT-1b; DECISIONS 2026-11-04 «Лид CHAT/NOTIFY» п. 3).

`/delete` (`ErasureMixin.erase`) стирает в кабинете только сообщения этого человека (его контакты
клиента): автор — «Удалённый пользователь», текст удалён. Беседа кабинета живёт на клиенте: якорь
переходит на другой лид клиента или новый по правилу якоря. Неотвеченное сообщение кабинета не
пропадает: якорь ведёт менеджер — лид «ждёт ответа» в «Мои» у ответственного; иначе передача
`cabinet_message` переходит на новый якорь открытой, с исходным временем и сроком SLA (перенос, а
не «закрыть и забыть»). Вызывать в транзакции обезличивания до `close_escalations` и `erase_lead`.
"""

from dataclasses import dataclass, field
from typing import Any, Final

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.stages import OwnerMode
from app.domain.triggers import PRIORITY, TriggerCode
from app.models.clients import Client
from app.models.leads import Conversation, Lead
from app.models.qualification import Escalation
from app.repositories import cabinet_chat as repo
from app.services.cabinet_chat import new_lead
from app.services.escalation import OPEN_STATUSES

logger = structlog.get_logger(__name__)

CABINET_REASON: Final = TriggerCode.CABINET_MESSAGE.value
#: Передача стёртого лида, которую переносим: и ждущая, и уже забранная менеджером.
_ACTIVE: Final = ("open", "snoozed", "taken")
#: Лог-метрика (как `rt_bus_metrics`): стирание в ERP пропущено — разбирается по журналу.
SKIPPED_METRIC: Final = "cabinet_erasure_skipped"


@dataclass
class CabinetErasure:
    """Итог для `lead.erased` и для постов передач после коммита."""

    event: dict[str, Any] | None = None
    #: (передача, новый якорь) — пост в канале команды и проверка SLA после коммита
    moved_escalations: list[tuple[int, int]] = field(default_factory=list)


async def erase_for_lead(session: AsyncSession, lead: Lead) -> CabinetErasure:
    conversations = await repo.cabinet_conversations_of(session, lead)
    contacts = await repo.person_contacts(session, lead.id)
    erp_contacts = await repo.erase_authors(session, [c.id for c in conversations], contacts)
    result = CabinetErasure()
    pending = await _cabinet_escalation(session, lead.id)
    for conversation in conversations:
        if conversation.lead_id != lead.id:
            continue
        anchor = await _reanchor(session, conversation, lead)
        if pending is not None:
            moved = await _carry(session, pending, anchor, conversation)
            if moved is not None:
                result.moved_escalations.append((moved, anchor.id))
            pending = None  # одна передача — на одну беседу
    await session.flush()
    companies = {c.erp_company_id for c in conversations if c.erp_company_id is not None}
    if erp_contacts and len(companies) == 1:
        result.event = {
            "erp_company_id": companies.pop(),
            "scope": "authors",
            "erp_contact_ids": erp_contacts,
        }
    elif erp_contacts:
        # Беседы кабинета двух компаний ERP у одного лида: в событии одна компания — стирание в
        # ERP не публикуется, разбирается вручную (в CRM сообщения уже стёрты). Без ПД: id и счёт.
        logger.warning(
            SKIPPED_METRIC,
            metric=SKIPPED_METRIC,
            count=1,
            lead_id=lead.id,
            conversation_ids=sorted(c.id for c in conversations),
            erp_company_ids=sorted(companies),
            erp_contacts=len(erp_contacts),
        )
    return result


async def _reanchor(session: AsyncSession, conversation: Conversation, lead: Lead) -> Lead:
    client = await session.get(Client, conversation.client_id) if conversation.client_id else None
    anchor = await repo.anchor_lead(session, client.id, exclude=lead.id) if client else None
    if anchor is None:
        anchor = await new_lead(session, client, lead.company_name or "")
    conversation.lead_id = anchor.id
    return anchor


async def _cabinet_escalation(session: AsyncSession, lead_id: int) -> Escalation | None:
    stmt = (
        select(Escalation)
        .where(
            Escalation.lead_id == lead_id,
            Escalation.status.in_(_ACTIVE),
            Escalation.reason_codes.contains([CABINET_REASON]),
        )
        .order_by(Escalation.id)
        .limit(1)
        .with_for_update()
    )
    found: Escalation | None = (await session.scalars(stmt)).first()
    return found


async def _carry(
    session: AsyncSession, source: Escalation, anchor: Lead, conversation: Conversation
) -> int | None:
    """Неотвеченное сообщение кабинета — новому якорю, по тому же правилу, что и входящее
    (`CabinetChatService._escalate`):

    * якорь ведёт менеджер (`human` с ответственным) — передачу не заводим и не переназначаем:
      лид «ждёт ответа» в «Мои» у ответственного (`last_lead_msg_at` — время последнего входящего
      беседы кабинета). Иначе была бы открытая передача, которую держатель не закроет, или вторая
      «забранная»;
    * иначе — открытая передача с исходным временем и сроком SLA; у якоря уже есть ждущая — причина
      дописывается к ней, срок — более ранний. Причины Telegram стёртого лида и тексты записки
      (могут нести его ПД) не переносятся; исходная закрывается вместе с лидом.

    Возвращает передачу для поста в канале команды (None — передачи нет)."""
    if anchor.owner_mode == OwnerMode.HUMAN.value and anchor.assigned_user_id is not None:
        last_in = await repo.last_inbound_at(session, conversation.id)
        if last_in is not None and (
            anchor.last_lead_msg_at is None or last_in > anchor.last_lead_msg_at
        ):
            anchor.last_lead_msg_at = last_in
        logger.info("cabinet_message_to_mine", from_lead=source.lead_id, to_lead=anchor.id)
        return None
    current = await _active(session, anchor.id)
    if current is not None:
        if CABINET_REASON not in current.reason_codes:
            current.reason_codes = [*current.reason_codes, CABINET_REASON]
        if source.sla_due_at is not None and (
            current.sla_due_at is None or source.sla_due_at < current.sla_due_at
        ):
            current.sla_due_at, current.sla_notified_at = source.sla_due_at, source.sla_notified_at
        moved = current
    else:
        moved = Escalation(
            lead_id=anchor.id,
            reason_codes=[CABINET_REASON],
            priority=PRIORITY[TriggerCode.CABINET_MESSAGE].value,
            status="open",
            sla_due_at=source.sla_due_at,
            sla_notified_at=source.sla_notified_at,
        )
        moved.created_at = source.created_at
        session.add(moved)
    if anchor.owner_mode == OwnerMode.BOT.value:
        anchor.owner_mode = OwnerMode.PAUSED.value  # ждёт человека, как при передаче
    await session.flush()
    logger.info(
        "cabinet_escalation_moved", from_lead=source.lead_id, to_lead=anchor.id, escalation=moved.id
    )
    return moved.id


async def _active(session: AsyncSession, lead_id: int) -> Escalation | None:
    stmt = (
        select(Escalation)
        # Дописываем только к ждущей передаче (как `escalation.apply`).
        .where(Escalation.lead_id == lead_id, Escalation.status.in_(OPEN_STATUSES))
        .order_by(Escalation.id)
        .limit(1)
        .with_for_update()
    )
    found: Escalation | None = (await session.scalars(stmt)).first()
    return found
