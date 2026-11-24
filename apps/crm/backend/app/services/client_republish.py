"""One-off republication of `client.updated` snapshots to the bus (W21, PR #763 follow-up).

ERP stores the client's CRM owner from the `client.updated` snapshot, so clients that existed
before that change get the owner only on their next edit. This command publishes the current
snapshot of every client (or one) through the outbox, with the very builder the normal update
path uses (`app.bus.events.client_updated` -> `snapshots.client_snapshot`).

Consent: `client.updated` has no consent gate on any path (create, edit, handoff publish it
unconditionally; consent is checked only when a lead is handed over to ERP), so every client row
is republished, exactly as the normal path would publish an update for it.

Idempotent for consumers: the client row is not changed (`updated_at` stays); ERP applies a
snapshot of the same moment for the fields it did not store before (the CRM owner, СЦ-9) and skips
older ones, so a repeat only gives a new event id.
"""

from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.domain.lead_sources import normalize_phone_e164
from app.models.clients import Client, ClientContact
from app.security.audit import Actor

logger = structlog.get_logger(__name__)

BATCH_SIZE = 50


@dataclass(frozen=True)
class RepublishResult:
    clients: int  # clients in the selection
    published: int  # outbox rows written (0 on dry-run)
    contacts: int = 0  # contacts in the selection (republish_handed_over_contacts)
    phones_to_fix: int = 0  # stored phones that normalise to another value
    phones_unparseable: int = 0  # stored phones that cannot be normalised (not republished)


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


def _phone_state(raw: str | None) -> tuple[str | None, bool]:
    """(E.164 form of the stored phone, whether it cannot be normalised); empty is fine."""
    if raw is None or not raw.strip():
        return None, False
    value = normalize_phone_e164(raw)
    return value, value is None


async def republish_contacts_of_client(
    session: AsyncSession, client_id: int, actor: Actor
) -> tuple[int, int]:
    """Publish `contact.updated` for the contacts of the client; returns (published, skipped).

    Used right after a hand-over to ERP: ERP skips `contact.created` while the client is not handed
    over, so the position and the Telegram username would never arrive. The contact row is not
    changed (`updated_at` stays): ERP applies the snapshot once and skips an equal one on repeat.
    A contact whose stored phone cannot be normalised is skipped: the schema takes E.164 or null,
    and `null` would blank the phone the hand-over gave ERP — a snapshot never sends a worse value.
    """
    ids = list(
        await session.scalars(
            select(ClientContact.id)
            .where(ClientContact.client_id == client_id)
            .order_by(ClientContact.id)
        )
    )
    published = skipped = 0
    for contact_id in ids:
        contact = await session.get(ClientContact, contact_id)
        if contact is None:
            continue
        if _phone_state(contact.phone_e164)[1]:
            skipped += 1
            logger.warning("contact_republish_skipped_phone", contact_id=contact_id)
            continue
        await bus_events.contact_updated(session, contact, actor)
        published += 1
    return published, skipped


async def republish_handed_over_contacts(
    sessions: async_sessionmaker[AsyncSession],
    *,
    client_id: int | None = None,
    dry_run: bool = True,
    batch_size: int = BATCH_SIZE,
) -> RepublishResult:
    """One-off: `contact.updated` for contacts of clients already handed over to ERP (G2 of the
    people audit 2026-11-24). Before publishing, stored phones are normalised to E.164 with the one
    CRM normaliser (rows with a raw phone like «90 123 45 67» would otherwise go out wrong).
    `dry_run` only counts: `phones_to_fix` rows would change, `phones_unparseable` cannot be
    normalised (left as is, their contacts are not republished)."""
    stmt = select(Client.id).where(Client.erp_company_id.is_not(None)).order_by(Client.id)
    if client_id is not None:
        stmt = stmt.where(Client.id == client_id)
    async with sessions() as session:
        ids = list(await session.scalars(stmt))
        rows = (
            (
                await session.execute(
                    select(ClientContact.phone_e164).where(ClientContact.client_id.in_(ids))
                )
            ).all()
            if ids
            else []
        )
    states = [(row[0], *_phone_state(row[0])) for row in rows]
    to_fix = sum(1 for raw, value, bad in states if not bad and value != raw and raw is not None)
    unparseable = sum(1 for _, _, bad in states if bad)
    result = RepublishResult(
        clients=len(ids),
        published=0,
        contacts=len(rows),
        phones_to_fix=to_fix,
        phones_unparseable=unparseable,
    )
    if dry_run:
        return result
    actor = Actor.system()
    published = 0
    for start in range(0, len(ids), batch_size):
        async with sessions() as session, session.begin():
            batch = ids[start : start + batch_size]
            for contact in await session.scalars(
                select(ClientContact).where(ClientContact.client_id.in_(batch))
            ):
                value, bad = _phone_state(contact.phone_e164)
                if not bad and contact.phone_e164 is not None and value != contact.phone_e164:
                    contact.phone_e164 = value
            await session.flush()
            for cid in batch:
                done, _ = await republish_contacts_of_client(session, cid, actor)
                published += done
    logger.info("handed_over_contacts_republished", clients=len(ids), published=published)
    return RepublishResult(
        clients=len(ids),
        published=published,
        contacts=len(rows),
        phones_to_fix=to_fix,
        phones_unparseable=unparseable,
    )
