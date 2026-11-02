"""Списки и карточка письма общего ящика (W18A-P2-3): сборка ответа из строк базы.

Список — записи (корни цепочек) вкладки с исполнителем, итогом и «не прочитано»; карточка — те же
поля плюс адресаты (сотрудники по адресу), все входящие письма записи, наши ответы из журнала
почты, журнал действий и «кому уйдёт копия». Права и состояния решает вызывающий
(`InboundMailService`).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inbound_mail_flow import eds_waiting, reply_all_copy
from app.models.inbound_mail import InboundMail
from app.repositories import inbound_mail as repo
from app.repositories import inbound_mail_views as views
from app.schemas import inbound_mail as dto
from app.services.inbound_mail_assist import view as assist_view

PREVIEW_CHARS = 200


@dataclass(slots=True)
class Names:
    clients: dict[int, str] = field(default_factory=dict)
    leads: dict[int, str] = field(default_factory=dict)
    users: dict[int, str] = field(default_factory=dict)

    def person(self, user_id: int | None) -> dto.InboundMailPerson | None:
        if user_id is None:
            return None
        return dto.InboundMailPerson(id=user_id, name=self.users.get(user_id, ""))

    def link(self, kind: str, key: int | None) -> dto.InboundMailLink | None:
        if key is None:
            return None
        ids = self.clients if kind == "client" else self.leads
        return dto.InboundMailLink(id=key, name=ids.get(key, ""))


async def load_names(
    session: AsyncSession, rows: Sequence[InboundMail], extra_users: Sequence[int] = ()
) -> Names:
    clients, leads = await repo.names(
        session,
        [r.client_id for r in rows if r.client_id is not None],
        [i for r in rows for i in (r.matched_lead_id, r.lead_id) if i is not None],
    )
    user_ids = {i for r in rows for i in (r.assignee_id, r.handled_by) if i is not None} | set(
        extra_users
    )
    return Names(clients, leads, await views.user_names(session, sorted(user_ids)))


def _result(row: InboundMail, names: Names) -> dto.InboundMailResult | None:
    if row.status != "done":
        return None
    return dto.InboundMailResult(
        outcome=row.outcome,
        by=names.person(row.handled_by),
        at=row.handled_at,
        letter_number=row.eds_letter_number,
        lead=names.link("lead", row.lead_id),
        reason=row.archive_reason,
    )


def item_fields(
    row: InboundMail,
    names: Names,
    *,
    assist_on: bool,
    unread: bool,
    messages: int,
    now: datetime,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "status": row.status,
        "from_email": row.from_email,
        "from_name": row.from_name,
        "subject": row.subject,
        "received_at": row.received_at,
        "sent_at": row.sent_at,
        "activity_at": row.activity_at,
        "preview": row.text[:PREVIEW_CHARS],
        "attachments_count": len(row.attachments or []),
        "assist": assist_view(row, assist_on),
        "client": names.link("client", row.client_id),
        "lead": names.link("lead", row.matched_lead_id),
        "from_history": row.from_history,
        "assignee": names.person(row.assignee_id),
        "assigned_at": row.assigned_at,
        "personal": row.personal,
        "thread_reply": row.thread_reply,
        "unread": unread,
        "messages_count": messages,
        "eds_waiting": eds_waiting(row.status, row.registering_at, now),
        "result": _result(row, names),
    }


async def build_page(
    session: AsyncSession,
    view: views.View,
    scope: views.Scope,
    *,
    limit: int,
    history: bool | None,
    q: str | None,
    assist_on: bool,
    now: datetime,
) -> tuple[list[dto.InboundMailItem], int, dto.InboundMailCounts]:
    found = await views.page(session, view, scope, limit=limit, history=history, q=q)
    rows = [row for row, _ in found]
    total = await views.total(session, view, scope, history=history, q=q)
    counts = await views.counts(session, scope)
    unread = await views.unread_new(session, scope)
    names = await load_names(session, rows)
    sizes = await views.message_counts(session, [r.id for r in rows])
    items = [
        dto.InboundMailItem(
            **item_fields(
                row,
                names,
                assist_on=assist_on,
                unread=is_unread,
                messages=sizes.get(row.id, 1),
                now=now,
            )
        )
        for row, is_unread in found
    ]
    return items, total, dto.InboundMailCounts(**counts, unread_new=unread)


def _files(row: InboundMail) -> list[dto.InboundMailAttachment]:
    return [
        dto.InboundMailAttachment(
            index=i, name=a["name"], content_type=a["content_type"], size=a["size"]
        )
        for i, a in enumerate(row.attachments or [])
    ]


async def _addresses(
    session: AsyncSession, row: InboundMail, mailbox: str | None
) -> tuple[list[dto.InboundMailAddress], list[dto.InboundMailAddress]]:
    emails = [*(row.to_addrs or []), *(row.cc_addrs or [])]
    staff = await views.staff_by_email(session, emails)
    names = await views.user_names(session, sorted(set(staff.values())))
    box = (mailbox or "").lower()

    def one(email: str) -> dto.InboundMailAddress:
        uid = staff.get(email.lower())
        person = dto.InboundMailPerson(id=uid, name=names.get(uid, "")) if uid else None
        return dto.InboundMailAddress(email=email, staff=person, mailbox=email.lower() == box)

    return [one(e) for e in row.to_addrs or []], [one(e) for e in row.cc_addrs or []]


async def _events(session: AsyncSession, mail_id: int, names: Names) -> list[dto.InboundMailEvent]:
    entries = await views.journal(session, mail_id)
    actors = await views.user_names(session, [e.actor_user_id for e in entries if e.actor_user_id])
    names.users.update(actors)
    out: list[dto.InboundMailEvent] = []
    for entry in entries:
        after = entry.after or {}
        detail = after.get("reason") if isinstance(after.get("reason"), str) else None
        out.append(
            dto.InboundMailEvent(
                at=entry.created_at,
                action=entry.action.removeprefix("inbound_mail."),
                actor=names.person(entry.actor_user_id),
                detail=detail,
            )
        )
    return out


async def build_card(
    session: AsyncSession,
    row: InboundMail,
    scope: views.Scope,
    *,
    assist_on: bool,
    personal_label: str,
    mailbox: str | None,
    now: datetime,
) -> dto.InboundMailOut:
    children = await views.children(session, row.id)
    replies = await repo.replies(session, row.id)
    names = await load_names(session, [row], [r.requested_by for r in replies if r.requested_by])
    to, cc = await _addresses(session, row, mailbox)
    unread = await views.is_unread(session, row, scope.user_id)
    latest = children[-1] if children else row
    messages = [
        dto.InboundMailMessage(
            id=m.id,
            from_email=m.from_email,
            from_name=m.from_name,
            at=m.sent_at or m.received_at,
            text=m.text,
            attachments=_files(m),
        )
        for m in [row, *children]
    ]
    return dto.InboundMailOut(
        **item_fields(
            row, names, assist_on=assist_on, unread=unread, messages=len(messages), now=now
        ),
        to=to,
        cc=cc,
        text=row.text,
        attachments=_files(row),
        skipped=[dto.InboundMailSkipped.model_validate(s) for s in row.skipped or []],
        too_large=row.too_large,
        inns=list(row.inns or []),
        eds_letter_id=row.eds_letter_id,
        messages=messages,
        replies=[
            dto.InboundMailReply(
                id=r.id,
                to_email=r.to_email,
                subject=r.subject,
                status=r.status,
                created_at=r.created_at,
                sent_at=r.sent_at,
                by=names.person(r.requested_by),
            )
            for r in replies
        ],
        journal=await _events(session, row.id, names),
        reply_all_copy=reply_all_copy(
            latest.to_addrs or [], latest.cc_addrs or [], mailbox, latest.from_email
        ),
        personal_label=personal_label,
    )
