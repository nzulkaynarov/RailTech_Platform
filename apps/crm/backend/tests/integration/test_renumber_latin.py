"""Перенумерация копий номеров CRM в латиницу на реальной БД (СЦ-5): сухой прогон, запись."""

import argparse
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cli import renumber_latin as cli
from app.models.clients import Client
from app.models.deals import Deal
from app.models.inbound_mail import InboundMail
from app.models.integrations import ErpEventNotice
from app.models.staff_tickets import StaffNotification
from app.services import renumber_latin as svc
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration
MAPPING = {"ВХ-001/26": "IN-001/26", "ЗВ-2026-002": "PRJ-2026-002", "ОБР-0012": "TK-0012"}
NOTICE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
SENT_NOTICE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a2")


async def seed(sessions: async_sessionmaker[AsyncSession]) -> int:
    user, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    async with sessions() as session, session.begin():
        client = Client(name="ООО Ромашка")
        session.add(client)
        await session.flush()
        session.add(
            Deal(client_id=client.id, title="Заявка", erp_deal_id=7, erp_number="ЗВ-2026-002")
        )
        session.add(
            InboundMail(
                message_id="<m1@x>", mailbox="INBOX", uidvalidity=1, uid=1,
                eds_letter_number="ВХ-001/26",
            )
        )  # fmt: skip
        session.add_all(
            [
                StaffNotification(
                    user_id=user.id, kind="ticket_new", tab="system",
                    title="Новое обращение ОБР-0012", object_kind="ticket",
                    object_id="12", object_number="ОБР-0012",
                ),
                StaffNotification(
                    user_id=user.id, kind="letter", tab="system",
                    title="Письмо ВХ-001/26 зарегистрировано", object_number="ВХ-001/26",
                ),
                StaffNotification(
                    user_id=user.id, kind="letter", tab="system",
                    title="Письмо ВХ-001/260", object_number="ВХ-001/260",
                ),
            ]
        )  # fmt: skip
        session.add(
            ErpEventNotice(
                event_id=NOTICE_ID,
                items=[
                    {"kind": "staff", "user_id": user.id, "text": "Заявка ЗВ-2026-002 в работе"}
                ],
            )
        )
        session.add(
            ErpEventNotice(
                event_id=SENT_NOTICE_ID,
                items=[{"kind": "staff", "user_id": user.id, "text": "Заявка ЗВ-2026-002 принята"}],
                notified_at=datetime(2026, 11, 20, tzinfo=UTC),
            )
        )
    return user.id


async def test_dry_run_lists_changes_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await seed(sessions)
    async with sessions() as session:
        changes = await svc.plan(session, MAPPING)
    lines = [c.line() for c in changes]
    assert any(
        line.startswith("deals.erp_number") and "ЗВ-2026-002 → PRJ-2026-002" in line
        for line in lines
    )
    assert any("inbound_mail.eds_letter_number" in line and "→ IN-001/26" in line for line in lines)
    assert any(
        "staff_notifications.object_number" in line and "→ TK-0012" in line for line in lines
    )
    assert any("staff_notifications.title" in line for line in lines)
    assert any("erp_event_notices.items[0].text" in line for line in lines)
    async with sessions() as session:
        deal = (await session.scalars(select(Deal))).one()
    assert deal.erp_number == "ЗВ-2026-002"


async def test_apply_changes_only_mapped_copies_and_is_idempotent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await seed(sessions)
    async with sessions() as session, session.begin():
        assert await svc.apply(session, MAPPING) == 7

    async with sessions() as session:
        assert (await session.scalars(select(Deal.erp_number))).one() == "PRJ-2026-002"
        assert (await session.scalars(select(InboundMail.eds_letter_number))).one() == "IN-001/26"
        notes = {
            n.object_number: n.title
            for n in (await session.scalars(select(StaffNotification))).all()
        }
        notice = await session.get(ErpEventNotice, NOTICE_ID)
        sent = await session.get(ErpEventNotice, SENT_NOTICE_ID)
        assert notice is not None
        assert sent is not None
    assert notes["TK-0012"] == "Новое обращение TK-0012"
    assert notes["IN-001/26"] == "Письмо IN-001/26 зарегистрировано"
    assert notes["ВХ-001/260"] == "Письмо ВХ-001/260"  # чужой номер, не совпал целиком
    assert notice.items[0]["text"] == "Заявка PRJ-2026-002 в работе"
    assert sent.items[0]["text"] == "Заявка ЗВ-2026-002 принята"  # ушедшее сообщение — история

    async with sessions() as session:
        assert await svc.plan(session, MAPPING) == []
    async with sessions() as session, session.begin():
        assert await svc.apply(session, MAPPING) == 0


async def test_ticket_pairs_come_from_the_data_not_from_the_mapping(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Номер обращения = обозначение + id: пара `ОБР-0012 → TK-0012` в маппинге не нужна."""
    await seed(sessions)
    only_documents = {"ВХ-001/26": "IN-001/26"}
    async with sessions() as session:
        lines = [c.line() for c in await svc.plan(session, only_documents)]
    assert any(
        "staff_notifications.object_number" in line and "→ TK-0012" in line for line in lines
    )

    async with sessions() as session, session.begin():
        await svc.apply(session, only_documents)
    async with sessions() as session:
        notes = {
            n.object_id: n
            for n in (await session.scalars(select(StaffNotification))).all()
            if n.object_id
        }
        assert notes["12"].object_number == "TK-0012"
        assert notes["12"].title == "Новое обращение TK-0012"
        assert await svc.plan(session, only_documents) == []


def _cli_args(path: Path, *, apply: bool) -> argparse.Namespace:
    return argparse.Namespace(mapping=str(path), apply=apply)


async def test_cli_dry_run_prints_changes_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await seed(sessions)
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(MAPPING), encoding="utf-8")

    async def aclose() -> None:
        return None

    monkeypatch.setattr(
        cli, "get_container", lambda: SimpleNamespace(session_factory=sessions, aclose=aclose)
    )

    assert await cli.run(_cli_args(mapping, apply=False)) == 0
    out = capsys.readouterr().out
    assert "ЗВ-2026-002 → PRJ-2026-002" in out
    assert "Сухой прогон" in out
    async with sessions() as session:
        assert (await session.scalars(select(Deal.erp_number))).one() == "ЗВ-2026-002"

    assert await cli.run(_cli_args(mapping, apply=True)) == 0
    assert "Применено: 7" in capsys.readouterr().out
    async with sessions() as session:
        assert (await session.scalars(select(Deal.erp_number))).one() == "PRJ-2026-002"

    assert await cli.run(_cli_args(mapping, apply=True)) == 0
    assert "Применено: 0" in capsys.readouterr().out


async def test_cli_rejects_a_chained_mapping(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mapping = tmp_path / "chain.json"
    mapping.write_text('{"A-1": "B-1", "B-1": "C-1"}', encoding="utf-8")
    assert await cli.run(_cli_args(mapping, apply=True)) == 1
    assert "B-1" in capsys.readouterr().err
