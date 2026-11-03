"""Письмо общего ящика как обращение: «взять в работу», вернуть, регистрация, массовый архив
(W18A-P2-3).

Один человек ведёт письмо (Help Scout «assigned to», collision detection): первое действие берёт
письмо автоматически, другому — 409 `mail_in_work_by_other` («уже в работе у …»), «Забрать себе» —
осознанный перехват с записью в журнал. Каждая функция работает в транзакции вызывающего и берёт
строку `FOR UPDATE`, поэтому двое одновременно не выполнят действие над одним письмом: второй
увидит уже изменённое состояние (тест гонки — `tests/integration/test_inbound_mail_work.py`).
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import ConflictError, NotFoundError, Reason
from app.domain.inbound_mail_flow import can_return, claim_of, eds_waiting
from app.models.inbound_mail import InboundMail
from app.repositories import inbound_mail as repo
from app.repositories import inbound_mail_views as views
from app.schemas import inbound_mail as dto
from app.security import audit
from app.security.principal import Principal
from app.services.inbound_mail_assist import record_decision


async def lock(session: AsyncSession, mail_id: int) -> InboundMail:
    """Запись списка под блокировкой; ответ цепочки отдельной записью не бывает."""
    row = await repo.get(session, mail_id, for_update=True)
    if row is None or row.thread_root_id is not None:
        raise NotFoundError("mail not found")
    return row


async def _in_work_by_other(session: AsyncSession, row: InboundMail) -> ConflictError:
    names = await views.user_names(session, [row.assignee_id] if row.assignee_id else [])
    return ConflictError(
        "mail is in work by another employee",
        reason=Reason.MAIL_IN_WORK_BY_OTHER,
        status=row.status,
        assignee_id=row.assignee_id,
        assignee_name=names.get(row.assignee_id or 0, ""),
        assigned_at=row.assigned_at.isoformat() if row.assigned_at else None,
    )


def handled(row: InboundMail) -> ConflictError:
    return ConflictError("mail is already handled", reason=Reason.MAIL_HANDLED, status=row.status)


def _assign(row: InboundMail, who: Principal, now: datetime) -> None:
    row.status = "in_work"
    row.assignee_id = who.user_id
    row.assigned_at = now
    row.thread_reply = False


async def claim(
    session: AsyncSession, row: InboundMail, who: Principal, now: datetime, *, auto: bool = True
) -> bool:
    """Взять письмо для действия: ничьё — берётся (True), своё — продолжается (False), чужое «в
    работе» или уже разобранное — 409."""
    verdict = claim_of(row.status, row.assignee_id, who.user_id)
    if verdict == "closed":
        raise handled(row)
    if verdict == "other":
        raise await _in_work_by_other(session, row)
    if verdict == "mine":
        return False
    _assign(row, who, now)
    await audit.record(
        session, who.actor, "inbound_mail.take", "inbound_mail", row.id, after={"auto": auto}
    )
    return True


def finish(row: InboundMail, outcome: str, who: Principal, now: datetime) -> None:
    """«Разобрано» с итогом: кто и когда; исполнитель остаётся в записи."""
    row.status = "done"
    row.outcome = outcome
    row.handled_by = who.user_id
    row.handled_at = now
    row.registering_at = None
    row.thread_reply = False


async def take(
    session: AsyncSession, who: Principal, mail_id: int, now: datetime, *, takeover: bool
) -> None:
    """«Взять в работу» (повтор своего — без изменений); «Забрать себе» — у того, кто ведёт."""
    row = await lock(session, mail_id)
    if takeover and row.status == "in_work" and row.assignee_id not in (None, who.user_id):
        before = row.assignee_id
        _assign(row, who, now)
        await audit.record(
            session,
            who.actor,
            "inbound_mail.takeover",
            "inbound_mail",
            row.id,
            before={"assignee_id": before},
            after={"assignee_id": who.user_id},
        )
        return
    await claim(session, row, who, now, auto=False)


async def release(session: AsyncSession, who: Principal, mail_id: int, *, full: bool) -> None:
    """«Вернуть в Новые»: своё «в работе» или разобранное архивом/ответом (запись в журнал).

    Разобранное возвращает только первая линия (`full`); исполнитель без раздела — своё «в
    работе»."""
    row = await lock(session, mail_id)
    if not can_return(row.status, row.outcome):
        raise ConflictError(
            "mail cannot be returned to the queue",
            reason=Reason.MAIL_NOT_RETURNABLE,
            status=row.status,
        )
    if row.status == "in_work" and row.assignee_id != who.user_id:
        raise await _in_work_by_other(session, row)
    if row.status == "done" and not full:
        raise handled(row)
    before = {"status": row.status, "outcome": row.outcome}
    row.status = "new"
    row.assignee_id = row.assigned_at = None
    row.outcome = row.archive_reason = None
    row.handled_by = row.handled_at = None
    row.registering_at = None
    row.thread_reply = False
    await audit.record(
        session, who.actor, "inbound_mail.release", "inbound_mail", row.id, before=before
    )


async def registration(
    session: AsyncSession, who: Principal, mail_id: int, now: datetime, state: str
) -> None:
    """ВХ создаётся в EDS (форма P8): письмо «Регистрируется» и берётся автоматически; отказ EDS —
    `cancel` возвращает «в работе». Итог «Разобрано: ВХ» ставит событие EDS
    (`accept_registered`)."""
    row = await lock(session, mail_id)
    if state == "cancel":
        if row.status == "registering" and row.assignee_id == who.user_id:
            row.status, row.registering_at = "in_work", None
            await audit.record(
                session, who.actor, "inbound_mail.register_cancel", "inbound_mail", row.id
            )
        return
    await claim(session, row, who, now)
    if row.status == "registering" and not eds_waiting(row.status, row.registering_at, now):
        # Регистрация идёт (двойное нажатие, вторая вкладка): второго ВХ не создаём. Зависшая дольше
        # `EDS_CONFIRM_MINUTES` («ждёт подтверждения») — можно повторить: EDS по источнику письма
        # вернёт прежний ВХ.
        raise ConflictError(
            "mail is already being registered", reason=Reason.MAIL_REGISTERING, status=row.status
        )
    first = row.status != "registering"
    row.status, row.registering_at = "registering", now
    if first:
        await audit.record(
            session, who.actor, "inbound_mail.register_start", "inbound_mail", row.id
        )


@dataclass(slots=True)
class BulkResult:
    archived: list[int]
    skipped: list[dto.InboundMailSkippedItem]


async def bulk_archive(
    session: AsyncSession, who: Principal, ids: list[int], reason: str, now: datetime
) -> BulkResult:
    """«В архив» нескольких писем с одной причиной (рассылки, уведомления). Чужие «в работе» и уже
    разобранные пропускаются и называются в итоге; строки берутся по возрастанию id (без взаимных
    блокировок)."""
    result = BulkResult([], [])
    clean = reason.strip()[:500]
    for mail_id in sorted(set(ids)):
        row = await repo.get(session, mail_id, for_update=True)
        if row is None or row.thread_root_id is not None:
            result.skipped.append(dto.InboundMailSkippedItem(id=mail_id, reason="missing"))
            continue
        skip = await _bulk_skip(session, row, who)
        if skip is not None:
            result.skipped.append(skip)
            continue
        finish(row, "archived", who, now)
        row.archive_reason = clean
        await record_decision(session, row, "archive", who.actor)
        await audit.record(
            session,
            who.actor,
            "inbound_mail.archive",
            "inbound_mail",
            row.id,
            after={"reason": clean, "bulk": True},
        )
        result.archived.append(mail_id)
    return result


async def _bulk_skip(
    session: AsyncSession, row: InboundMail, who: Principal
) -> dto.InboundMailSkippedItem | None:
    verdict = claim_of(row.status, row.assignee_id, who.user_id)
    if row.status == "spam":
        return None
    if verdict == "closed":
        return dto.InboundMailSkippedItem(id=row.id, reason="handled")
    if verdict == "other":
        names = await views.user_names(session, [row.assignee_id] if row.assignee_id else [])
        person = (
            dto.InboundMailPerson(id=row.assignee_id, name=names.get(row.assignee_id, ""))
            if row.assignee_id
            else None
        )
        return dto.InboundMailSkippedItem(id=row.id, reason="in_work_by_other", assignee=person)
    if row.status == "registering":
        return dto.InboundMailSkippedItem(id=row.id, reason="registering")
    return None
