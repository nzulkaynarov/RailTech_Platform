"""Сообщение известного контакта компании — не новый лид (КОНТР-1а).

Человек, уже заведённый контактом компании (связь с Telegram, телефон или почта контакта),
пишет боту или через форму. Это переписка компании: лид получает компанию, ответственного за
неё (`clients.owner_user_id`) и уходит из «Новых». Бот отвечает как прежде. Нет ответственного
за компанию — лид идёт в обычную очередь, но помечен компанией. Ничего не удаляется, история
остаётся на лиде; кто и когда переназначил — в аудите (`lead.known_contact`).

Контакт компании A никогда не привязывается к компании B: нескольких кандидатов и конфликта с
уже выбранной компанией лида правило не разрешает — лид остаётся как есть. Лид, который уже
ведёт человек, не трогается.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.domain.company_conversation import MARK_KEY
from app.domain.stages import Stage
from app.models.auth import User
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity
from app.models.qualification import StageTransition
from app.repositories import events
from app.security import audit
from app.security.audit import Actor

logger = structlog.get_logger(__name__)

__all__ = ["Outcome", "apply", "company_of_lead"]

# Стадии, в которых лид ещё не в работе у человека: правило применимо только к ним.
_OPEN_STAGES = (Stage.NEW, Stage.ENGAGED, Stage.QUALIFIED, Stage.UNRESPONSIVE)


class Outcome(StrEnum):
    NONE = "none"  # не известный контакт, неоднозначно или лид уже в работе
    MARKED = "marked"  # компания проставлена, ответственного за неё нет
    ASSIGNED = "assigned"  # компания и ответственный
    UNCHANGED = "unchanged"  # правило уже применено


@dataclass(frozen=True, slots=True)
class _Evidence:
    identity_ids: list[int]
    phones: set[str]
    emails: set[str]


async def _evidence(session: AsyncSession, lead: Lead) -> _Evidence:
    rows = (
        await session.execute(
            select(TelegramIdentity.id, TelegramIdentity.phone_e164).where(
                TelegramIdentity.lead_id == lead.id
            )
        )
    ).all()
    phones = {p for _, p in rows if p} | ({lead.phone_e164} if lead.phone_e164 else set())
    emails = {lead.email.lower()} if lead.email else set()
    return _Evidence([int(i) for i, _ in rows], phones, emails)


async def _candidates(session: AsyncSession, lead: Lead) -> set[int]:
    """Активные компании, чьим контактом этот человек уже является."""
    ev = await _evidence(session, lead)
    match = []
    if ev.identity_ids:
        match.append(ClientContact.telegram_identity_id.in_(ev.identity_ids))
    if ev.phones:
        match.append(ClientContact.phone_e164.in_(ev.phones))
    if ev.emails:
        match.append(func.lower(ClientContact.email).in_(ev.emails))
    found: set[int] = set()
    if match:
        stmt = (
            select(ClientContact.client_id)
            .join(Client, Client.id == ClientContact.client_id)
            .where(or_(*match), Client.is_active.is_(True))
        )
        found |= {int(i) for i in (await session.scalars(stmt)).all()}
    if ev.identity_ids:
        linked = (
            select(TelegramIdentity.client_id)
            .join(Client, Client.id == TelegramIdentity.client_id)
            .where(TelegramIdentity.id.in_(ev.identity_ids), Client.is_active.is_(True))
        )
        found |= {int(i) for i in (await session.scalars(linked)).all() if i is not None}
    return found


async def company_of_lead(session: AsyncSession, lead: Lead) -> Client | None:
    """Компания, к которой лид относится однозначно; иначе `None`."""
    found = await _candidates(session, lead)
    if lead.client_id is not None:
        chosen = lead.client_id if (not found or lead.client_id in found) else None
    else:
        chosen = next(iter(found)) if len(found) == 1 else None
    client = await session.get(Client, chosen) if chosen is not None else None
    return client if client is not None and client.is_active else None


def _applicable(lead: Lead) -> bool:
    if (
        lead.erased_at is not None
        or lead.discarded_kind is not None
        or lead.owner_mode == "human"
        or lead.stage not in _OPEN_STAGES
    ):
        return False
    if lead.assigned_user_id is None:
        return True
    mark = (lead.qualification or {}).get(MARK_KEY)
    # Переназначенный человеком после метки лид правило не трогает.
    return isinstance(mark, dict) and mark.get("user_id") == lead.assigned_user_id


async def _matched_contact(session: AsyncSession, lead: Lead, client_id: int) -> int | None:
    """Контакт компании, опознанный по собственным признакам человека; неоднозначно — `None`."""
    ev = await _evidence(session, lead)
    match = []
    if ev.identity_ids:
        match.append(ClientContact.telegram_identity_id.in_(ev.identity_ids))
    if ev.phones:
        match.append(ClientContact.phone_e164.in_(ev.phones))
    if ev.emails:
        match.append(func.lower(ClientContact.email).in_(ev.emails))
    if not match:
        return None
    ids = (
        await session.scalars(
            select(ClientContact.id).where(ClientContact.client_id == client_id, or_(*match))
        )
    ).all()
    return int(ids[0]) if len(ids) == 1 else None


async def apply(session: AsyncSession, lead: Lead, actor: Actor | None = None) -> Outcome:
    """Применяет правило к лиду в транзакции вызывающего. Уведомлений человеку снаружи нет."""
    who = actor or Actor.system()
    if not _applicable(lead):
        return Outcome.NONE
    client = await company_of_lead(session, lead)
    if client is None:
        return Outcome.NONE
    before = _view(lead)
    if lead.client_id is None:
        lead.client_id = client.id
    if not lead.company_name:
        lead.company_name = client.name
    owner = await session.get(User, client.owner_user_id) if client.owner_user_id else None
    if owner is None or not owner.is_active:
        return await _finish(session, lead, who, before, Outcome.MARKED, ())
    if MARK_KEY in (lead.qualification or {}) and lead.assigned_user_id == owner.id:
        return Outcome.UNCHANGED
    lead.assigned_user_id = owner.id
    if lead.owner_mode == "paused":  # запрос с сайта: бота в чате нет, ведёт ответственный
        lead.owner_mode = "human"
    moment = datetime.now(UTC)
    lead.qualification = {
        **(lead.qualification or {}),
        MARK_KEY: {
            "client_id": client.id,
            "user_id": owner.id,
            "contact_id": await _matched_contact(session, lead, client.id),
            "at": moment.isoformat(),
        },
    }
    stage_from = lead.stage
    if lead.stage == Stage.NEW:
        lead.stage = Stage.ENGAGED.value
        session.add(
            StageTransition(
                lead_id=lead.id,
                from_stage=stage_from,
                to_stage=lead.stage,
                source="system",
                actor_user_id=None,
                reason="known company contact",
            )
        )
    return await _finish(session, lead, who, before, Outcome.ASSIGNED, ("assigned_user", "client"))


def _view(lead: Lead) -> dict[str, Any]:
    return {
        "stage": lead.stage,
        "owner_mode": lead.owner_mode,
        "assigned_user_id": lead.assigned_user_id,
        "client_id": lead.client_id,
    }


async def _finish(
    session: AsyncSession,
    lead: Lead,
    who: Actor,
    before: dict[str, Any],
    outcome: Outcome,
    changed: tuple[str, ...],
) -> Outcome:
    after = _view(lead)
    if after == before:
        return Outcome.UNCHANGED
    await audit.record(
        session, who, "lead.known_contact", "lead", lead.id, before=before, after=after
    )
    await events.publish(session, "lead.updated", lead_id=lead.id, owner_mode=lead.owner_mode)
    if changed:
        await bus_events.lead_updated(session, lead, who, changed)
        if before["stage"] != after["stage"]:
            await bus_events.lead_stage_changed(
                session,
                lead,
                from_stage=before["stage"],
                to_stage=after["stage"],
                actor=who,
                source="system",
                reason="known company contact",
            )
    logger.info("lead_known_contact", lead_id=lead.id, outcome=outcome.value)
    return outcome
