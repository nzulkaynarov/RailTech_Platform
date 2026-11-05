"""Реестр полномочий подписи: выдать, изменить, отозвать, приложить файл основания, список и журнал (ADR-0024 п. 1, 8).

* Выдаёт и ведёт реестр держатель права `signing.manage` (код каталога ролей, ADR-0012); у каждого действия строка
  журнала (`signing_authority_events`) в той же транзакции.
* Полномочие не удаляется: отзыв (с причиной) гасит его, строка остаётся в истории. Изменить можно действующее или
  истёкшее (продлить срок), но не отозванное — для отозванного выдают новое.
* Виды документов — открытый справочник `signing-kinds` (данные администратора); неизвестный вид — 422.
* Файл основания (скан доверенности, приказа) — в хранилище EDS, приватно: скачивает держатель `signing.manage`
  (`GET …/basis-file`); замена добавляет версию, прежние остаются.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import conflict, invalid_fields, not_found
from app.models import Employee, FileVersion, Letterhead, SigningAuthority, SigningAuthorityEvent, StoredFile
from app.schemas.common import PersonRef
from app.schemas.signing import (
    EXPIRING_DAYS,
    AuthorityStatus,
    SigningAuthorityDetail,
    SigningAuthorityIn,
    SigningAuthorityList,
    SigningAuthorityPatch,
    SigningRevoked,
    SigningSetupHint,
    StatusFilter,
)
from app.schemas.signing import SigningAuthority as AuthorityOut
from app.schemas.signing import SigningAuthorityEvent as EventOut
from app.services import dictionaries, files, signing_rules
from app.services.people import Directory, load_directory
from app.services.storage import ObjectStorage

KINDS = "signing-kinds"
LIST_LIMIT = 1000
_REQUIRED = ("kinds", "basis", "valid_from")


def today() -> date:
    return clock.company_date(clock.now())


def status_of(row: SigningAuthority, day: date) -> AuthorityStatus:
    """Состояние полномочия на `day`: отозвано, ещё не началось, срок вышел, скоро окончится или действует."""
    if row.revoked_at is not None:
        return "revoked"
    if day < row.valid_from:
        return "scheduled"
    if row.valid_to is not None:
        if day > row.valid_to:
            return "expired"
        if (row.valid_to - day).days <= EXPIRING_DAYS:
            return "expiring"
    return "active"


def _terms(row: SigningAuthority) -> signing_rules.Terms:
    return signing_rules.Terms(
        kinds=tuple(row.kinds),
        basis=row.basis,
        basis_number=row.basis_number,
        basis_date=row.basis_date,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        limit_amount=row.limit_amount,
        limit_currency=row.limit_currency,
        vakolat_url=row.vakolat_url,
    )


def _check(row: SigningAuthority) -> None:
    problems = signing_rules.check(_terms(row))
    if problems:
        raise invalid_fields("Проверьте полномочие.", **problems)


async def _check_kinds(session: AsyncSession, kinds: list[str], *, keep: list[str] | None = None) -> None:
    """Каждый вид — действующее значение справочника; уже записанный в полномочии (`keep`) остаётся, даже если скрыт."""
    unknown = [k for k in kinds if k not in (keep or []) and await dictionaries.find(session, KINDS, k) is None]
    if unknown:
        raise invalid_fields("Такого вида документа нет в справочнике.", kinds=f"unknown_kind: {', '.join(unknown)}")


async def _require_active_employee(session: AsyncSession, crm_user_id: int) -> None:
    found = await session.execute(
        select(Employee.crm_user_id).where(Employee.crm_user_id == crm_user_id, Employee.is_active.is_(True))
    )
    if found.scalar_one_or_none() is None:
        raise invalid_fields("Сотрудник не найден или отключён.", crm_user_id="not_active_employee")


def _snapshot(row: SigningAuthority) -> dict[str, Any]:
    return {
        "kinds": list(row.kinds),
        "limit_amount": None if row.limit_amount is None else f"{row.limit_amount:.2f}",
        "limit_currency": row.limit_currency,
        "basis": row.basis,
        "basis_number": row.basis_number,
        "basis_date": row.basis_date.isoformat() if row.basis_date else None,
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "vakolat_url": row.vakolat_url,
        "note": row.note,
    }


def _event(
    authority_id: uuid.UUID,
    action: str,
    by: int | None,
    *,
    comment: str | None = None,
    details: dict[str, Any] | None = None,
) -> SigningAuthorityEvent:
    return SigningAuthorityEvent(
        authority_id=authority_id,
        at=clock.now(),
        action=action,
        by_crm_user_id=by,
        comment=comment,
        details=details or {},
    )


async def create(session: AsyncSession, actor_id: int, body: SigningAuthorityIn) -> SigningAuthorityDetail:
    await _require_active_employee(session, body.crm_user_id)
    await _check_kinds(session, body.kinds)
    now = clock.now()
    row = SigningAuthority(
        id=uuid.uuid4(),
        crm_user_id=body.crm_user_id,
        kinds=list(body.kinds),
        limit_amount=None if body.limit_amount is None else Decimal(body.limit_amount),
        limit_currency=body.limit_currency,
        basis=body.basis,
        basis_number=body.basis_number or None,
        basis_date=body.basis_date,
        vakolat_url=body.vakolat_url or None,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        note=body.note or None,
        created_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    _check(row)
    session.add(row)
    await session.flush()
    session.add(_event(row.id, "issued", actor_id, details={"after": _snapshot(row), "holder": body.crm_user_id}))
    await session.flush()
    return await detail(session, row.id)


async def _locked(session: AsyncSession, authority_id: uuid.UUID) -> SigningAuthority:
    stmt = select(SigningAuthority).where(SigningAuthority.id == authority_id).with_for_update()
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise not_found("Полномочие не найдено.")
    return row


def _not_revoked(row: SigningAuthority) -> None:
    if row.revoked_at is not None:
        raise conflict("revoked", "Полномочие отозвано: изменить его нельзя, выдайте новое.")


def _clean(value: Any) -> Any:
    """Пустая строка в необязательном текстовом поле — то же, что «не задано»."""
    return (value.strip() or None) if isinstance(value, str) else value


async def update(
    session: AsyncSession, actor_id: int, authority_id: uuid.UUID, patch: SigningAuthorityPatch
) -> SigningAuthorityDetail:
    row = await _locked(session, authority_id)
    _not_revoked(row)
    before = _snapshot(row)
    sent = patch.model_fields_set
    nulls = [name for name in _REQUIRED if name in sent and getattr(patch, name) is None]
    if nulls:
        raise invalid_fields("Поле нельзя очистить.", **dict.fromkeys(nulls, "required"))
    if "kinds" in sent and patch.kinds is not None:
        await _check_kinds(session, patch.kinds, keep=list(row.kinds))
        row.kinds = patch.kinds
    for name in (
        "basis",
        "basis_number",
        "basis_date",
        "valid_from",
        "valid_to",
        "vakolat_url",
        "note",
        "limit_currency",
    ):
        if name in sent:
            setattr(row, name, _clean(getattr(patch, name)))
    if "limit_amount" in sent:
        row.limit_amount = None if patch.limit_amount is None else Decimal(patch.limit_amount)
    _check(row)
    after = _snapshot(row)
    changed = {name: [before[name], after[name]] for name in after if before[name] != after[name]}
    if not changed:
        return await detail(session, authority_id)
    if "valid_to" in changed:
        row.expiry_notified_for = None  # срок перенесён — напоминание об окончании снова возможно
    row.updated_at = clock.now()
    session.add(_event(row.id, "updated", actor_id, details={"changed": changed}))
    await session.flush()
    return await detail(session, authority_id)


async def revoke(session: AsyncSession, actor_id: int, authority_id: uuid.UUID, reason: str) -> SigningAuthorityDetail:
    row = await _locked(session, authority_id)
    _not_revoked(row)
    now = clock.now()
    row.revoked_at, row.revoked_by, row.revoke_reason, row.updated_at = now, actor_id, reason, now
    session.add(_event(row.id, "revoked", actor_id, comment=reason))
    await session.flush()
    return await detail(session, authority_id)


# --- файл основания --------------------------------------------------------------------------------------------------


async def set_file(
    session: AsyncSession, storage: ObjectStorage, actor_id: int, authority_id: uuid.UUID, item: files.Upload
) -> SigningAuthorityDetail:
    """Скан основания: первый — новый файл, следующий — новая версия того же файла (прежние остаются в хранилище)."""
    row = await _locked(session, authority_id)
    _not_revoked(row)
    name = files.clean_name(item.name)
    content_type = files.resolve_content_type(item.content_type, name)
    files.check_content(content_type, item.data)
    now = clock.now()
    if row.file_id is None:
        stored = StoredFile(id=uuid.uuid4(), created_by=actor_id, created_at=now)
        session.add(stored)
        await session.flush()
        row.file_id, number = stored.id, 1
    else:
        last = await session.execute(select(func.max(FileVersion.version)).where(FileVersion.file_id == row.file_id))
        number = int(last.scalar_one()) + 1
    key = f"files/{row.file_id}/v{number}"
    session.add(
        FileVersion(
            file_id=row.file_id,
            version=number,
            name=name,
            content_type=content_type,
            size=len(item.data),
            sha256=files.digest(item.data),
            s3_key=key,
            uploaded_by=actor_id,
            uploaded_at=now,
        )
    )
    await session.flush()
    await storage.put(key, item.data, content_type)
    row.updated_at = now
    session.add(_event(row.id, "file_replaced", actor_id, details={"name": name, "version": number}))
    await session.flush()
    return await detail(session, authority_id)


async def file_version(session: AsyncSession, authority_id: uuid.UUID, version: int | None) -> FileVersion:
    row = (
        await session.execute(select(SigningAuthority).where(SigningAuthority.id == authority_id))
    ).scalar_one_or_none()
    if row is None or row.file_id is None:
        raise not_found("Файл основания не приложен.")
    return await files.get_version(session, row.file_id, version)


# --- чтение ----------------------------------------------------------------------------------------------------------


async def _present(session: AsyncSession, rows: list[SigningAuthority], day: date) -> list[AuthorityOut]:
    people: dict[int, Employee] = {}
    ids = {r.crm_user_id for r in rows}
    if ids:
        found = await session.execute(select(Employee).where(Employee.crm_user_id.in_(ids)))
        people = {e.crm_user_id: e for e in found.scalars()}
    directory = await load_directory(session, [x for r in rows for x in (r.created_by, r.revoked_by, r.crm_user_id)])
    versions = await _latest_versions(session, [r.file_id for r in rows if r.file_id is not None])
    items: list[AuthorityOut] = []
    for row in rows:
        holder = people.get(row.crm_user_id)
        version = versions.get(row.file_id) if row.file_id is not None else None
        items.append(
            AuthorityOut(
                id=row.id,
                holder=directory.person(row.crm_user_id),
                holder_position=holder.position if holder else None,
                holder_active=bool(holder and holder.is_active),
                kinds=list(row.kinds),
                limit_amount=None if row.limit_amount is None else f"{row.limit_amount:.2f}",
                limit_currency=row.limit_currency,
                basis=row.basis,
                basis_number=row.basis_number,
                basis_date=row.basis_date,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                vakolat_url=row.vakolat_url,
                note=row.note,
                file=files.to_ref(version, directory) if version else None,
                status=status_of(row, day),
                expires_in_days=_expires_in(row, day),
                revoked=_revoked(row, directory),
                created_by=directory.person(row.created_by),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return items


def _expires_in(row: SigningAuthority, day: date) -> int | None:
    if row.valid_to is None or row.revoked_at is not None or row.valid_to < day:
        return None
    return (row.valid_to - day).days


def _revoked(row: SigningAuthority, directory: Directory) -> SigningRevoked | None:
    if row.revoked_at is None or row.revoked_by is None:
        return None
    return SigningRevoked(at=row.revoked_at, by=directory.person(row.revoked_by), reason=row.revoke_reason or "")


async def _latest_versions(session: AsyncSession, file_ids: list[uuid.UUID]) -> dict[uuid.UUID, FileVersion]:
    if not file_ids:
        return {}
    latest = (
        select(FileVersion.file_id, func.max(FileVersion.version).label("v"))
        .where(FileVersion.file_id.in_(file_ids))
        .group_by(FileVersion.file_id)
        .subquery()
    )
    rows = await session.execute(
        select(FileVersion).join(
            latest, (FileVersion.file_id == latest.c.file_id) & (FileVersion.version == latest.c.v)
        )
    )
    return {v.file_id: v for v in rows.scalars()}


async def list_authorities(
    session: AsyncSession, *, status: StatusFilter = "all", crm_user_id: int | None = None, day: date | None = None
) -> SigningAuthorityList:
    day = day or today()
    stmt = select(SigningAuthority).order_by(SigningAuthority.valid_from.desc(), SigningAuthority.created_at.desc())
    if crm_user_id is not None:
        stmt = stmt.where(SigningAuthority.crm_user_id == crm_user_id)
    rows = list((await session.execute(stmt.limit(LIST_LIMIT))).scalars())
    items = await _present(session, rows, day)
    wanted = {
        "all": None,
        "active": {"active", "expiring"},
        "expiring": {"expiring"},
        "inactive": {"scheduled", "expired", "revoked"},
    }[status]
    kept = [i for i in items if wanted is None or i.status in wanted]
    kept.sort(key=lambda i: (i.holder.full_name.lower(), i.valid_from), reverse=False)
    return SigningAuthorityList(items=kept)


async def detail(session: AsyncSession, authority_id: uuid.UUID) -> SigningAuthorityDetail:
    row = (
        await session.execute(select(SigningAuthority).where(SigningAuthority.id == authority_id))
    ).scalar_one_or_none()
    if row is None:
        raise not_found("Полномочие не найдено.")
    (base,) = await _present(session, [row], today())
    events = list(
        (
            await session.execute(
                select(SigningAuthorityEvent)
                .where(SigningAuthorityEvent.authority_id == authority_id)
                .order_by(SigningAuthorityEvent.id)
            )
        ).scalars()
    )
    directory = await load_directory(session, [e.by_crm_user_id for e in events])
    journal = [
        EventOut(
            at=e.at,
            action=e.action,
            by=directory.person_or_none(e.by_crm_user_id),
            comment=e.comment,
            details=e.details,
        )
        for e in events
    ]
    return SigningAuthorityDetail(**base.model_dump(), journal=journal)


async def setup_hint(session: AsyncSession) -> SigningSetupHint:
    """Первый запуск: есть ли хоть одно полномочие, кто подписывает по уставу по бланку компании и кто это в проекции.

    Директор «известен», если подписант бланка совпадает по ФИО (без регистра и лишних пробелов) ровно с одним активным
    сотрудником; иначе человека выбирает администратор — код не угадывает."""
    exists = (await session.execute(select(func.count()).select_from(SigningAuthority))).scalar_one() > 0
    letterhead = (await session.execute(select(Letterhead))).scalar_one_or_none()
    name = (letterhead.signatory_name if letterhead else "").strip() or None
    position = (letterhead.signatory_position if letterhead else "").strip() or None
    director: PersonRef | None = None
    if name is not None:
        wanted = " ".join(name.lower().split())
        rows = (await session.execute(select(Employee).where(Employee.is_active.is_(True)))).scalars()
        matches = [e for e in rows if " ".join(e.full_name.lower().split()) == wanted]
        if len(matches) == 1:
            director = PersonRef(crm_user_id=matches[0].crm_user_id, full_name=matches[0].full_name)
    return SigningSetupHint(has_authorities=exists, signatory_name=name, signatory_position=position, director=director)
