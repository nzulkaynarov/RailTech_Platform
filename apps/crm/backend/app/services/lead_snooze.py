"""«Отложить» и «Вернуть из отложенных» (SPEC §10.1, Q-018): правила вынесены из
`services/leads.py` (≤ 400 строк)."""

from datetime import datetime, timedelta
from typing import Final

from app.domain.errors import ForbiddenError, Reason, ValidationFailedError
from app.domain.escalation import reset_sla
from app.domain.lead_access import may_snooze
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.schemas.settings import AppSettings
from app.security.principal import Principal
from app.services.channel_card import needs_sla

MAX_SNOOZE: Final = timedelta(days=7)


def check_until(until: datetime, now: datetime) -> None:
    if until <= now or until - now > MAX_SNOOZE:
        raise ValidationFailedError(
            "snooze must be within 7 days", reason=Reason.SNOOZE_RANGE, field="until"
        )


def check_snoozer(lead: Lead, who: Principal) -> None:
    """Отложить и вернуть может тот, кто вправе откладывать (Q-018)."""
    if not may_snooze(
        assigned_user_id=lead.assigned_user_id, user_id=who.user_id, is_admin=who.is_admin
    ):
        raise ForbiddenError(
            "only the lead owner or an admin can snooze", reason=Reason.NOT_LEAD_OWNER
        )


def reopen(escalation: Escalation, lead: Lead | None, now: datetime, cfg: AppSettings) -> None:
    """Отложенная передача снова открыта; срок реакции отсчитывается заново (аудит P1-8)."""
    escalation.status, escalation.snoozed_until = "open", None
    if needs_sla(escalation.priority):
        timer = reset_sla(now, cfg.escalation.sla_minutes, cfg.business_hours.domain())
        escalation.sla_due_at, escalation.sla_notified_at = timer.sla_due_at, timer.sla_notified_at
    if lead is not None:
        lead.snoozed_until = None
