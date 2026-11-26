"""Known-contact rule for leads that already exist (КОНТР-1а).

    python -m app reapply-known-contacts [--apply] [--lead-id N]

Without `--apply` only counts (dry-run). Applies `services/known_contact.apply` to open leads
that nobody handles yet: the company and its responsible person are set, the lead leaves «Новые».
Nothing is sent to the outside person and no personal data is printed: only lead ids and counts.
Safe to repeat.
"""

import argparse
import sys
from collections import Counter

from sqlalchemy import select

from app.container import get_container
from app.models.leads import Lead
from app.security.audit import Actor
from app.services import known_contact


async def run(args: argparse.Namespace) -> int:
    container = get_container()
    outcomes: Counter[str] = Counter()
    touched: list[int] = []
    try:
        from app.tasks.queue import queue

        # The queue is open for the command: the commit wakes the bus relay.
        async with queue.open_async():
            async with container.session_factory() as session:
                stmt = select(Lead.id).where(
                    Lead.erased_at.is_(None),
                    Lead.discarded_kind.is_(None),
                    Lead.owner_mode != "human",
                )
                if args.lead_id is not None:
                    stmt = stmt.where(Lead.id == args.lead_id)
                lead_ids = list((await session.scalars(stmt.order_by(Lead.id))).all())
            for lead_id in lead_ids:  # one short transaction per lead
                async with container.session_factory() as session:
                    tx = await session.begin()
                    lead = await session.get(Lead, lead_id, with_for_update=True)
                    if lead is None:
                        await tx.rollback()
                        continue
                    outcome = await known_contact.apply(session, lead, Actor.system())
                    outcomes[outcome.value] += 1
                    if outcome in (known_contact.Outcome.ASSIGNED, known_contact.Outcome.MARKED):
                        touched.append(lead_id)
                    if args.apply:
                        await tx.commit()
                    else:
                        await tx.rollback()
            if args.apply:
                await container.drain_bus()
    finally:
        await container.aclose()
    mode = "применено" if args.apply else "dry-run, ничего не записано"
    sys.stdout.write(
        f"Лидов известных контактов: {len(touched)} ({mode}); "
        f"по исходам: {dict(sorted(outcomes.items()))}.\n"
    )
    if touched:
        sys.stdout.write("Номера лидов: " + ", ".join(f"L-{i:04d}" for i in touched[:50]) + "\n")
    return 0
