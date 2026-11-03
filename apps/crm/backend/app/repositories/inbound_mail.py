"""Запросы входящей почты (W18A-P2): письма очереди, состояние папки, связка с клиентом и лидом."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clients import Client, ClientContact
from app.models.email import EmailLog
from app.models.inbound_mail import InboundMail, InboundMailbox, InboundMailImport
from app.models.leads import Lead

REF_KIND = "inbound_mail"


async def exists(session: AsyncSession, message_id: str) -> bool:
    stmt = select(InboundMail.id).where(InboundMail.message_id == message_id)
    return (await session.scalars(stmt.limit(1))).first() is not None


async def insert_new(session: AsyncSession, values: dict[str, object]) -> int | None:
    """Новая строка; тот же `message_id` уже есть (гонка двух опросов) — None, без ошибки."""
    stmt = (
        insert(InboundMail)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[InboundMail.message_id])
        .returning(InboundMail.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get(
    session: AsyncSession, mail_id: int, *, for_update: bool = False
) -> InboundMail | None:
    stmt = select(InboundMail).where(InboundMail.id == mail_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).first()


def _filter(status: str, history: bool | None) -> list[ColumnElement[bool]]:
    where = [InboundMail.status == status]
    if history is not None:
        where.append(InboundMail.from_history.is_(history))
    return where


async def page(
    session: AsyncSession, status: str, limit: int, history: bool | None = None
) -> Sequence[InboundMail]:
    """Письма статуса; новые сверху по дате письма (у загруженных из истории дата приёма — сегодня);
    дата из будущего (часы отправителя) не выше даты приёма — `LEAST` пропускает NULL."""
    stmt = (
        select(InboundMail)
        .where(*_filter(status, history))
        .order_by(
            func.least(InboundMail.sent_at, InboundMail.received_at).desc(),
            InboundMail.id.desc(),
        )
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()


async def count(session: AsyncSession, status: str, history: bool | None = None) -> int:
    stmt = select(func.count()).select_from(InboundMail).where(*_filter(status, history))
    return int((await session.execute(stmt)).scalar_one())


async def promote_from_spam(session: AsyncSession, message_id: str, mailbox: str) -> int | None:
    """Письмо, которое было в «Спаме», нашлось в обычной папке (его переложили): в очередь."""
    stmt = (
        update(InboundMail)
        .where(InboundMail.message_id == message_id, InboundMail.status == "spam")
        .values(status="new", mailbox=mailbox)
        .returning(InboundMail.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def mailboxes(session: AsyncSession, names: Sequence[str]) -> list[InboundMailbox]:
    stmt = select(InboundMailbox).where(InboundMailbox.mailbox.in_(list(names)))
    return list((await session.scalars(stmt)).all())


async def last_import(session: AsyncSession) -> InboundMailImport | None:
    stmt = select(InboundMailImport).order_by(InboundMailImport.id.desc()).limit(1)
    return (await session.scalars(stmt)).first()


async def running_import(session: AsyncSession, fresh_after: datetime) -> InboundMailImport | None:
    """Идущая загрузка, обновлявшаяся после `fresh_after` (зависшая после сбоя воркера — нет)."""
    stmt = (
        select(InboundMailImport)
        .where(InboundMailImport.status == "running", InboundMailImport.updated_at >= fresh_after)
        .order_by(InboundMailImport.id.desc())
        .limit(1)
        .with_for_update()
    )
    return (await session.scalars(stmt)).first()


async def mailbox(
    session: AsyncSession, name: str, *, for_update: bool = False
) -> InboundMailbox | None:
    stmt = select(InboundMailbox).where(InboundMailbox.mailbox == name)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).first()


async def lock_mailbox(session: AsyncSession, name: str, host: str) -> InboundMailbox:
    """Строка состояния папки под блокировкой; нет — создаётся (два опроса сразу — без гонки)."""
    await session.execute(
        insert(InboundMailbox)
        .values(mailbox=name, host=host, fetched_total=0)
        .on_conflict_do_nothing(index_elements=[InboundMailbox.mailbox])
    )
    found = await mailbox(session, name, for_update=True)
    if found is None:  # только что вставлена или уже была — есть всегда
        raise LookupError(name)
    return found


async def last_mailbox(session: AsyncSession) -> InboundMailbox | None:
    stmt = select(InboundMailbox).order_by(InboundMailbox.last_poll_at.desc().nulls_last())
    return (await session.scalars(stmt.limit(1))).first()


async def client_by_email(session: AsyncSession, email: str) -> tuple[int, str] | None:
    stmt = (
        select(Client.id, Client.name)
        .join(ClientContact, ClientContact.client_id == Client.id)
        .where(func.lower(ClientContact.email) == email, Client.is_active.is_(True))
        .order_by(Client.id)
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    return (int(row[0]), str(row[1])) if row is not None else None


async def client_by_inns(session: AsyncSession, inns: Sequence[str]) -> tuple[int, str] | None:
    if not inns:
        return None
    stmt = (
        select(Client.id, Client.name)
        .where(Client.inn.in_(list(inns)), Client.is_active.is_(True))
        .order_by(Client.id)
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    return (int(row[0]), str(row[1])) if row is not None else None


async def names(
    session: AsyncSession, client_ids: Sequence[int], lead_ids: Sequence[int]
) -> tuple[dict[int, str], dict[int, str]]:
    clients: dict[int, str] = {}
    leads: dict[int, str] = {}
    if client_ids:
        rows = await session.execute(
            select(Client.id, Client.name).where(Client.id.in_(list(client_ids)))
        )
        clients = {int(i): str(n) for i, n in rows.all()}
    if lead_ids:
        rows = await session.execute(
            select(Lead.id, Lead.display_name).where(Lead.id.in_(list(lead_ids)))
        )
        leads = {int(i): str(n or "") for i, n in rows.all()}
    return clients, leads


async def replies(session: AsyncSession, mail_id: int) -> Sequence[EmailLog]:
    stmt = (
        select(EmailLog)
        .where(EmailLog.ref_kind == REF_KIND, EmailLog.ref_id == str(mail_id))
        .order_by(EmailLog.created_at, EmailLog.id)
    )
    return (await session.scalars(stmt)).all()
