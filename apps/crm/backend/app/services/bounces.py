"""Delivery reports (bounces) of our letters: link to the letter, mark the address, stop auto mail.

A bounce read from the shared mailbox (`domain/bounce.py`) is never a lead or a «Входящие» item:
`apply` links it to our outgoing letter (`email_log`), records the failure in the log row and marks
the failed address in `email_undeliverable`. Only an address we really mailed can be marked: a
forged «bounce» for a stranger's address is ignored (linked by Message-ID or by a letter sent to
that very address in the last `RECENT_DAYS`).

Permanent (5.x.x) blocks at once; soft (4.x.x) counts reports and blocks from `SOFT_LIMIT`.
Automatic mail to a blocked address is skipped (`is_blocked`); editing the address in the card
lifts the block, because the mark belongs to the address.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bounce import Bounce
from app.models.email import EmailLog, EmailUndeliverable
from app.schemas.notices import EmailUndeliverableOut
from app.security import audit

logger = structlog.get_logger(__name__)

SOFT_LIMIT: Final = 3
RECENT_DAYS: Final = 30


@dataclass(frozen=True, slots=True)
class Undeliverable:
    """What a card shows for an address: kind, plain-words reason code, when, how many reports."""

    email: str
    kind: str
    reason: str
    last_at: datetime
    reports: int

    @property
    def blocked(self) -> bool:
        return self.kind == "permanent" or self.reports >= SOFT_LIMIT


def _view(row: EmailUndeliverable) -> Undeliverable:
    return Undeliverable(row.email, row.kind, row.reason, row.last_at, row.reports)


def undeliverable_out(state: Undeliverable | None) -> EmailUndeliverableOut | None:
    """API form of a card state; `None` stays `None`."""
    if state is None:
        return None
    return EmailUndeliverableOut.model_validate(
        {
            "kind": state.kind,
            "reason": state.reason,
            "last_at": state.last_at,
            "reports": state.reports,
        }
    )


async def states(session: AsyncSession, emails: Iterable[str | None]) -> dict[str, Undeliverable]:
    """Blocked addresses among `emails` (lower-cased keys); soft ones under the limit not."""
    wanted = {e.strip().lower() for e in emails if e and e.strip()}
    if not wanted:
        return {}
    rows = await session.scalars(
        select(EmailUndeliverable).where(EmailUndeliverable.email.in_(wanted))
    )
    return {v.email: v for v in map(_view, rows) if v.blocked}


async def is_blocked(session: AsyncSession, email: str | None) -> bool:
    return bool(email) and bool(await states(session, [email]))


async def _link(session: AsyncSession, bounce: Bounce, now: datetime) -> EmailLog | None:
    """Our letter the report is about: by Message-ID, then by the report's own references, then by
    the failed recipient and a recent sent letter."""
    for message_id in (bounce.original_message_id, *bounce.reply_ids):
        if not message_id:
            continue
        row = await session.scalar(
            select(EmailLog).where(EmailLog.message_id == message_id).limit(1)
        )
        if row is not None:
            return row
    since = now - timedelta(days=RECENT_DAYS)
    for address in bounce.recipients:
        row = await session.scalar(
            select(EmailLog)
            .where(
                EmailLog.to_email == address,
                EmailLog.status == "sent",
                EmailLog.sent_at >= since,
            )
            .order_by(EmailLog.sent_at.desc())
            .limit(1)
        )
        if row is not None:
            return row
    return None


async def apply(
    session: AsyncSession, bounce: Bounce, report_id: str, now: datetime | None = None
) -> list[str]:
    """Record the report; returns the marked addresses (empty — unknown letter, repeat, nothing)."""
    moment = now or datetime.now(UTC)
    row = await _link(session, bounce, moment)
    if row is None:
        logger.info("bounce_unlinked", recipients=len(bounce.recipients))
        return []
    if row.bounce_message_id == report_id:
        return []  # the same report read again (a reset mailbox position)
    addresses = [a for a in bounce.recipients if a == row.to_email] or [row.to_email]
    row.bounced_at, row.bounce_message_id = moment, report_id[:255]
    row.bounce_status = bounce.status
    row.bounce_reason = bounce.reason
    marked = [await _mark(session, a, bounce, row.id, report_id, moment) for a in addresses]
    await audit.record(
        session,
        audit.Actor.system(),
        "email.bounce",
        "email_log",
        row.id,
        after={"kind": bounce.severity, "reason": bounce.reason, "status": bounce.status},
    )
    logger.info("bounce_applied", email_log_id=row.id, kind=bounce.severity, reason=bounce.reason)
    return marked


async def _mark(
    session: AsyncSession,
    email: str,
    bounce: Bounce,
    email_log_id: int,
    report_id: str,
    now: datetime,
) -> str:
    current = await session.scalar(
        select(EmailUndeliverable).where(EmailUndeliverable.email == email).with_for_update()
    )
    if current is None:
        session.add(
            EmailUndeliverable(
                email=email,
                kind=bounce.severity,
                reports=1,
                reason=bounce.reason,
                status_code=bounce.status,
                diagnostic=bounce.diagnostic or None,
                first_at=now,
                last_at=now,
                last_report_id=report_id[:255],
                email_log_id=email_log_id,
            )
        )
        return email
    if current.last_report_id == report_id:
        return email
    current.reports += 1
    current.last_at, current.last_report_id = now, report_id[:255]
    current.email_log_id = email_log_id
    if bounce.severity == "permanent" or current.kind == "permanent":
        current.kind = "permanent"
    current.reason, current.status_code = bounce.reason, bounce.status
    current.diagnostic = bounce.diagnostic or current.diagnostic
    return email
