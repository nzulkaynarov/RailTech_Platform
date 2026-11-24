# ruff: noqa: F811 — fixtures imported from the follow-up test are redefined as arguments
"""Delivery reports of our own letters (owner 2026-11-24): never a lead or a «Входящие» item.

Web request with a mailbox address → auto-reply goes out → the mail server returns a DSN to the
shared mailbox → the poll links it to our letter, marks the address, the card shows it and the next
auto-reply to that address is not sent. Samples are real-world DSNs (`tests/fixtures/bounces`).
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.bounce import parse_bounce
from app.domain.inbound_folders import FolderSetting
from app.integrations.imap import FetchedMessage
from app.models.email import EmailLog, EmailUndeliverable
from app.models.inbound_mail import InboundMail
from app.models.leads import Lead
from app.models.notices import ClientNotice
from app.services import bounces
from app.services.inbound_mail_ingest import InboundMailIngest
from app.services.settings import SettingsService
from tests.integration.test_web_lead_followup import (  # noqa: F401 — fixtures
    Harness,
    client,
    connect_smtp,
    harness,
    manager_headers,
    notice_of,
    post_web,
)

pytestmark = pytest.mark.integration

SAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "bounces"
OUT_ID = "out-1.20261124@railtech.test"


def delay_for(message_id: str) -> bytes:
    raw = (SAMPLES / "delay_4xx.eml").read_text(encoding="utf-8")
    return raw.replace("20261124125000.7.7@railtech.example", message_id).encode("utf-8")


def yandex_for(address: str, message_id: str = OUT_ID) -> bytes:
    raw = (SAMPLES / "yandex_domain_not_found.eml").read_text(encoding="utf-8")
    raw = raw.replace("em@tvorog.io", address)
    raw = raw.replace("20261124101500.1234.5678@railtech.example", message_id)
    return raw.encode("utf-8")


def ingest(sessions: async_sessionmaker[AsyncSession]) -> InboundMailIngest:
    # A bounce never reaches the mailbox secrets, the IMAP client or the attachment storage.
    unused: Any = None
    return InboundMailIngest(sessions, unused, SettingsService(sessions), unused, unused, "bucket")


async def poll(sessions: async_sessionmaker[AsyncSession], raw: bytes, uid: int = 1) -> int | None:
    return await ingest(sessions).store(FolderSetting("INBOX"), 1, FetchedMessage(uid, raw))


def with_message_ids(harness: Harness) -> None:
    """The transport reports the Message-ID the way the real one does."""
    sent = harness.transport.sent

    async def send(connection: Any, to: str, subject: str, body: str, **_: Any) -> str:
        sent.append((to, subject, body))
        return f"out-{len(sent)}.20261124@railtech.test"

    cast(Any, harness.transport).send = send


async def count(sessions: async_sessionmaker[AsyncSession], model: Any) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_bounce_is_not_a_lead_marks_the_address_and_stops_the_next_auto_reply(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    with_message_ids(harness)
    await connect_smtp(sessions, client)
    lead_id = post_web(client, live_settings)  # email a@rail.uz, phone 90 123 45 67
    notice = await notice_of(sessions, lead_id)
    assert harness.notices is not None
    assert await harness.notices.deliver(notice.id) == "queued"
    await harness.deliver_mail()
    assert len(harness.transport.sent) == 1
    async with sessions() as session:
        sent_row = (await session.scalars(select(EmailLog))).one()
    assert sent_row.message_id == OUT_ID

    # The server returns the report: not a lead, not an inbound-mail item.
    leads_before = await count(sessions, Lead)
    assert await poll(sessions, yandex_for("a@rail.uz")) is None
    assert await count(sessions, Lead) == leads_before
    assert await count(sessions, InboundMail) == 0

    async with sessions() as session:
        row = (await session.scalars(select(EmailLog))).one()
        assert row.bounce_reason == "domain_not_found"
        assert row.bounce_status == "5.4.4"
        assert row.bounced_at is not None
        mark = (await session.scalars(select(EmailUndeliverable))).one()
        assert (mark.email, mark.kind, mark.reports) == ("a@rail.uz", "permanent", 1)

    # The card and the mail log tell staff.
    auth = await manager_headers(sessions, client)
    card = client.get(f"/api/v1/leads/{lead_id}", headers=auth).json()
    assert card["email_undeliverable"]["kind"] == "permanent"
    assert card["email_undeliverable"]["reason"] == "domain_not_found"

    # The same report read twice (reset mailbox position) counts once.
    await poll(sessions, yandex_for("a@rail.uz"), uid=2)
    async with sessions() as session:
        assert (await session.scalars(select(EmailUndeliverable))).one().reports == 1

    # A repeated request from the same contact: no second auto-reply to the dead address.
    second = post_web(client, live_settings)
    assert second == lead_id
    async with sessions() as session:
        latest = (
            await session.scalars(select(ClientNotice).order_by(ClientNotice.id.desc()).limit(1))
        ).one()
    assert latest.id != notice.id
    assert await harness.notices.deliver(latest.id) == "skipped"
    await harness.deliver_mail()
    assert len(harness.transport.sent) == 1, "no letter went to the undeliverable address"
    async with sessions() as session:
        done = await session.get(ClientNotice, latest.id)
        assert done is not None
        assert (done.status, done.error) == ("skipped", "address_undeliverable")


async def test_mail_log_shows_the_bounce(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    harness: Harness,
) -> None:
    with_message_ids(harness)
    await connect_smtp(sessions, client)
    lead_id = post_web(client, live_settings)
    notice = await notice_of(sessions, lead_id)
    assert harness.notices is not None
    await harness.notices.deliver(notice.id)
    await harness.deliver_mail()
    await poll(sessions, yandex_for("a@rail.uz"))
    admin_auth = await manager_headers(sessions, client)
    items = client.get("/api/v1/integrations/smtp/log", headers=admin_auth)
    if items.status_code == 403:  # the log is for the administrator
        from tests.integration.crm_helpers import login, make_user

        admin, password = await make_user(sessions, "log-admin@railtech.uz", ["admin"])
        items = client.get(
            "/api/v1/integrations/smtp/log", headers=login(client, admin.email, password)
        )
    [item] = [i for i in items.json() if i["to_email"] == "a@rail.uz"]
    assert item["bounce"]["reason"] == "domain_not_found"


async def test_forged_report_for_a_stranger_address_marks_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Only an address we really mailed can be marked: a made-up bounce changes nothing."""
    assert await poll(sessions, yandex_for("victim@client.example", "made-up@evil.test")) is None
    assert await count(sessions, EmailUndeliverable) == 0


