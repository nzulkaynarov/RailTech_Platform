"""Действия команды над лидом (SPEC §10.1, §8.2, ADR-0012).

Права на действие проверяет RBAC (`require`), здесь — объектные правила:
владелец лида, состояние эскалации, допустимость перехода стадии. Каждое
действие — одна транзакция с записью в `audit_log` и событием для SSE.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
    Reason,
    ValidationFailedError,
)
from app.domain.lead_access import may_acknowledge, may_snooze
from app.domain.stage_machine import stage_before_handoff
from app.domain.stages import OwnerMode, Stage, TransitionSource
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.repositories import events
from app.repositories import leads as repo
from app.repositories import users as users_repo
from app.schemas.settings import Language
from app.security import audit
from app.security.principal import Principal
from app.services import deals, lead_parts, stages
from app.services.escalation import OPEN_STATUSES
from app.services.lead_messenger import LeadMessenger
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

EscalationChanged = Callable[[int], Awaitable[None]]
LeadAssigned = Callable[[int, int], Awaitable[None]]  # (lead_id, user_id) → канал и личка
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
        on_assigned: LeadAssigned | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._messenger = messenger
        self._on_escalation_changed = on_escalation_changed
        self._on_assigned = on_assigned

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
                raise ConflictError(
                    "lead is already taken",
                    reason=Reason.LEAD_TAKEN,
                    assigned_user_id=lead.assigned_user_id,
                    assigned_user_name=await _user_name(session, lead.assigned_user_id),
                )
            before = lead_parts.snapshot(lead)
            # Из «Отказа» — снова в работу (ADR-0015); клиента и «Сделку» берут без смены стадии.
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
                raise ConflictError(
                    "lead is already handled by the bot", reason=Reason.ALREADY_WITH_BOT
                )
            before = lead_parts.snapshot(lead)
            if lead.stage in (Stage.HANDOFF, Stage.IN_PROGRESS):
                target = stage_before_handoff(await lead_parts.history(session, lead_id))
                await _move(session, lead, target, who, "returned to bot")
            lead.owner_mode = OwnerMode.BOT.value
            lead.assigned_user_id = None
            lead.snoozed_until = None
            lead.consecutive_fallbacks = 0
            lead.bot_turns_without_progress = 0
            if note and note.strip():
                lead_parts.add_note(session, lead, who, note, visible_to_bot=True)
            escalation = await _active_escalation(session, lead_id)
            if escalation is not None:
                escalation.status, escalation.resolved_at = "returned", datetime.now(UTC)
                escalation.outcome = "returned_to_bot"
            changed = await self._finish(
                session, who, lead, "lead.return_to_bot", before, escalation
            )
            language = LANGUAGES.get(lead.language, "ru")
        cfg = await self._settings.get()
        text = cfg.texts.returned_to_bot.get(language, company=cfg.company.name)
        await self._messenger.send(lead_id, text, {"notice": "returned_to_bot"})
        await self._notify(changed)

    async def new_deal(self, who: Principal, lead_id: int) -> None:
        """Повторная продажа клиенту: customer → in_progress, ведёт тот, кто открыл (ADR-0015)."""
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            if lead.stage != Stage.CUSTOMER:
                raise InvalidTransitionError("new deal is opened for a customer only")
            before = lead_parts.snapshot(lead)
            await _move(session, lead, Stage.IN_PROGRESS, who, "new deal")
            lead.owner_mode = OwnerMode.HUMAN.value
            lead.assigned_user_id = who.user_id
            await deals.ensure_open_deal(session, lead, actor=who)  # Q-021
            changed = await self._finish(session, who, lead, "lead.new_deal", before, None)
        await self._notify(changed)

    async def assign(self, who: Principal, lead_id: int, user_id: int) -> None:
        """Передать лида коллеге: стадия не меняется, лид узнаёт имя нового менеджера."""
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            if lead.owner_mode != OwnerMode.HUMAN:
                raise ConflictError(
                    "take the lead before handing it over", reason=Reason.TAKE_FIRST
                )
            _require_owner(lead, who)
            target = await users_repo.get(session, user_id)
            roles = await users_repo.roles_of(session, user_id) if target else []
            if target is None or not target.is_active or not {"manager", "admin"} & set(roles):
                raise ValidationFailedError(
                    "choose an active manager",
                    reason=Reason.INACTIVE_COLLEAGUE,
                    field="user_id",
                )
            before = lead_parts.snapshot(lead)
            lead.assigned_user_id = user_id
            changed = await self._finish(session, who, lead, "lead.assign", before, None)
            language = LANGUAGES.get(lead.language, "ru")
            name = target.full_name.split()[0] if target.full_name.strip() else target.full_name
        text = cfg.texts.manager_joined.get(language, manager=name)
        await self._messenger.send(lead_id, text, {"notice": "manager_joined"})
        await self._notify(changed)
        if self._on_assigned is not None:
            try:
                await self._on_assigned(lead_id, user_id)
            except Exception as exc:  # noqa: BLE001 — очередь недоступна; передача уже сохранена
                logger.warning("lead_assign_notify_failed", lead_id=lead_id, error=repr(exc))

    async def snooze(self, who: Principal, lead_id: int, until: datetime) -> None:
        now = datetime.now(UTC)
        if until <= now or until - now > MAX_SNOOZE:
            raise ValidationFailedError(
                "snooze must be within 7 days", reason=Reason.SNOOZE_RANGE, field="until"
            )
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            if not may_snooze(
                assigned_user_id=lead.assigned_user_id, user_id=who.user_id, is_admin=who.is_admin
            ):
                raise ForbiddenError(
                    "only the lead owner or an admin can snooze", reason=Reason.NOT_LEAD_OWNER
                )
            escalation = await _active_escalation(session, lead_id)
            if escalation is None or escalation.status not in OPEN_STATUSES:
                raise ConflictError(
                    "no open escalation to snooze",
                    reason=Reason.NO_OPEN_HANDOFF,
                )
            before = lead_parts.snapshot(lead)
            escalation.status, escalation.snoozed_until = "snoozed", until
            lead.snoozed_until = until
            changed = await self._finish(session, who, lead, "lead.snooze", before, escalation)
        await self._notify(changed)

    async def acknowledge(self, who: Principal, lead_id: int) -> None:
        """«Принято к сведению» (аудит P0-1): закрыть информационную передачу лида у бота,
        не забирая его и не меняя стадию. Права — как у «Забрать» (RBAC)."""
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            escalation = await _active_escalation(session, lead_id)
            if escalation is None or not may_acknowledge(
                priority=escalation.priority, status=escalation.status
            ):
                raise ConflictError(
                    "no open info escalation to acknowledge", reason=Reason.NO_OPEN_HANDOFF
                )
            before = lead_parts.snapshot(lead)
            escalation.status, escalation.resolved_at = "closed", datetime.now(UTC)
            escalation.outcome, escalation.snoozed_until = "acknowledged", None
            escalation.taken_by_user_id = who.user_id
            lead.snoozed_until = None
            changed = await self._finish(session, who, lead, "lead.acknowledge", before, escalation)
        await self._notify(changed)

    async def close(
        self,
        who: Principal,
        lead_id: int,
        outcome: Outcome,
        reason: str | None,
        *,
        amount: Decimal | None = None,
        lost_reason: str | None = None,
    ) -> None:
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            _require_owner(lead, who)
            if lead.stage != Stage.IN_PROGRESS:
                raise InvalidTransitionError(
                    "take the lead before closing it", reason=Reason.TAKE_FIRST
                )
            before = lead_parts.snapshot(lead)
            target = Stage.WON if outcome == "won" else Stage.LOST
            await _move(session, lead, target, who, reason or outcome)
            # Сделка лида закрывается в той же транзакции (ADR-0019).
            await deals.apply_lead_outcome(
                session, who, lead, outcome, cfg.deals, reason_code=lost_reason, amount=amount
            )
            # Итог зафиксирован — диалог снова ведёт бот, иначе лид пишет в тишину.
            # Владелец остаётся: он ответственный за клиента после сделки.
            lead.owner_mode = OwnerMode.BOT.value
            lead.snoozed_until = None
            lead.consecutive_fallbacks = 0
            lead.bot_turns_without_progress = 0
            if lead.client_id is not None:
                # Повторная сделка клиента: итог записан, лид снова клиент (ADR-0015).
                await stages.transition(
                    session, lead, Stage.CUSTOMER, TransitionSource.SYSTEM, reason="repeat deal"
                )
            escalation = await _active_escalation(session, lead_id)
            if escalation is not None:
                escalation.status, escalation.resolved_at = "closed", datetime.now(UTC)
                escalation.outcome = outcome
            if reason and reason.strip():
                lead_parts.add_note(session, lead, who, reason, visible_to_bot=False)
            changed = await self._finish(
                session, who, lead, f"lead.close_{outcome}", before, escalation
            )
        await self._notify(changed)

    async def add_note(self, who: Principal, lead_id: int, text: str, visible_to_bot: bool) -> int:
        if not text.strip():
            raise ValidationFailedError("note is empty", field="text")
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            note = lead_parts.add_note(session, lead, who, text, visible_to_bot=visible_to_bot)
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
                raise ConflictError("take the lead before replying", reason=Reason.TAKE_FIRST)
            _require_owner(lead, who)
            if lead.consent_given_at is None:
                # Без согласия на обработку данных писать лиду нельзя (аудит P2).
                raise ConflictError("lead has not given consent", reason=Reason.NO_CONSENT)
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
            session,
            who.actor,
            action,
            "lead",
            lead.id,
            before=before,
            after=lead_parts.snapshot(lead),
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


async def _user_name(session: AsyncSession, user_id: int | None) -> str | None:
    """Имя того, кто ведёт лида, — для «Лида уже забрал …» (имена команды видны всем ролям)."""
    user = await users_repo.get(session, user_id) if user_id is not None else None
    return user.full_name if user is not None else None


def _require_owner(lead: Lead, who: Principal) -> None:
    if who.is_admin:
        return
    if lead.owner_mode == OwnerMode.HUMAN and lead.assigned_user_id != who.user_id:
        raise ForbiddenError(
            "only the lead owner or an admin can do this", reason=Reason.NOT_LEAD_OWNER
        )


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
