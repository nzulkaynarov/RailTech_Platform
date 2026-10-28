"""Статус лида для Платформы в SQL (CRM-02): фильтр `platform_status` и «просроченные» списка лидов.

Те же правила, что `domain/client_requests.platform_status` (таблица кейсов — в unit-тестах домена,
сверка SQL с доменом — `tests/integration/test_client_requests.py`).
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, case, exists, func, or_, select

from app.domain.client_requests import ASKS_PRICE_REASON, PlatformStatus
from app.models.leads import Lead
from app.models.qualification import Escalation

_ACTIVE = ("open", "snoozed", "taken")


def _asks_price() -> ColumnElement[bool]:
    return exists(
        select(Escalation.id).where(
            Escalation.lead_id == Lead.id,
            Escalation.status.in_(_ACTIVE),
            Escalation.reason_codes.contains([ASKS_PRICE_REASON]),
        )
    )


def overdue() -> ColumnElement[bool]:
    """Открытая передача, у которой истёк SLA ответа: лид ждёт менеджера дольше нормы."""
    return exists(
        select(Escalation.id).where(
            Escalation.lead_id == Lead.id,
            Escalation.status == "open",
            Escalation.sla_due_at < func.now(),
        )
    )


def platform_status() -> ColumnElement[str]:
    status = PlatformStatus
    return case(
        (Lead.stage == "lost", status.LOST.value),
        (Lead.stage.in_(("customer", "won")), status.CLIENT.value),
        (Lead.stage == "new", status.NEW.value),
        (and_(Lead.stage.in_(("handoff", "in_progress")), _asks_price()), status.WANTS_QUOTE.value),
        (
            or_(Lead.stage == "unresponsive", and_(Lead.stage == "handoff", overdue())),
            status.NO_ANSWER.value,
        ),
        else_=status.DIALOG.value,
    )


def status_in(values: Sequence[str]) -> ColumnElement[bool]:
    return platform_status().in_(list(values))


def escalation_flags(
    escalation: Escalation | None, now: datetime | None = None
) -> tuple[bool, bool]:
    """(просит КП, SLA истёк) по активной передаче лида — для `platform_status` в ответе API."""
    if escalation is None:
        return False, False
    moment = now or datetime.now(UTC)
    asks = ASKS_PRICE_REASON in (escalation.reason_codes or [])
    late = (
        escalation.status == "open"
        and escalation.sla_due_at is not None
        and escalation.sla_due_at < moment
    )
    return asks, late
