"""Обезличивание лида и чат кабинета (CHAT-1, CHAT-1b; DECISIONS 2026-11-04 «Лид CHAT/NOTIFY» п. 3).

`/delete` (`ErasureMixin.erase`) стирает в кабинете только сообщения этого человека (его контакты
клиента): автор — «Удалённый пользователь», текст удалён. Беседа кабинета живёт на клиенте: якорь
переходит на другой лид клиента или новый по правилу якоря. Неотвеченное сообщение кабинета не
пропадает. «Неотвечено» определяется по самой беседе (последнее сообщение клиента позже последнего
ответа менеджера в неё), а не по наличию передачи у стираемого лида: сообщение могло ждать ответа
в «Мои» у менеджера стираемого якоря, передачи при этом нет. Дальше — по новому якорю: ведёт
менеджер — лид «ждёт ответа» в «Мои» у ответственного; иначе открытая передача `cabinet_message`
(исходная переносится с временем и сроком SLA, если исходной не было — новая со сроком от
настроек). Вызывать в транзакции обезличивания до `close_escalations` и `erase_lead`.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.business_hours import add_business_minutes
from app.domain.stages import OwnerMode
from app.domain.triggers import PRIORITY, TriggerCode
from app.models.clients import Client
from app.models.leads import Conversation, Lead
from app.models.qualification import Escalation
from app.repositories import cabinet_chat as repo
from app.schemas.settings import AppSettings
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


async def erase_for_lead(session: AsyncSession, lead: Lead, cfg: AppSettings) -> CabinetErasure:
    conversations = await repo.cabinet_conversations_of(session, lead)
    contacts = await repo.person_contacts(session, lead.id)
    erp_contacts = await repo.erase_authors(session, [c.id for c in conversations], contacts)
    result = CabinetErasure()
    pending = await _cabinet_escalation(session, lead.id)
    for conversation in conversations:
        if conversation.lead_id != lead.id:
            continue
        anchor = await _reanchor(session, conversation, lead)
        if not await repo.waits_for_reply(session, conversation.id):
            continue  # ответили — переносить нечего
        moved = await _carry(session, pending, anchor, cfg)
        pending = None  # исходная передача — одна, на первую неотвеченную беседу
        if moved is not None:
            result.moved_escalations.append((moved, anchor.id))
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
    session: AsyncSession, source: Escalation | None, anchor: Lead, cfg: AppSettings
) -> int | None:
    """Неотвеченную беседу кабинета делаем видимой у нового якоря — по тому же правилу, что и
    входящее сообщение (`CabinetChatService._escalate`):

    * якорь ведёт менеджер (`human` с ответственным) — передачу не заводим и не переназначаем:
      иначе была бы открытая передача, которую держатель не закроет (ответ в беседу передачи не
      закрывает, «Забрать» своё — ничего не делает), или вторая «забранная». Лид «ждёт ответа» в
      «Мои» у ответственного: `last_lead_msg_at` якоря сдвигается на «сейчас». Отметка общая для
      всех бесед лида и Telegram, поэтому время именно этого сообщения в ней выразить нельзя —
      ответ менеджера своему лиду или создание якоря после сообщения иначе перекрыли бы его. Само
      сообщение, его время и порядок в беседе не меняются; у лида `human` срока SLA нет. Ответ
      менеджера в беседу (`LeadService.reply` → `last_human_msg_at`) снимает «ждёт ответа»;
    * иначе — открытая передача: исходная переносится с временем и сроком SLA, исходной нет (беседа
      ждала в «Мои» стираемого лида) — новая со сроком от настроек; у якоря уже есть ждущая —
      причина дописывается к ней, срок — более ранний. Причины Telegram стёртого лида и тексты
      записки (могут нести его ПД) не переносятся; исходная закрывается вместе с лидом.

    Возвращает передачу для поста в канале команды (None — передачи нет)."""
    now = datetime.now(UTC)
    if anchor.owner_mode == OwnerMode.HUMAN.value and anchor.assigned_user_id is not None:
        anchor.last_lead_msg_at = now
        logger.info("cabinet_message_to_mine", to_lead=anchor.id)
        return None
    sla_due_at = source.sla_due_at if source is not None else None
    if source is None:
        sla_due_at = add_business_minutes(
            now, cfg.escalation.sla_minutes, cfg.business_hours.domain()
        )
    current = await _active(session, anchor.id)
    if current is not None:
        if CABINET_REASON not in current.reason_codes:
            current.reason_codes = [*current.reason_codes, CABINET_REASON]
        if sla_due_at is not None and (
            current.sla_due_at is None or sla_due_at < current.sla_due_at
        ):
            current.sla_due_at = sla_due_at
            current.sla_notified_at = source.sla_notified_at if source is not None else None
        moved = current
    else:
        moved = Escalation(
            lead_id=anchor.id,
            reason_codes=[CABINET_REASON],
            priority=PRIORITY[TriggerCode.CABINET_MESSAGE].value,
            status="open",
            sla_due_at=sla_due_at,
            sla_notified_at=source.sla_notified_at if source is not None else None,
        )
        if source is not None:
            moved.created_at = source.created_at
        session.add(moved)
    if anchor.owner_mode == OwnerMode.BOT.value:
        anchor.owner_mode = OwnerMode.PAUSED.value  # ждёт человека, как при передаче
    await session.flush()
    logger.info(
        "cabinet_escalation_moved",
        from_lead=source.lead_id if source is not None else None,
        to_lead=anchor.id,
        escalation=moved.id,
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
