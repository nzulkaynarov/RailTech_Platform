"""«Почта · Отправленные» (план 2.8; исследование 2026-11-11 «Документы и шаблоны» §5, MAIL-1).

Журнал писем ансамбля (`email_log`: CRM и запросы ERP, EDS по шине) с поиском: сотрудник видит
письма, отправленные по его запросу, администратор (`integrations:read`) — все. Текст письма —
только по отдельному запросу и с записью в аудит (`mail.body_view`); тело хранится зашифрованным.
"""

import base64
import json
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, and_, or_, select

from app.api.deps import ContainerDep, PrincipalDep, get_rbac
from app.domain.errors import NotFoundError, ValidationFailedError
from app.models.auth import User
from app.models.email import EmailLog
from app.security import audit
from app.security.principal import Principal
from app.security.rbac import Rbac
from app.security.secrets_store import SecretCipher, SecretsKeyError

router = APIRouter(prefix="/api/v1/mail/sent", tags=["mail"])

RbacDep = Annotated[Rbac, Depends(get_rbac)]
Status = Literal["queued", "sent", "failed", "skipped_no_smtp"]


class SentMailItem(BaseModel):
    id: int
    to_email: str
    subject: str
    status: Status
    error: str | None
    lang: str
    source: Literal["crm", "erp", "eds"]
    purpose: str | None
    ref_kind: str | None
    ref_id: str | None
    attachments: int
    requested_by: int | None
    requested_by_name: str | None
    created_at: datetime
    sent_at: datetime | None


class SentMailPage(BaseModel):
    items: list[SentMailItem]
    next_cursor: str | None


class SentMailBody(BaseModel):
    """Текст письма по запросу: `null` — тело уже удалено по сроку хранения или ключ сменился."""

    id: int
    text: str | None
    attachments: list[str]


def _sees_all(rbac: Rbac, who: Principal) -> bool:
    return rbac.allowed(who.rbac_roles, "integrations", "read", who.platform_role_ids)


def _scope(stmt: Select[Any], rbac: Rbac, who: Principal) -> Select[Any]:
    return stmt if _sees_all(rbac, who) else stmt.where(EmailLog.requested_by == who.user_id)


def _cursor(raw: str | None) -> tuple[datetime, int] | None:
    if not raw:
        return None
    try:
        at, row_id = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        return datetime.fromisoformat(at), int(row_id)
    except (ValueError, TypeError) as exc:
        raise ValidationFailedError("bad cursor", fields=["cursor"]) from exc


def _encode(row: EmailLog) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([row.created_at.isoformat(), row.id]).encode()
    ).decode()


@router.get("", response_model=SentMailPage)
async def list_sent(
    who: PrincipalDep,
    rbac: RbacDep,
    container: ContainerDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status: Status | None = None,
    ref_kind: Annotated[str | None, Query(max_length=32)] = None,
    ref_id: Annotated[str | None, Query(max_length=64)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SentMailPage:
    """Письма новыми первыми: поиск по адресату и теме, статус, объект (`ref_kind` + `ref_id`),
    период; курсор."""
    stmt = _scope(select(EmailLog), rbac, who)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(EmailLog.to_email.ilike(needle), EmailLog.subject.ilike(needle)))
    if status:
        stmt = stmt.where(EmailLog.status == status)
    if ref_kind:
        stmt = stmt.where(EmailLog.ref_kind == ref_kind)
        if ref_id:
            stmt = stmt.where(EmailLog.ref_id == ref_id)
    if since:
        stmt = stmt.where(EmailLog.created_at >= since)
    if until:
        stmt = stmt.where(EmailLog.created_at < until)
    after = _cursor(cursor)
    if after:
        stmt = stmt.where(
            or_(
                EmailLog.created_at < after[0],
                and_(EmailLog.created_at == after[0], EmailLog.id < after[1]),
            )
        )
    stmt = stmt.order_by(EmailLog.created_at.desc(), EmailLog.id.desc()).limit(limit + 1)
    async with container.session_factory() as session:
        rows: list[EmailLog] = list((await session.scalars(stmt)).all())
        page, more = rows[:limit], len(rows) > limit
        ids = {r.requested_by for r in page if r.requested_by is not None}
        names: dict[int, str] = {}
        if ids:
            found = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
            names = {int(user_id): str(name) for user_id, name in found.all()}
    return SentMailPage(
        items=[
            SentMailItem(
                id=r.id,
                to_email=r.to_email,
                subject=r.subject,
                status=r.status,
                error=r.error,
                lang=r.lang,
                source=r.source,
                purpose=r.purpose,
                ref_kind=r.ref_kind,
                ref_id=r.ref_id,
                attachments=len(r.attachments or []),
                requested_by=r.requested_by,
                requested_by_name=names.get(r.requested_by) if r.requested_by is not None else None,
                created_at=r.created_at,
                sent_at=r.sent_at,
            )
            for r in page
        ],
        next_cursor=_encode(page[-1]) if more and page else None,
    )


@router.get("/{email_id}", response_model=SentMailBody)
async def read_sent(
    email_id: int, who: PrincipalDep, rbac: RbacDep, container: ContainerDep
) -> SentMailBody:
    """Текст письма: тот же круг, что видит строку; каждый просмотр — в аудит."""
    async with container.session_factory() as session, session.begin():
        row = (
            await session.scalars(
                _scope(select(EmailLog).where(EmailLog.id == email_id), rbac, who)
            )
        ).first()
        if row is None:
            raise NotFoundError("email not found")
        cipher = SecretCipher.optional(container.settings.secrets_key.get_secret_value())
        text: str | None = None
        if cipher is not None and row.body_ciphertext is not None:
            try:
                text = cipher.decrypt(row.body_ciphertext)
            except SecretsKeyError:
                text = None
        await audit.record(session, who.actor, "mail.body_view", "email_log", str(row.id))
    return SentMailBody(
        id=row.id,
        text=text,
        attachments=[str(a.get("filename") or "") for a in (row.attachments or [])],
    )
