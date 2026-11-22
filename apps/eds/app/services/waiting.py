"""«Вы ждёте других» (ГЛ-1): что автор передал другому и ждёт, плюс «Напомнить».

Факты, из которых строки выводятся (своего статуса нет):
* письмо на подписи — `awaiting_signature` (черновик с отметкой передачи), подписант — по реестру полномочий;
* служебка, заявление, отчёт на согласовании — открытый маршрут моего документа, ждёт текущий шаг;
* поручение, которое я выдал резолюцией, — `instructions.created_by`, статус «в работе».

«Напомнить» шлёт уведомление текущему адресату (`letter_sign_requested`, `approval_reminder` — назначенному
согласующему или, на шаге «любой с правом», держателям права; `instruction_reminder`) и никогда не повторяет
`approval.requested` («круг открыт» — один раз). Пишет в журнал объекта `waiting.reminded`; повтор по тому же
объекту — не чаще раза в час (429 `RATE_LIMITED`): время прошлого напоминания берётся из журнала, отдельной таблицы нет.
"""

import datetime as dt
import uuid
from typing import Any

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import and_, any_, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import EdsError, conflict, not_found
from app.models import ApprovalRoute, ApprovalStep, Document, Employee, Instruction, JournalEntry, Letter
from app.schemas.approvals import ApprovalTemplate, RouteStatus
from app.schemas.waiting import REMIND_INTERVAL, RemindOut, WaitingItem, WaitingKind, WaitingList
from app.services import document_notices, instructions, journal, signing_resolve, signing_state
from app.services.people import load_directory

LIMIT = 50
REMINDED = "waiting.reminded"
_DOCUMENT_TEMPLATES = (ApprovalTemplate.MEMO.value, ApprovalTemplate.APPLICATION.value, ApprovalTemplate.REPORT.value)


async def _last_reminders(
    session: AsyncSession, column: Any, ids: list[uuid.UUID], *, comment: bool = False
) -> dict[str, dt.datetime]:
    """Момент последнего напоминания по объектам (ключ — id объекта или id поручения из комментария)."""
    if not ids:
        return {}
    wanted = {str(i) for i in ids}
    stmt = select(JournalEntry).where(JournalEntry.action == REMINDED)
    stmt = stmt.where(JournalEntry.letter_id.in_(ids)) if comment else stmt.where(column.in_(ids))
    out: dict[str, dt.datetime] = {}
    for row in (await session.execute(stmt.order_by(JournalEntry.id))).scalars():
        key = (row.comment or "") if comment else str(getattr(row, column.key))
        if comment or key in wanted:
            out[key] = row.at  # порядок по id: позднее перекрывает раннее
    return out


def _gate(last: dt.datetime | None) -> tuple[bool, dt.datetime | None]:
    """(можно ли напомнить сейчас, с какого момента можно)."""
    if last is None:
        return True, None
    until = last + REMIND_INTERVAL
    return (clock.now() >= until), until


async def step_recipients(session: AsyncSession, step: ApprovalStep, *, exclude: int) -> list[int]:
    """Кому уходит напоминание по текущему шагу: назначенный сотрудник, а у шага «любой с правом» — активные
    держатели права. Сам автор не получатель: напоминать себе незачем."""
    if step.assignee_crm_user_id is not None:
        return [] if step.assignee_crm_user_id == exclude else [step.assignee_crm_user_id]
    found = await session.execute(
        select(Employee.crm_user_id)
        .where(Employee.is_active.is_(True), literal(step.assignee_permission) == any_(Employee.permissions_eds))
        .order_by(Employee.crm_user_id)
    )
    return [int(i) for i in found.scalars() if int(i) != exclude]


