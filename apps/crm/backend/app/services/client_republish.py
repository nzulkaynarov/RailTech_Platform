"""One-off republication of `client.updated` snapshots to the bus (W21, PR #763 follow-up).

ERP stores the client's CRM owner from the `client.updated` snapshot, so clients that existed
before that change get the owner only on their next edit. This command publishes the current
snapshot of every client (or one) through the outbox, with the very builder the normal update
path uses (`app.bus.events.client_updated` -> `snapshots.client_snapshot`).

The normal path has no consent gate for `client.updated`: a client row only exists after the
consent check at lead handoff (`clients._require_consent`), and the snapshot carries no personal
data (name, INN, segment, owner). So there is nothing to withhold here either; a client row is
republished exactly when the normal path would publish an update for it.

Idempotent for consumers: the snapshot replaces the projection, the row is not changed
(`updated_at` stays), a repeat only gives a new event id.
"""

from dataclasses import dataclass

import structlog
from sqlalchemy import select
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
                client = await session.get(Client, cid)
                if client is None:  # deleted between the selection and the batch
                    continue
                await bus_events.client_updated(session, client, actor)
                published += 1
    logger.info("clients_republished", clients=len(ids), published=published)
    return RepublishResult(clients=len(ids), published=published)
