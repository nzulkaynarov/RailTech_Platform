"""Действия команды над лидом (SPEC §10.1, §8.2, ADR-0012).

Права на действие проверяет RBAC (`require`), здесь — объектные правила:
владелец лида, состояние эскалации, допустимость перехода стадии. Каждое
действие — одна транзакция с записью в `audit_log` и событием для SSE.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import (
    ConflictError,
    DomainError,
    ForbiddenError,
    InvalidTransitionError,
    NotFoundError,
    ValidationFailedError,
)
from app.domain.stage_machine import stage_before_handoff
from app.domain.stages import OwnerMode, Stage, TransitionSource
from app.models.leads import Lead, LeadNote
from app.models.qualification import Escalation, StageTransition
from app.repositories import events
from app.repositories import leads as repo
from app.schemas.settings import Language
from app.security import audit
from app.security.principal import Principal
from app.services import stages
from app.services.escalation import OPEN_STATUSES
from app.services.lead_messenger import LeadMessenger
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

EscalationChanged = Callable[[int], Awaitable[None]]
Outcome = Literal["won", "lost"]
MAX_SNOOZE: Final = timedelta(days=7)
ACTIVE_ESCALATION = (*OPEN_STATUSES, "taken")
LANGUAGES: Final[dict[str, Language]] = {"ru": "ru", "uz": "uz", "en": "en"}


class DeliveryError(DomainError):
    code = "delivery_failed"


@dataclass(frozen=True, slots=True)
class _Changed:
    escalation_id: int | None = None


class LeadService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        messenger: LeadMessenger,
        on_escalation_changed: EscalationChanged | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._messenger = messenger
        self._on_escalation_changed = on_escalation_changed

    async def take(self, who: Principal, lead_id: int) -> None:
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            if lead.owner_mode == OwnerMode.HUMAN and lead.assigned_user_id == who.user_id:
                return
            if (
                lead.owner_mode == OwnerMode.HUMAN
                and lead.assigned_user_id is not None
                and not who.is_admin
            ):
                raise ConflictError("lead is already taken", assigned_user_id=lead.assigned_user_id)
            before = _snapshot(lead)
            if lead.stage == Stage.LOST:
                raise InvalidTransitionError("lost lead cannot be taken")
            if lead.stage not in (Stage.IN_PROGRESS, Stage.WON, Stage.CUSTOMER):
                await _move(session, lead, Stage.IN_PROGRESS, who, "taken by manager")
            lead.owner_mode = OwnerMode.HUMAN.value
            lead.assigned_user_id = who.user_id
            lead.snoozed_until = None
            escalation = await _active_escalation(session, lead_id)
            if escalation is not None:
                escalation.status = "taken"
                escalation.taken_by_user_id = who.user_id
                escalation.taken_at = datetime.now(UTC)
            changed = await self._finish(session, who, lead, "lead.take", before, escalation)
            language = LANGUAGES.get(lead.language, "ru")
        text = cfg.texts.manager_joined.get(language, manager=who.first_name or who.full_name)
        await self._messenger.send(lead_id, text, {"notice": "manager_joined"})
        await self._notify(changed)

    async def return_to_bot(self, who: Principal, lead_id: int, note: str | None) -> None:
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            _require_owner(lead, who)
            if lead.owner_mode == OwnerMode.BOT:
                raise ConflictError("lead is already handled by the bot")
            before = _snapshot(lead)
            if lead.stage in (Stage.HANDOFF, Stage.IN_PROGRESS):
                target = stage_before_handoff(await _history(session, lead_id))
                await _move(session, lead, target, who, "returned to bot")
            lead.owner_mode = OwnerMode.BOT.value
            lead.assigned_user_id = None
            lead.snoozed_until = None
            lead.consecutive_fallbacks = 0
            lead.bot_turns_without_progress = 0
            if note and note.strip():
                _add_note(session, lead, who, note, visible_to_bot=True)
            escalation = await _active_escalation(session, lead_id)
            if escalation is not None:
                escalation.status, escalation.resolved_at = "returned", datetime.now(UTC)
                escalation.outcome = "returned_to_bot"
            changed = await self._finish(
                session, who, lead, "lead.return_to_bot", before, escalation
            )
        await self._notify(changed)

    async def snooze(self, who: Principal, lead_id: int, until: datetime) -> None:
        now = datetime.now(UTC)
        if until <= now or until - now > MAX_SNOOZE:
            raise ValidationFailedError("snooze must be within 7 days", field="until")
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            escalation = await _active_escalation(session, lead_id)
            if escalation is None or escalation.status not in OPEN_STATUSES:
                raise ConflictError("no open escalation to snooze")
            before = _snapshot(lead)
            escalation.status, escalation.snoozed_until = "snoozed", until
            lead.snoozed_until = until
            changed = await self._finish(session, who, lead, "lead.snooze", before, escalation)
        await self._notify(changed)

    async def close(
        self, who: Principal, lead_id: int, outcome: Outcome, reason: str | None
    ) -> None:
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            _require_owner(lead, who)
            if lead.stage != Stage.IN_PROGRESS:
                raise InvalidTransitionError("take the lead before closing it")
            before = _snapshot(lead)
            target = Stage.WON if outcome == "won" else Stage.LOST
            await _move(session, lead, target, who, reason or outcome)
            escalation = await _active_escalation(session, lead_id)
            if escalation is not None:
                escalation.status, escalation.resolved_at = "closed", datetime.now(UTC)
                escalation.outcome = outcome
            if reason and reason.strip():
                _add_note(session, lead, who, f"{outcome}: {reason}", visible_to_bot=False)
            changed = await self._finish(
                session, who, lead, f"lead.close_{outcome}", before, escalation
            )
        await self._notify(changed)

    async def add_note(self, who: Principal, lead_id: int, text: str, visible_to_bot: bool) -> int:
        if not text.strip():
            raise ValidationFailedError("note is empty", field="text")
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            note = _add_note(session, lead, who, text, visible_to_bot=visible_to_bot)
            await session.flush()
            await audit.record(
                session,
                who.actor,
                "lead.note",
                "lead",
                lead_id,
                after={"note_id": note.id, "visible_to_bot": visible_to_bot},
            )
            await events.publish(session, "lead.updated", lead_id=lead_id)
            return note.id

    async def reply(self, who: Principal, lead_id: int, text: str) -> int:
        body = text.strip()
        if not body or len(body) > 4000:
            raise ValidationFailedError("message must be 1..4000 characters", field="text")
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            if lead.owner_mode != OwnerMode.HUMAN:
                raise ConflictError("take the lead before replying")
            _require_owner(lead, who)
            lead.last_human_msg_at = datetime.now(UTC)
            await audit.record(session, who.actor, "lead.reply", "lead", lead_id)
        message_id = await self._messenger.send(
            lead_id, body, {"mode": "manager"}, role="manager", sent_by_user_id=who.user_id
        )
        if message_id is None:
            raise DeliveryError("telegram delivery failed")
        return message_id

    async def _finish(
        self,
        session: AsyncSession,
        who: Principal,
        lead: Lead,
        action: str,
        before: dict[str, Any],
        escalation: Escalation | None,
    ) -> _Changed:
        await audit.record(
            session, who.actor, action, "lead", lead.id, before=before, after=_snapshot(lead)
        )
        await events.publish(session, "lead.updated", lead_id=lead.id, owner_mode=lead.owner_mode)
        if escalation is not None:
            await events.publish(
                session,
                "escalation.updated",
                lead_id=lead.id,
                escalation_id=escalation.id,
                status=escalation.status,
            )
        logger.info(action.replace(".", "_"), lead_id=lead.id, user_id=who.user_id)
        return _Changed(escalation.id if escalation is not None else None)

    async def _notify(self, changed: _Changed) -> None:
        if changed.escalation_id is not None and self._on_escalation_changed is not None:
            try:
                await self._on_escalation_changed(changed.escalation_id)
            except Exception as exc:  # noqa: BLE001 — очередь недоступна; пост обновит следующий sync
                logger.warning(
                    "escalation_notify_failed",
                    escalation_id=changed.escalation_id,
                    error=type(exc).__name__,
                )


async def _lead(session: AsyncSession, lead_id: int) -> Lead:
    lead = await repo.get_lead(session, lead_id, for_update=True)
    if lead is None or lead.erased_at is not None:
        raise NotFoundError("lead not found")
    return lead


def _require_owner(lead: Lead, who: Principal) -> None:
    if who.is_admin:
        return
    if lead.owner_mode == OwnerMode.HUMAN and lead.assigned_user_id != who.user_id:
        raise ForbiddenError("only the lead owner or an admin can do this")


async def _move(
    session: AsyncSession, lead: Lead, target: Stage, who: Principal, reason: str
) -> None:
    decision = await stages.transition(
        session, lead, target, TransitionSource.USER, reason=reason, actor_user_id=who.user_id
    )
    if not decision.allowed:
        raise InvalidTransitionError(decision.reason or "transition not allowed")


async def _active_escalation(session: AsyncSession, lead_id: int) -> Escalation | None:
    stmt = (
        select(Escalation)
        .where(Escalation.lead_id == lead_id, Escalation.status.in_(ACTIVE_ESCALATION))
        .order_by(Escalation.id.desc())
        .with_for_update()
    )
    return (await session.scalars(stmt)).first()


async def _history(session: AsyncSession, lead_id: int) -> list[tuple[Stage, Stage]]:
    stmt = (
        select(StageTransition.from_stage, StageTransition.to_stage)
        .where(StageTransition.lead_id == lead_id)
        .order_by(StageTransition.id)
    )
    return [(Stage(a), Stage(b)) for a, b in (await session.execute(stmt)).all()]


def _add_note(
    session: AsyncSession, lead: Lead, who: Principal, text: str, *, visible_to_bot: bool
) -> LeadNote:
    note = LeadNote(
        lead_id=lead.id,
        user_id=who.user_id,
        text=text.strip()[:4000],
        visible_to_bot=visible_to_bot,
    )
    session.add(note)
    lead.notes_count += 1
    return note


def _snapshot(lead: Lead) -> dict[str, Any]:
    return {
        "stage": lead.stage,
        "owner_mode": lead.owner_mode,
        "assigned_user_id": lead.assigned_user_id,
    }