async def _signatures(session: AsyncSession, employee: Employee, today: dt.date) -> tuple[list[WaitingItem], bool]:
    documents = list(
        (
            await session.execute(
                select(Document)
                .where(signing_state.awaiting_signature(), Document.author_crm_user_id == employee.crm_user_id)
                .order_by(Document.registration_requested_at, Document.id)
                .limit(LIMIT + 1)
            )
        )
        .scalars()
        .all()
    )
    more = len(documents) > LIMIT
    documents = documents[:LIMIT]
    last = await _last_reminders(session, JournalEntry.document_id, [d.id for d in documents])
    out: list[WaitingItem] = []
    for document in documents:
        if document.registration_requested_at is None:
            continue
        signer = await signing_resolve.letter_signer(session, document, today)
        ok, until = _gate(last.get(str(document.id)))
        out.append(
            WaitingItem(
                kind="letter_signature",
                object_id=document.id,
                number=document.number,
                title=document.subject,
                waiting_on=signer.signer if signer else None,
                waiting_label=None if signer else "Подписанта нет",
                since=document.registration_requested_at,
                due=None,
                remind_available_at=until,
                # некому напоминать: подписанта нет или подписант — сам автор
                remindable=ok and signer is not None and signer.signer.crm_user_id != employee.crm_user_id,
            )
        )
    return out, more


async def _approvals(session: AsyncSession, employee: Employee) -> tuple[list[WaitingItem], bool]:
    rows = (
        await session.execute(
            select(ApprovalRoute, Document, ApprovalStep)
            .join(Document, Document.id == ApprovalRoute.document_id)
            .join(
                ApprovalStep,
                and_(ApprovalStep.approval_id == ApprovalRoute.id, ApprovalStep.index == ApprovalRoute.current_step),
            )
            .where(
                ApprovalRoute.status == RouteStatus.OPEN.value,
                ApprovalRoute.template.in_(_DOCUMENT_TEMPLATES),
                Document.author_crm_user_id == employee.crm_user_id,
            )
            .order_by(ApprovalRoute.created_at, ApprovalRoute.id)
            .limit(LIMIT + 1)
        )
    ).all()
    more = len(rows) > LIMIT
    rows = rows[:LIMIT]
    directory = await load_directory(session, (step.assignee_crm_user_id for _, _, step in rows))
    last = await _last_reminders(session, JournalEntry.approval_id, [route.id for route, _, _ in rows])
    out: list[WaitingItem] = []
    for route, document, step in rows:
        ok, until = _gate(last.get(str(route.id)))
        recipients = await step_recipients(session, step, exclude=employee.crm_user_id)
        out.append(
            WaitingItem(
                kind="approval",
                object_id=route.id,
                number=document.number,
                title=document.subject,
                waiting_on=directory.person_or_none(step.assignee_crm_user_id),
                waiting_label=step.label if step.assignee_crm_user_id is None else None,
                since=route.created_at,
                due=None,
                remind_available_at=until,
                remindable=ok and bool(recipients),
            )
        )
    return out, more


async def _instructions(session: AsyncSession, employee: Employee) -> tuple[list[WaitingItem], bool]:
    rows = (
        await session.execute(
            select(Instruction, Letter)
            .join(Letter, Letter.id == Instruction.letter_id)
            .where(
                Instruction.created_by == employee.crm_user_id,
                Instruction.status == "in_work",
                Instruction.crm_user_id != employee.crm_user_id,
            )
            .order_by(Instruction.due, Instruction.id)
            .limit(LIMIT + 1)
        )
    ).all()
    more = len(rows) > LIMIT
    rows = rows[:LIMIT]
    directory = await load_directory(session, (i.crm_user_id for i, _ in rows))
    last = await _last_reminders(session, None, list({letter.id for _, letter in rows}), comment=True)
    out: list[WaitingItem] = []
    for instruction, letter in rows:
        ok, until = _gate(last.get(str(instruction.id)))
        out.append(
            WaitingItem(
                kind="instruction",
                object_id=instruction.id,
                number=letter.number,
                title=letter.subject,
                waiting_on=directory.person(instruction.crm_user_id),
                waiting_label=None,
                since=instruction.created_at,
                due=instruction.due,
                remind_available_at=until,
                remindable=ok,
            )
        )
    return out, more


async def list_waiting(session: AsyncSession, employee: Employee) -> WaitingList:
    today = clock.company_date(clock.now())
    signatures, more_signatures = await _signatures(session, employee, today)
    routes, more_routes = await _approvals(session, employee)
    given, more_given = await _instructions(session, employee)
    items = sorted([*signatures, *routes, *given], key=lambda item: item.since)
    return WaitingList(items=items, more=more_signatures or more_routes or more_given)


def _too_soon(until: dt.datetime) -> EdsError:
    seconds = max(1, int((until - clock.now()).total_seconds()))
    return EdsError(
        "RATE_LIMITED",
        "Напоминание уже отправлено. Повторить можно позже.",
        status_code=429,
        details={"retry_after_seconds": seconds, "available_at": until.isoformat()},
        headers={"Retry-After": str(seconds)},
    )


