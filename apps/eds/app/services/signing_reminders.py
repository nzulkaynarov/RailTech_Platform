"""Напоминание об окончании полномочия подписи (SIGN-2, ADR-0024 п. 1): за 14 дней — держателям права `signing.manage`.

Задача по расписанию (`tasks/maintenance.py`) зовёт `send_expiry_reminders`; время — аргумент, тесты без часов.
Напоминание уходит событием `signing_authority.expiring` (доставляет CRM: колокольчик и Telegram) один раз на
полномочие и дату окончания: `expiry_notified_for` хранит дату, на которую уже напомнили; перенос срока разрешает
новое напоминание.
Нет получателей (никто не держит право) — ничего не отправляется и не помечается: напомним, когда они появятся.
До 9:00 по Ташкенту не шлёт — не ночью.
"""

from datetime import date, datetime, timedelta

import structlog
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import any_, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.models import Employee, SigningAuthority, SigningAuthorityEvent
from app.models.signing import BASIS_ORDER, BASIS_POWER_OF_ATTORNEY
from app.schemas.signing import REMINDER_DAYS
from app.security.permissions import EdsPermission as P
from app.services import events

log = structlog.get_logger(__name__)

REMINDER_HOUR = 9
_BASIS_NAME = {BASIS_POWER_OF_ATTORNEY: "Доверенность", BASIS_ORDER: "Приказ"}


def days_word(count: int) -> str:
    """«1 день», «2 дня», «5 дней», «11 дней», «21 день»."""
    tail, hundred = count % 10, count % 100
    if tail == 1 and hundred != 11:
        return f"{count} день"
    if 2 <= tail <= 4 and not 12 <= hundred <= 14:
        return f"{count} дня"
    return f"{count} дней"


def _title(basis: str, holder: str, valid_to: date) -> str:
    return f"{_BASIS_NAME.get(basis, 'Полномочие')} {holder} заканчивается {valid_to:%d.%m.%Y}"[:200]


async def _recipients(session: AsyncSession) -> list[int]:
    found = await session.execute(
        select(Employee.crm_user_id)
        .where(Employee.is_active.is_(True), literal(P.SIGNING_MANAGE.value) == any_(Employee.permissions_eds))
        .order_by(Employee.crm_user_id)
    )
    return [int(i) for i in found.scalars()]


async def send_expiry_reminders(session: AsyncSession, bus: AsyncBus, *, now: datetime) -> int:
    """Напомнить о полномочиях, которые закончатся в ближайшие `REMINDER_DAYS` дней. Возвращает число напоминаний."""
    if now.astimezone(clock.COMPANY_TZ).hour < REMINDER_HOUR:
        return 0
    today = clock.company_date(now)
    rows = list(
        (
            await session.execute(
                select(SigningAuthority, Employee)
                .join(Employee, Employee.crm_user_id == SigningAuthority.crm_user_id)
                .where(
                    SigningAuthority.revoked_at.is_(None),
                    SigningAuthority.valid_to.is_not(None),
                    SigningAuthority.valid_to >= today,
                    SigningAuthority.valid_to <= today + timedelta(days=REMINDER_DAYS),
                    or_(
                        SigningAuthority.expiry_notified_for.is_(None),
                        SigningAuthority.expiry_notified_for != SigningAuthority.valid_to,
                    ),
                    Employee.is_active.is_(True),
                )
                .order_by(SigningAuthority.valid_to, SigningAuthority.id)
                .with_for_update(of=SigningAuthority, skip_locked=True)
            )
        ).all()
    )
    recipients = await _recipients(session) if rows else []
    if not recipients:
        return 0
    for authority, holder in rows:
        assert authority.valid_to is not None  # noqa: S101 — отобрано условием выше
        left = (authority.valid_to - today).days
        authority.expiry_notified_for = authority.valid_to
        await events.publish(
            bus,
            session,
            "signing_authority.expiring",
            {
                "notice_key": f"signing-authority:{authority.id}:expiring:{authority.valid_to.isoformat()}",
                "recipients": recipients,
                "title": _title(authority.basis, holder.full_name, authority.valid_to),
                "subtitle": f"Осталось {days_word(left)}. Настройки → Права подписи: продлите или выдайте новую"[:200],
                "authority": {
                    "eds_authority_id": str(authority.id),
                    "holder": {"crm_user_id": holder.crm_user_id, "full_name": holder.full_name},
                    "basis": authority.basis,
                    "basis_number": authority.basis_number,
                    "valid_to": authority.valid_to.isoformat(),
                    "days_left": left,
                },
                "actor": events.actor(None),
            },
            subject=f"signing-authority/{authority.id}",
        )
        session.add(
            SigningAuthorityEvent(
                authority_id=authority.id,
                at=clock.now(),
                action="expiry_reminded",
                by_crm_user_id=None,
                details={"valid_to": authority.valid_to.isoformat(), "days_left": left, "recipients": recipients},
            )
        )
    log.info("signing_expiry_reminders_sent", count=len(rows), day=today.isoformat())
    return len(rows)