async def test_soft_bounce_counts_and_blocks_only_from_the_limit(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        for n in range(bounces.SOFT_LIMIT):
            session.add(
                EmailLog(
                    to_email="sales@partner.example",
                    subject="s",
                    template="t",
                    lang="ru",
                    status="sent",
                    sent_at=now,
                    message_id=f"20261124125000.7.{n}@railtech.example",
                )
            )
    for n in range(bounces.SOFT_LIMIT):
        report = parse_bounce(delay_for(f"20261124125000.7.{n}@railtech.example"))
        assert report is not None
        assert report.severity == "soft"
        async with sessions.begin() as session:
            await bounces.apply(session, report, f"delay-{n}@mx.test")
        async with sessions() as session:
            blocked = await bounces.is_blocked(session, "sales@partner.example")
        assert blocked is (n + 1 >= bounces.SOFT_LIMIT)
    async with sessions() as session:
        mark = (await session.scalars(select(EmailUndeliverable))).one()
        assert (mark.kind, mark.reports) == ("soft", bounces.SOFT_LIMIT)


async def test_editing_the_address_lifts_the_block(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        session.add(
            EmailUndeliverable(
                email="old@tvorog.io",
                kind="permanent",
                reason="domain_not_found",
                first_at=now,
                last_at=now,
            )
        )
    async with sessions() as session:
        assert await bounces.is_blocked(session, "Old@Tvorog.io")
        assert not await bounces.is_blocked(session, "new@tvorog.io")