async def _check_gate(last: dt.datetime | None) -> None:
    ok, until = _gate(last)
    if not ok and until is not None:
        raise _too_soon(until)


async def remind(
    session: AsyncSession, bus: AsyncBus, employee: Employee, kind: WaitingKind, object_id: uuid.UUID
) -> RemindOut:
    """Повторить уведомление текущему адресату; объект должен быть «моим» (автор) и всё ещё ждать."""
    actor = employee.crm_user_id
    now = clock.now()
    if kind == "letter_signature":
        document = await session.get(Document, object_id, with_for_update=True)
        if (
            document is None
            or document.author_crm_user_id != actor
            or not signing_state.is_awaiting_signature(document)
        ):
            raise not_found()
        last = (await _last_reminders(session, JournalEntry.document_id, [document.id])).get(str(document.id))
        await _check_gate(last)
        signer = await signing_resolve.letter_signer(session, document, clock.company_date(now))
        if signer is None or signer.signer.crm_user_id == actor:
            raise conflict("no_one_to_remind", "Напоминать некому: подписант не назначен или это вы.")
        behalf = "" if not signer.acting_for else " · за " + ", ".join(p.full_name for p in signer.acting_for)
        await document_notices.publish_notice(
            session,
            bus,
            document,
            kind="letter_sign_requested",
            key=f"document:{document.id}:letter_sign_reminded:{int(now.timestamp())}",
            recipients=[signer.signer.crm_user_id],
            title="Напоминание: подпишите исходящее",
            subtitle=f"{document.subject}{behalf}",
            actor_id=actor,
        )
        await journal.record(session, REMINDED, by=actor, document_id=document.id)
    elif kind == "approval":
        found = (
            await session.execute(
                select(ApprovalRoute, Document, ApprovalStep)
                .join(Document, Document.id == ApprovalRoute.document_id)
                .join(
                    ApprovalStep,
                    and_(
                        ApprovalStep.approval_id == ApprovalRoute.id, ApprovalStep.index == ApprovalRoute.current_step
                    ),
                )
                .where(
                    ApprovalRoute.id == object_id,
                    ApprovalRoute.status == RouteStatus.OPEN.value,
                    Document.author_crm_user_id == actor,
                )
            )
        ).first()
        if found is None:
            raise not_found()
        route, document, step = found
        last = (await _last_reminders(session, JournalEntry.approval_id, [route.id])).get(str(route.id))
        await _check_gate(last)
        recipients = await step_recipients(session, step, exclude=actor)
        if not recipients:
            raise conflict("no_one_to_remind", "Напоминать некому: на шаге нет согласующего, кроме вас.")
        await document_notices.publish_notice(
            session,
            bus,
            document,
            kind="approval_reminder",
            key=f"approval:{route.id}:reminded:{int(now.timestamp())}",
            recipients=recipients,
            title="Напоминание: нужно ваше решение",
            subtitle=f"{document.number or document.subject} · {step.label}"[:200],
            actor_id=actor,
        )
        await journal.record(session, REMINDED, by=actor, approval_id=route.id, document_id=document.id)
    else:
        found_i = (
            await session.execute(
                select(Instruction, Letter)
                .join(Letter, Letter.id == Instruction.letter_id)
                .where(
                    Instruction.id == object_id,
                    Instruction.created_by == actor,
                    Instruction.status == "in_work",
                )
            )
        ).first()
        if found_i is None:
            raise not_found()
        instruction, letter = found_i
        last = (await _last_reminders(session, None, [letter.id], comment=True)).get(str(instruction.id))
        await _check_gate(last)
        await instructions.notify(
            session,
            bus,
            letter=letter,
            kind="instruction_reminder",
            key=f"instruction:{instruction.id}:reminded:{int(now.timestamp())}",
            recipients=[instruction.crm_user_id],
            title=f"Напоминание: поручение по письму {letter.number}",
            subtitle=letter.subject,
            due=instruction.due,
            actor_id=actor,
        )
        await journal.record(session, REMINDED, by=actor, letter_id=letter.id, comment=str(instruction.id))
    return RemindOut(reminded_at=now)
