"""Действия команды над лидом (SPEC §10.1, §8.2, ADR-0012).

Права на действие проверяет RBAC (`require`), здесь — объектные правила:
владелец лида, состояние эскалации, допустимость перехода стадии. Каждое
действие — одна транзакция с записью в `audit_log` и событием для SSE.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.domain.backoffice import BackofficeMode, may_close_locally
from app.domain.errors import (
    ConflictError,
    DomainError,
    ForbiddenError,
    InvalidTransitionError,
    NotFoundError,
    Reason,
    ValidationFailedError,
)
from app.domain.lead_access import may_acknowledge
from app.domain.stage_machine import stage_before_handoff
from app.domain.stages import OwnerMode, Stage, TransitionSource
from app.domain.text import staff_name
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.repositories import crm as crm_repo
from app.repositories import events
from app.repositories import leads as repo
from app.repositories import users as users_repo
from app.schemas.settings import Language
from app.security import audit
from app.security.principal import Principal
from app.services import deals, lead_parts, lead_snooze, stages
from app.services.escalation import OPEN_STATUSES
from app.services.lead_messenger import LeadMessenger
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

EscalationChanged = Callable[[int], Awaitable[None]]
LeadAssigned = Callable[[int, int], Awaitable[None]]  # (lead_id, user_id) → канал и личка
# Telegram-чаты, чьё меню бота надо обновить сразу (после коммита, через очередь).
ChatsChanged = Callable[[list[int]], Awaitable[None]]
BackofficeModeProvider = Callable[[], Awaitable[BackofficeMode]]
Outcome = Literal["won", "lost"]
_active_escalation = lead_parts.active_escalation
LANGUAGES: Final[dict[str, Language]] = {"ru": "ru", "uz": "uz", "en": "en"}


class DeliveryError(DomainError):
    code = "delivery_failed"


@dataclass(frozen=True, slots=True)
class _Changed:
    escalation_id: int | None = None
    chats: tuple[int, ...] = ()


class LeadService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        messenger: LeadMessenger,
        on_escalation_changed: EscalationChanged | None = None,
        on_assigned: LeadAssigned | None = None,
        on_escalation_reopened: EscalationChanged | None = None,
        on_chats_changed: ChatsChanged | None = None,
        backoffice_mode: BackofficeModeProvider | None = None,
    ) -> None:
        self._sessions = sessions
        # Режим жизненного цикла (ADR-0022): без провайдера — `local`, как до ансамбля.
        self._backoffice_mode = backoffice_mode
        self._settings = settings
        self._messenger = messenger
        self._on_escalation_changed = on_escalation_changed
        self._on_assigned = on_assigned
        self._on_escalation_reopened = on_escalation_reopened or on_escalation_changed
        self._on_chats_changed = on_chats_changed

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
                    assigned_user_name=await lead_parts.user_name(session, lead.assigned_user_id),
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
        text = cfg.texts.manager_joined.get(language, manager=staff_name(who.full_name, language))
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
            name = staff_name(target.full_name, language)
        text = cfg.texts.manager_joined.get(language, manager=name)
        await self._messenger.send(lead_id, text, {"notice": "manager_joined"})
        await self._notify(changed)
        if self._on_assigned is not None:
            try:
                await self._on_assigned(lead_id, user_id)
            except Exception as exc:  # noqa: BLE001 — очередь недоступна; передача уже сохранена
                logger.warning("lead_assign_notify_failed", lead_id=lead_id, error=repr(exc))

    async def snooze(self, who: Principal, lead_id: int, until: datetime) -> None:
        lead_snooze.check_until(until, datetime.now(UTC))
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            lead_snooze.check_snoozer(lead, who)
            escalation = await _active_escalation(session, lead_id)
            if escalation is None or escalation.status not in OPEN_STATUSES:
                raise ConflictError("no open escalation to snooze", reason=Reason.NO_OPEN_HANDOFF)
            before = lead_parts.snapshot(lead)
            escalation.status, escalation.snoozed_until = "snoozed", until
            lead.snoozed_until = until
            changed = await self._finish(session, who, lead, "lead.snooze", before, escalation)
        await self._notify(changed)

    async def unsnooze(self, who: Principal, lead_id: int) -> None:
        """«Вернуть из отложенных»: передача снова открыта, SLA заново; права — как у «Отложить»."""
        cfg = await self._settings.get()
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            lead_snooze.check_snoozer(lead, who)
            escalation = await _active_escalation(session, lead_id)
            if escalation is None or escalation.status != "snoozed":
                raise ConflictError("no snoozed escalation", reason=Reason.NO_OPEN_HANDOFF)
            before = lead_parts.snapshot(lead)
            lead_snooze.reopen(escalation, lead, datetime.now(UTC), cfg)
            changed = await self._finish(session, who, lead, "lead.unsnooze", before, escalation)
        await self._notify(changed, reopened=True)

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
        mode = await self._backoffice_mode() if self._backoffice_mode else BackofficeMode.LOCAL
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            _require_owner(lead, who)
            if not may_close_locally(mode, outcome):
                # ADR-0022: с коннектором ERP выигрыш решает бэк-офис (`deal.won`), не кнопка CRM.
                raise ConflictError(
                    "won is decided by the back office", reason=Reason.WON_DECIDED_BY_ERP
                )
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

    async def reply(
        self, who: Principal, lead_id: int, text: str, *, client_message_id: str | None = None
    ) -> int:
        body = text.strip()
        if not body or len(body) > 4000:
            raise ValidationFailedError("message must be 1..4000 characters", field="text")
        if client_message_id is not None:  # «Повторить» после обрыва: ответ уже ушёл — не дублируем
            async with self._sessions() as session:
                done = await crm_repo.reply_by_key(session, lead_id, client_message_id)
            if done is not None and (done.meta or {}).get("delivery") != "sending":
                return done.id
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            if lead.owner_mode != OwnerMode.HUMAN:
                raise ConflictError("take the lead before replying", reason=Reason.TAKE_FIRST)
            _require_owner(lead, who)
            if lead.consent_given_at is None:
                # Без согласия на обработку данных писать лиду нельзя (аудит P2).
                raise ConflictError("lead has not given consent", reason=Reason.NO_CONSENT)
            await audit.record(session, who.actor, "lead.reply", "lead", lead_id)
        if client_message_id is not None:
            message_id = await self._messenger.send_once(
                lead_id, body, client_message_id, sent_by_user_id=who.user_id
            )
        else:
            message_id = await self._messenger.send(
                lead_id, body, {"mode": "manager"}, role="manager", sent_by_user_id=who.user_id
            )
        if message_id is None:
            raise DeliveryError("telegram delivery failed")
        # «Лид отвечен» — только после доставки (B-013): при отказе Telegram он «ждёт ответа».
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            lead.last_human_msg_at = datetime.now(UTC)
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
        if before.get("assigned_user_id") != lead.assigned_user_id:
            await bus_events.lead_updated(session, lead, who.actor, ["assigned_user"])
        if escalation is not None:
            await events.publish(
                session,
                "escalation.updated",
                lead_id=lead.id,
                escalation_id=escalation.id,
                status=escalation.status,
            )
        logger.info(action.replace(".", "_"), lead_id=lead.id, user_id=who.user_id)
        # Меню бота зависит от режима (`domain/bot_menu.menu_variant`): сменился — обновить сразу.
        menu = before.get("owner_mode") != lead.owner_mode
        chats = tuple(await repo.chats_of_lead(session, lead.id)) if menu else ()
        return _Changed(escalation.id if escalation is not None else None, chats)

    async def _notify(self, changed: _Changed, *, reopened: bool = False) -> None:
        """Пост в канале; `reopened` — ещё и проверка SLA в новый срок (как у новой передачи)."""
        await notify_chats(self._on_chats_changed, list(changed.chats))
        hook = self._on_escalation_reopened if reopened else self._on_escalation_changed
        if changed.escalation_id is not None and hook is not None:
            try:
                await hook(changed.escalation_id)
            except Exception as exc:  # noqa: BLE001 — очередь недоступна; пост обновит следующий sync
                logger.warning(
                    "escalation_notify_failed",
                    escalation_id=changed.escalation_id,
                    error=type(exc).__name__,
                )


async def notify_chats(hook: ChatsChanged | None, chats: list[int]) -> None:
    """После коммита: меню чатов в очередь; недоступная очередь не отменяет действие CRM
    (меню всё равно обновится со следующим сообщением лида — `bot/status.py`)."""
    if not chats or hook is None:
        return
    try:
        await hook(chats)
    except Exception as exc:  # noqa: BLE001 — действие уже сохранено
        logger.warning("chat_menu_enqueue_failed", chats=len(chats), error=type(exc).__name__)


async def _lead(session: AsyncSession, lead_id: int) -> Lead:
    lead = await repo.get_lead(session, lead_id, for_update=True)
    if lead is None or lead.erased_at is not None:
        raise NotFoundError("lead not found")
    return lead


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
