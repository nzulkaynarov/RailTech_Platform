"""One-off republication of `client.updated` snapshots to the bus (W21, PR #763 follow-up).

ERP stores the client's CRM owner from the `client.updated` snapshot, so clients that existed
before that change get the owner only on their next edit. This command publishes the current
snapshot of every client (or one) through the outbox, with the very builder the normal update
path uses (`app.bus.events.client_updated` -> `snapshots.client_snapshot`).

Consent: `client.updated` has no consent gate on any path (create, edit, handoff publish it
unconditionally; consent is checked only when a lead is handed over to ERP), so every client row
is republished, exactly as the normal path would publish an update for it.

Why the row is touched first: ERP applies a client snapshot only when it is strictly newer than
the one it already applied (equal `updated_at` -> `skipped_duplicate`), so a snapshot with the
unchanged `updated_at` would do nothing for clients already handed over and not edited since. The
command therefore bumps `updated_at` (the `set_updated_at` trigger) in the same transaction and
publishes the snapshot built after it. Repeats stay idempotent by content: a snapshot replaces the
projection, only `updated_at` and the event id are new.
"""

from dataclasses import dataclass

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.models.clients import Client
from app.security.audit import Actor

logger = structlog.get_logger(__name__)

BATCH_SIZE = 50


@dataclass(frozen=True)
class RepublishResult:
    clients: int  # clients in the selection
    published: int  # outbox rows written (0 on dry-run)


async def _client_ids(session: AsyncSession, client_id: int | None) -> list[int]:
    stmt = select(Client.id).order_by(Client.id)
    if client_id is not None:
        stmt = stmt.where(Client.id == client_id)
    return list(await session.scalars(stmt))


async def republish_clients(
    sessions: async_sessionmaker[AsyncSession],
    *,
    client_id: int | None = None,
    dry_run: bool = False,
    batch_size: int = BATCH_SIZE,
) -> RepublishResult:
    """Publish `client.updated.v1` for every client (or one); `dry_run` only counts."""
    async with sessions() as session:
        ids = await _client_ids(session, client_id)
    if dry_run:
        return RepublishResult(clients=len(ids), published=0)
    actor = Actor.system()
    published = 0
    for start in range(0, len(ids), batch_size):
        async with sessions() as session, session.begin():
            for cid in ids[start : start + batch_size]:
                touched_id = await session.scalar(
                    update(Client)
                    .where(Client.id == cid)
                    .values(updated_at=func.now())
                    .returning(Client.id)
                    .execution_options(synchronize_session=False)
                )
                if touched_id is None:  # deleted between the selection and the batch
                    continue
                client = await session.get(Client, cid, populate_existing=True)
                if client is None:
                    continue
                await bus_events.client_updated(session, client, actor)
                published += 1
    logger.info("clients_republished", clients=len(ids), published=published)
    return RepublishResult(clients=len(ids), published=published)
