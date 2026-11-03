"""Путь делопроизводства входящих: резолюция трёх типов, поручения, переносы, ознакомление, контроль (P8b; SPEC-v3
§3.2a п. 1–6; бенчмарк СЭД 2026-11-01 §6 — ГОСТ Р 7.0.97, Правила Росархива № 71, 1С, Directum, ELMA).

* **Путь резолюции** (`track_of`): `calc` — письмо по заявке клиента (есть `erp_request_id`, или нет вида документа
  и есть `erp_deal_id`: письма «Создать заявку» и до P8) — резолюция «расчёт по зонам»; `office` — остальное, в том
  числе письмо с видом документа, связанное с заявкой как контекст.
* **Резолюция** (`resolve_office`): «К исполнению» и «Подготовить ответ» — поручения ответственному и соисполнителям
  (любой активный сотрудник, без проверки зоны), письмо «На исполнении», на контроле; «Для сведения» — «Принято к
  сведению», поручений нет. «Ознакомить» — строки ознакомления. Проект делопроизводителя (`save_draft`) директор
  утверждает тем же вызовом.
* **Исполнение** (`complete`): отчёт (текст, файлы) или отправленный ИСХ; ИСХ «в ответ на» при отправке закрывает
  поручения «Подготовить ответ» (`close_by_outgoing` — зовёт `documents._send_letter`, то же сделает P4). Все поручения
  исполнены — письмо «Исполнено», контроль снят, уведомление автору резолюции и регистратору.
* **Перенос** (`request_extension`, `decide_extension`): запрос исполнителя, решение автора резолюции; срок срочного
  письма не продлевается (Росархив 5.14) — одобрить нельзя, только отклонить.
* **Контроль** (`send_reminders`, задача по расписанию): за рабочий день до срока и в день срока (срок больше 10 дней —
  ещё за 3 дня), после срока — «Просрочено» исполнителю и автору резолюции. Время — аргумент: тесты не зависят от часов.

Уведомления — событие `notice.requested` (колокольчик и Telegram доставляет CRM). Каждая операция — одна транзакция.
"""

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import EdsError, conflict, forbidden, forbidden_reason, invalid_fields, not_found
from app.models import Acquaintance, Document, Employee, Instruction, InstructionExtension, Letter
from app.schemas.letters import (
    AcquaintanceTask,
    EmployeeChoice,
    EmployeeList,
    ExtensionDecision,
    ExtensionDecisionIn,
    ExtensionRequestIn,
    ExtensionTask,
    InstructionCompleteIn,
    InstructionTask,
    LetterStatus,
    LetterTaskLetter,
    LetterTasks,
    LetterTrack,
    OfficeResolutionIn,
    ResolutionDraftIn,
    ResolutionKind,
)
from app.security.permissions import EdsPermission as P
from app.services import access, events, files, journal
from app.services.people import active_ids, load_directory

log = structlog.get_logger(__name__)

IN_WORK = "in_work"
EXECUTED = "executed"
# Подсказка срока (бенчмарк §6.4): «срочно» — 3 дня, обычный — 10 дней от регистрации.
URGENT_DAYS, NORMAL_DAYS = 3, 10
# Срок длиннее этого (в днях от выдачи поручения) — ещё напоминание за 3 дня.
LONG_TERM_DAYS = 10
TASKS_LIMIT = 100
# Напоминания уходят в рабочее время компании (не ночью).
REMINDER_HOUR = 9


# --- рабочие дни и подсказка срока -------------------------------------------------------------------------------


def is_workday(day: date) -> bool:
    """Рабочий день — пн–пт. Праздничного календаря на пилоте нет (SPEC-v3 §3.2a)."""
    return day.weekday() < 5


def next_workday(day: date) -> date:
    """Тот же день, если рабочий, иначе ближайший следующий (последний день срока на выходном — Росархив 5.7)."""
    while not is_workday(day):
        day += timedelta(days=1)
    return day


def prev_workday(day: date) -> date:
    """Ближайший рабочий день строго раньше `day`."""
    day -= timedelta(days=1)
    while not is_workday(day):
        day -= timedelta(days=1)
    return day


def track_of(letter: Letter) -> LetterTrack:
    """Путь резолюции письма — правило SPEC-v3 §3.2a (эту же формулу повторяет BFF для старого EDS)."""
    if letter.erp_request_id is not None or (letter.doc_kind is None and letter.erp_deal_id is not None):
        return LetterTrack.CALC
    return LetterTrack.OFFICE


def suggested_due(letter: Letter, today: date, kind_days: int | None = None) -> date | None:
    """Подсказка срока резолюции пути `office`: срок по документу минус рабочий день; иначе регистрация + срок вида
    документа (`kind_days`, справочник `letter-kinds`, EDS-REG), а без него + 3 дня («срочно») или + 10 дней; выходной —
    на понедельник; не раньше `today`."""
    if track_of(letter) is not LetterTrack.OFFICE:
        return None
    if letter.document_due is not None:
        hint = prev_workday(letter.document_due)
    else:
        start = clock.company_date(letter.registered_at)
        days = kind_days if kind_days is not None else (URGENT_DAYS if letter.urgent else NORMAL_DAYS)
        hint = next_workday(start + timedelta(days=days))
    return max(hint, today)


def reminder_due(due: date, issued_on: date, today: date, sent: Iterable[str]) -> str | None:
    """Какое напоминание о сроке `due` отправить сегодня (одно, самое позднее из наступивших), или `None`.

    Точки: `d3` — за 3 дня (на рабочий день раньше, если выпало на выходной), только если срок дальше 10 дней от
    выдачи; `d1` — предыдущий рабочий день; `d0` — день срока; `overdue` — любой день после срока. Точки не позже дня
    выдачи не напоминают (о сроке сказало само поручение). Пропущенные (воркер стоял) не досылаются по одной: уходит
    последнее наступившее.
    """
    done = set(sent)
    if today > due:
        return None if "overdue" in done else "overdue"
    points: list[tuple[str, date]] = []
    if (due - issued_on).days > LONG_TERM_DAYS:
        d3 = due - timedelta(days=3)
        points.append(("d3", d3 if is_workday(d3) else prev_workday(d3)))
    points += [("d1", prev_workday(due)), ("d0", due)]
    ready = [key for key, when in points if issued_on < when <= today]
    if not ready or ready[-1] in done:
        return None
    return ready[-1]


def _keys_up_to(key: str) -> list[str]:
    order = ["d3", "d1", "d0", "overdue"]
    return order[: order.index(key) + 1]


# --- общее --------------------------------------------------------------------------------------------------------


def _today() -> date:
    return clock.company_date(clock.now())


def _fmt(day: date | None) -> str:
    return day.strftime("%d.%m.%Y") if day else ""


async def _letter_for_update(session: AsyncSession, letter_id: uuid.UUID) -> Letter:
    letter = (
        await session.execute(select(Letter).where(Letter.id == letter_id).with_for_update())
    ).scalar_one_or_none()
    if letter is None:
        raise not_found("Письмо не найдено.")
    return letter


async def _instruction_for_update(session: AsyncSession, instruction_id: uuid.UUID) -> tuple[Instruction, Letter]:
    """Поручение и его письмо под блокировкой (письмо первым — порядок блокировок как у резолюции)."""
    found = (
        await session.execute(select(Instruction.letter_id).where(Instruction.id == instruction_id))
    ).scalar_one_or_none()
    if found is None:
        raise not_found("Поручение не найдено.")
    letter = await _letter_for_update(session, found)
    instruction = (
        await session.execute(select(Instruction).where(Instruction.id == instruction_id).with_for_update())
    ).scalar_one()
    return instruction, letter


def _require_office(letter: Letter) -> None:
    if track_of(letter) is not LetterTrack.OFFICE:
        raise conflict(
            "track_mismatch",
            "Это письмо по заявке клиента: резолюция — расчёт по зонам.",
            track=LetterTrack.CALC.value,
        )


def _require_awaiting(letter: Letter) -> None:
    if letter.status != LetterStatus.AWAITING_RESOLUTION.value:
        raise conflict(
            "invalid_state",
            "Операция недоступна в текущем статусе письма.",
            status=letter.status,
            expected=LetterStatus.AWAITING_RESOLUTION.value,
        )


async def notify(
    session: AsyncSession,
    bus: AsyncBus,
    *,
    letter: Letter,
    kind: str,
    key: str,
    recipients: Iterable[int | None],
    title: str,
    subtitle: str | None = None,
    due: date | None = None,
    actor_id: int | None = None,
) -> None:
    """`notice.requested` получателям (без повторов и пустых); никого — события нет."""
    people = list(dict.fromkeys(uid for uid in recipients if uid is not None))
    if not people:
        return
    data: dict[str, Any] = {
        "notice_key": key,
        "kind": kind,
        "recipients": people,
        "title": title[:200],
        "subtitle": subtitle[:200] if subtitle else None,
        "letter": {"eds_letter_id": str(letter.id), "number": letter.number, "subject": letter.subject},
        "due": due.isoformat() if due else None,
        "actor": events.actor(actor_id),
    }
    await events.publish(bus, session, "notice.requested", data, subject=letter.number)


async def _check_people(
    session: AsyncSession,
    *,
    responsible: int | None,
    co_executors: Sequence[int],
    acquaint: Sequence[int],
) -> None:
    """Все — активные сотрудники проекции; один человек — не дважды (ответственный, соисполнители, «ознакомить»)."""
    workers = [*([responsible] if responsible is not None else []), *co_executors]
    everyone = [*workers, *acquaint]
    if len(set(workers)) != len(workers):
        raise invalid_fields("Сотрудник указан дважды.", co_executor_ids="duplicate")
    if len(set(everyone)) != len(everyone):
        raise invalid_fields("Сотрудник указан дважды.", acquaint_ids="duplicate")
    active = await active_ids(session, everyone)
    bad: dict[str, str] = {}
    if responsible is not None and responsible not in active:
        bad["responsible_crm_user_id"] = "not_active_employee"
    if any(uid not in active for uid in co_executors):
        bad["co_executor_ids"] = "not_active_employee"
    if any(uid not in active for uid in acquaint):
        bad["acquaint_ids"] = "not_active_employee"
    if bad:
        raise invalid_fields("Сотрудник не найден или отключён.", **bad)


def _check_due(due: date | None, today: date) -> None:
    if due is not None and due < today:
        raise invalid_fields("Срок не может быть в прошлом.", due="due_in_past")


# --- проект резолюции ---------------------------------------------------------------------------------------------


async def validate_draft(session: AsyncSession, data: ResolutionDraftIn) -> dict[str, Any] | None:
    """Проект как хранится в письме; `kind = None` — проекта нет."""
    if data.kind is None:
        return None
    _check_due(data.due, _today())
    await _check_people(
        session,
        responsible=data.responsible_crm_user_id,
        co_executors=data.co_executor_ids,
        acquaint=data.acquaint_ids,
    )
    return {
        "kind": data.kind.value,
        "responsible": data.responsible_crm_user_id,
        "due": data.due.isoformat() if data.due else None,
        "text": (data.text or "").strip() or None,
        "co_executors": list(data.co_executor_ids),
        "acquaint": list(data.acquaint_ids),
    }


def stamp_draft(draft: dict[str, Any] | None, actor_id: int) -> dict[str, Any] | None:
    if draft is None:
        return None
    return {**draft, "by": actor_id, "at": clock.now().isoformat()}


async def save_draft(session: AsyncSession, *, actor_id: int, letter_id: uuid.UUID, data: ResolutionDraftIn) -> Letter:
    """Проект резолюции делопроизводителя (или директора): заменяется целиком, журнал `letter.draft_saved`."""
    letter = await _letter_for_update(session, letter_id)
    _require_office(letter)
    _require_awaiting(letter)
    letter.resolution_draft = stamp_draft(await validate_draft(session, data), actor_id)
    letter.updated_at = clock.now()
    await journal.record(session, "letter.draft_saved", by=actor_id, letter_id=letter.id)
    return letter


# --- резолюция ----------------------------------------------------------------------------------------------------


async def resolve_office(
    session: AsyncSession, bus: AsyncBus, *, actor_id: int, letter_id: uuid.UUID, data: OfficeResolutionIn
) -> Letter:
    """Резолюция пути делопроизводства. Поручения и ознакомление — строки; `letter.resolved` не публикуется."""
    letter = await _letter_for_update(session, letter_id)
    _require_office(letter)
    _require_awaiting(letter)
    today = _today()
    with_work = data.kind is not ResolutionKind.INFO
    if with_work:
        missing = {
            name: "required"
            for name, value in (("responsible_crm_user_id", data.responsible_crm_user_id), ("due", data.due))
            if value is None
        }
        if missing:
            raise invalid_fields("Укажите ответственного и срок.", **missing)
    else:
        extra = {
            name: "not_allowed_for_info"
            for name, given in (
                ("responsible_crm_user_id", data.responsible_crm_user_id is not None),
                ("due", data.due is not None),
                ("co_executor_ids", bool(data.co_executor_ids)),
            )
            if given
        }
        if extra:
            raise invalid_fields("«Для сведения» — без исполнителя и срока.", **extra)
    _check_due(data.due, today)
    await _check_people(
        session,
        responsible=data.responsible_crm_user_id,
        co_executors=data.co_executor_ids,
        acquaint=data.acquaint_ids,
    )
    now = clock.now()
    letter.resolution_kind = data.kind.value
    letter.resolution_text = data.text
    letter.resolution_due = data.due
    letter.resolution_decided_by, letter.resolution_decided_at = actor_id, now
    letter.resolution_draft = None
    letter.updated_at = now
    created: list[Instruction] = []
    if with_work and data.responsible_crm_user_id is not None and data.due is not None:
        people = [(data.responsible_crm_user_id, "responsible")] + [
            (uid, "co_executor") for uid in data.co_executor_ids
        ]
        for uid, role in people:
            instruction = Instruction(
                id=uuid.uuid4(),
                letter_id=letter.id,
                crm_user_id=uid,
                role=role,
                kind=data.kind.value,
                due=data.due,
                text=data.text,
                status=IN_WORK,
                reminders_sent=[],
                created_by=actor_id,
                created_at=now,
                updated_at=now,
            )
            session.add(instruction)
            created.append(instruction)
        letter.status, letter.on_control = LetterStatus.IN_EXECUTION.value, True
    else:
        letter.status, letter.on_control = LetterStatus.NOTED.value, False
    for uid in data.acquaint_ids:
        session.add(Acquaintance(id=uuid.uuid4(), letter_id=letter.id, crm_user_id=uid, created_at=now))
    await session.flush()
    await journal.record(session, "letter.resolved", by=actor_id, letter_id=letter.id, comment=data.text)
    for instruction in created:
        reply = instruction.kind == ResolutionKind.REPLY.value
        title = f"Подготовить ответ на письмо {letter.number}" if reply else f"Поручение по письму {letter.number}"
        await notify(
            session,
            bus,
            letter=letter,
            kind="instruction_assigned",
            key=f"instruction:{instruction.id}:assigned",
            recipients=[instruction.crm_user_id],
            title=title,
            subtitle=f"{letter.subject} · срок {_fmt(instruction.due)}",
            due=instruction.due,
            actor_id=actor_id,
        )
    await notify(
        session,
        bus,
        letter=letter,
        kind="acquaint_requested",
        key=f"letter:{letter.id}:acquaint",
        recipients=data.acquaint_ids,
        title=f"Ознакомьтесь с письмом {letter.number}",
        subtitle=letter.subject,
        actor_id=actor_id,
    )
    log.info("letter_office_resolved", number=letter.number, kind=data.kind.value, instructions=len(created))
    return letter


# --- исполнение ---------------------------------------------------------------------------------------------------


async def _finish_if_done(session: AsyncSession, bus: AsyncBus, letter: Letter, actor_id: int | None) -> None:
    """Все поручения письма исполнены — письмо «Исполнено», контроль снят, уведомление автору и регистратору."""
    if letter.status != LetterStatus.IN_EXECUTION.value:
        return
    open_left = await session.execute(
        select(Instruction.id).where(Instruction.letter_id == letter.id, Instruction.status == IN_WORK).limit(1)
    )
    if open_left.scalar_one_or_none() is not None:
        return
    now = clock.now()
    letter.status, letter.on_control, letter.executed_at, letter.updated_at = (
        LetterStatus.EXECUTED.value,
        False,
        now,
        now,
    )
    await journal.record(session, "letter.executed", by=actor_id, letter_id=letter.id)
    await notify(
        session,
        bus,
        letter=letter,
        kind="letter_executed",
        key=f"letter:{letter.id}:executed",
        recipients=[letter.resolution_decided_by, letter.registered_by],
        title=f"Исполнено: {letter.number}",
        subtitle=letter.subject,
        actor_id=actor_id,
    )


async def _outgoing_by_number(session: AsyncSession, number: str) -> Document:
    stmt = select(Document).where(
        Document.number == number.strip(), Document.kind == "letter_out", Document.status == "sent"
    )
    document = (await session.execute(stmt)).scalar_one_or_none()
    if document is None:
        raise invalid_fields("Отправленный ИСХ с таким номером не найден.", outgoing_number="not_found")
    return document


async def complete(
    session: AsyncSession, bus: AsyncBus, *, actor_id: int, instruction_id: uuid.UUID, data: InstructionCompleteIn
) -> Letter:
    """«Исполнено» исполнителем: отчёт (текст, файлы) или отправленный ИСХ."""
    instruction, letter = await _instruction_for_update(session, instruction_id)
    if instruction.crm_user_id != actor_id:
        raise forbidden_reason("not_executor", "Отметить исполнение может только исполнитель поручения.")
    if instruction.status != IN_WORK:
        raise conflict("invalid_state", "Поручение уже исполнено.", status=instruction.status, expected=IN_WORK)
    report = (data.report or "").strip() or None
    outgoing = await _outgoing_by_number(session, data.outgoing_number) if data.outgoing_number else None
    if report is None and not data.file_ids and outgoing is None:
        raise invalid_fields("Напишите отчёт, приложите файл или укажите ИСХ.", report="report_required")
    await files.attach(session, data.file_ids, actor_id=actor_id, instruction_id=instruction.id)
    now = clock.now()
    instruction.status, instruction.report, instruction.executed_at, instruction.updated_at = (
        EXECUTED,
        report,
        now,
        now,
    )
    instruction.outgoing_document_id = outgoing.id if outgoing else None
    comment = report if outgoing is None else f"Ответ {outgoing.number}" + (f". {report}" if report else "")
    await journal.record(session, "instruction.executed", by=actor_id, letter_id=letter.id, comment=comment)
    await _finish_if_done(session, bus, letter, actor_id)
    return letter


async def close_by_outgoing(session: AsyncSession, bus: AsyncBus, *, document: Document, actor_id: int) -> int:
    """Хук регистрации ИСХ «в ответ на ВХ» (`documents._send_letter`; P4 — тот же вызов): поручения «Подготовить
    ответ» этого письма в работе → «Исполнено» со ссылкой на ИСХ. Возвращает число закрытых."""
    if document.in_reply_to is None or document.kind != "letter_out":
        return 0
    letter = await _letter_for_update(session, document.in_reply_to)
    rows = list(
        (
            await session.execute(
                select(Instruction)
                .where(
                    Instruction.letter_id == letter.id,
                    Instruction.kind == ResolutionKind.REPLY.value,
                    Instruction.status == IN_WORK,
                )
                .with_for_update()
            )
        ).scalars()
    )
    now = clock.now()
    for instruction in rows:
        instruction.status, instruction.executed_at, instruction.updated_at = EXECUTED, now, now
        instruction.outgoing_document_id = document.id
        await journal.record(
            session,
            "instruction.executed",
            by=actor_id,
            letter_id=letter.id,
            comment=f"Ответ {document.number}",
        )
    if rows:
        await _finish_if_done(session, bus, letter, actor_id)
    return len(rows)


# --- перенос срока ------------------------------------------------------------------------------------------------


async def _pending(session: AsyncSession, instruction_id: uuid.UUID) -> InstructionExtension | None:
    stmt = select(InstructionExtension).where(
        InstructionExtension.instruction_id == instruction_id, InstructionExtension.status == "pending"
    )
    return (await session.execute(stmt.with_for_update())).scalar_one_or_none()


async def request_extension(
    session: AsyncSession, bus: AsyncBus, *, actor_id: int, instruction_id: uuid.UUID, data: ExtensionRequestIn
) -> Letter:
    """Запрос переноса срока исполнителем: строка запроса, задача и уведомление автору резолюции."""
    instruction, letter = await _instruction_for_update(session, instruction_id)
    if instruction.crm_user_id != actor_id:
        raise forbidden_reason("not_executor", "Перенос срока просит исполнитель поручения.")
    if instruction.status != IN_WORK:
        raise conflict("invalid_state", "Поручение уже исполнено.", status=instruction.status, expected=IN_WORK)
    if data.new_due <= instruction.due:
        raise invalid_fields("Новый срок должен быть позже текущего.", new_due="not_later")
    if await _pending(session, instruction.id) is not None:
        raise conflict("extension_pending", "Запрос переноса уже ждёт решения.")
    now = clock.now()
    extension = InstructionExtension(
        id=uuid.uuid4(),
        instruction_id=instruction.id,
        old_due=instruction.due,
        new_due=data.new_due,
        reason=data.reason,
        status="pending",
        requested_by=actor_id,
        requested_at=now,
    )
    session.add(extension)
    await session.flush()
    await journal.record(
        session,
        "instruction.extension_requested",
        by=actor_id,
        letter_id=letter.id,
        comment=f"{_fmt(instruction.due)} → {_fmt(data.new_due)}: {data.reason}",
    )
    directory = await load_directory(session, [actor_id])
    await notify(
        session,
        bus,
        letter=letter,
        kind="extension_requested",
        key=f"extension:{extension.id}:requested",
        recipients=[letter.resolution_decided_by],
        title=f"Запрос переноса срока по письму {letter.number}",
        subtitle=f"{directory.name(actor_id)}: до {_fmt(data.new_due)} · {data.reason}",
        due=data.new_due,
        actor_id=actor_id,
    )
    return letter


async def decide_extension(
    session: AsyncSession, bus: AsyncBus, *, actor_id: int, instruction_id: uuid.UUID, data: ExtensionDecisionIn
) -> Letter:
    """Решение автора резолюции по переносу. Одобрено — новый срок, напоминания заново; срочное — только отклонить."""
    instruction, letter = await _instruction_for_update(session, instruction_id)
    if letter.resolution_decided_by != actor_id:
        raise forbidden_reason("not_resolution_author", "Перенос срока решает автор резолюции.")
    pending = await _pending(session, instruction.id)
    if pending is None:
        raise conflict("no_pending_extension", "Запроса переноса без решения нет.")
    approve = data.decision is ExtensionDecision.APPROVE
    if approve and letter.urgent:
        raise conflict("urgent_not_extendable", "Срок срочного письма не продлевается — запрос можно только отклонить.")
    now = clock.now()
    pending.status = "approved" if approve else "rejected"
    pending.decided_by, pending.decided_at, pending.comment = actor_id, now, (data.comment or "").strip() or None
    if approve:
        instruction.due, instruction.reminders_sent, instruction.updated_at = pending.new_due, [], now
        if instruction.role == "responsible":
            letter.resolution_due = pending.new_due
        letter.updated_at = now
    action = "instruction.extension_approved" if approve else "instruction.extension_rejected"
    await journal.record(session, action, by=actor_id, letter_id=letter.id, comment=pending.comment)
    verdict = "одобрен" if approve else "отклонён"
    await notify(
        session,
        bus,
        letter=letter,
        kind="extension_decided",
        key=f"extension:{pending.id}:decided",
        recipients=[instruction.crm_user_id],
        title=f"Перенос срока {verdict}: {letter.number}",
        subtitle=f"Срок {_fmt(instruction.due)}" + (f" · {pending.comment}" if pending.comment else ""),
        due=instruction.due,
        actor_id=actor_id,
    )
    return letter


# --- ознакомление -------------------------------------------------------------------------------------------------


async def acknowledge(session: AsyncSession, *, actor_id: int, letter_id: uuid.UUID) -> Letter:
    """«Ознакомлен»: дата у своей строки; повтор — без изменений; не в списке — 404."""
    letter = await _letter_for_update(session, letter_id)
    row = (
        await session.execute(
            select(Acquaintance)
            .where(Acquaintance.letter_id == letter.id, Acquaintance.crm_user_id == actor_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise not_found("Вас нет в списке «ознакомить».")
    if row.acknowledged_at is None:
        row.acknowledged_at = clock.now()
        await journal.record(session, "letter.acknowledged", by=actor_id, letter_id=letter.id)
    return letter


# --- видимость ----------------------------------------------------------------------------------------------------


async def is_participant(session: AsyncSession, crm_user_id: int, letter: Letter) -> bool:
    """Исполнитель поручения, в списке «ознакомить» или автор резолюции (Росархив 3.31: исполнитель видит документ)."""
    if letter.resolution_decided_by == crm_user_id:
        return True
    stmt = select(
        exists().where(Instruction.letter_id == letter.id, Instruction.crm_user_id == crm_user_id)
        | exists().where(Acquaintance.letter_id == letter.id, Acquaintance.crm_user_id == crm_user_id)
    )
    return bool((await session.execute(stmt)).scalar())


async def require_readable(session: AsyncSession, employee: Employee, letter: Letter) -> None:
    """Карточка письма: `letters.read` или участник; иначе 403 (как раньше без права)."""
    if access.has(employee, P.LETTERS_READ):
        return
    if await is_participant(session, employee.crm_user_id, letter):
        return
    raise forbidden((P.LETTERS_READ.value,))


# --- «Мои задачи» и сотрудники ------------------------------------------------------------------------------------


def _task_letter(letter: Letter) -> LetterTaskLetter:
    return LetterTaskLetter(
        id=letter.id, number=letter.number, subject=letter.subject, sender_name=letter.sender_name, urgent=letter.urgent
    )


async def my_tasks(session: AsyncSession, *, crm_user_id: int, today: date | None = None) -> LetterTasks:
    """Поручения в работе (я исполнитель), переносы на моё решение (я автор резолюции), ознакомления без отметки."""
    day = today or _today()
    pending_ext = exists().where(
        InstructionExtension.instruction_id == Instruction.id, InstructionExtension.status == "pending"
    )
    rows = (
        await session.execute(
            select(Instruction, Letter, pending_ext.label("pending"))
            .join(Letter, Letter.id == Instruction.letter_id)
            .where(Instruction.crm_user_id == crm_user_id, Instruction.status == IN_WORK)
            .order_by(Instruction.due, Instruction.created_at)
            .limit(TASKS_LIMIT)
        )
    ).all()
    instructions = [
        InstructionTask(
            id=i.id,
            letter=_task_letter(letter),
            kind=ResolutionKind(i.kind),
            role=i.role,
            due=i.due,
            overdue=i.due < day,
            extension_pending=bool(pending),
            created_at=i.created_at,
        )
        for i, letter, pending in rows
    ]
    ext_rows = (
        await session.execute(
            select(InstructionExtension, Instruction, Letter)
            .join(Instruction, Instruction.id == InstructionExtension.instruction_id)
            .join(Letter, Letter.id == Instruction.letter_id)
            .where(InstructionExtension.status == "pending", Letter.resolution_decided_by == crm_user_id)
            .order_by(InstructionExtension.requested_at)
            .limit(TASKS_LIMIT)
        )
    ).all()
    directory = await load_directory(session, (i.crm_user_id for _, i, _ in ext_rows))
    extensions = [
        ExtensionTask(
            id=e.id,
            instruction_id=i.id,
            letter=_task_letter(letter),
            executor=directory.person(i.crm_user_id),
            old_due=e.old_due,
            new_due=e.new_due,
            reason=e.reason,
            requested_at=e.requested_at,
        )
        for e, i, letter in ext_rows
    ]
    acq_rows = (
        await session.execute(
            select(Acquaintance, Letter)
            .join(Letter, Letter.id == Acquaintance.letter_id)
            .where(Acquaintance.crm_user_id == crm_user_id, Acquaintance.acknowledged_at.is_(None))
            .order_by(Acquaintance.created_at)
            .limit(TASKS_LIMIT)
        )
    ).all()
    acquaintances = [AcquaintanceTask(letter=_task_letter(letter), created_at=a.created_at) for a, letter in acq_rows]
    return LetterTasks(instructions=instructions, extensions=extensions, acquaintances=acquaintances)


async def active_employees(session: AsyncSession) -> EmployeeList:
    """Активные сотрудники проекции по имени; «надгробия» (пустое имя) — нет."""
    rows = (
        await session.execute(
            select(Employee.crm_user_id, Employee.full_name, Employee.position)
            .where(Employee.is_active.is_(True), Employee.full_name != "")
            .order_by(Employee.full_name, Employee.crm_user_id)
        )
    ).all()
    return EmployeeList(
        items=[EmployeeChoice(crm_user_id=int(uid), full_name=name, position=pos or None) for uid, name, pos in rows]
    )


# --- контроль сроков ----------------------------------------------------------------------------------------------

_REMINDER_TITLES = {
    "d3": "Через 3 дня срок поручения по письму {number}",
    "d1": "Срок поручения по письму {number} — {due}",
    "d0": "Сегодня срок поручения по письму {number}",
}


async def send_reminders(session: AsyncSession, bus: AsyncBus, *, now: datetime) -> int:
    """Напоминания и «Просрочено» по поручениям в работе на момент `now` (вызывает задача по расписанию).

    До 9:00 по `Asia/Tashkent` ничего не шлёт. Возвращает число отправленных уведомлений."""
    if now.astimezone(clock.COMPANY_TZ).hour < REMINDER_HOUR:
        return 0
    today = clock.company_date(now)
    rows = (
        await session.execute(
            select(Instruction, Letter)
            .join(Letter, Letter.id == Instruction.letter_id)
            .where(Instruction.status == IN_WORK, Instruction.due <= today + timedelta(days=4))
            .order_by(Instruction.due)
            .with_for_update(of=Instruction, skip_locked=True)
        )
    ).all()
    sent = 0
    for instruction, letter in rows:
        key = reminder_due(
            instruction.due, clock.company_date(instruction.created_at), today, instruction.reminders_sent or []
        )
        if key is None:
            continue
        instruction.reminders_sent = sorted({*(instruction.reminders_sent or []), *_keys_up_to(key)})
        if key == "overdue":
            await notify(
                session,
                bus,
                letter=letter,
                kind="instruction_overdue",
                key=f"instruction:{instruction.id}:overdue:{instruction.due.isoformat()}",
                recipients=[instruction.crm_user_id, letter.resolution_decided_by],
                title=f"Просрочено поручение по письму {letter.number}",
                subtitle=f"{letter.subject} · срок был {_fmt(instruction.due)}",
                due=instruction.due,
            )
        else:
            await notify(
                session,
                bus,
                letter=letter,
                kind="instruction_reminder",
                key=f"instruction:{instruction.id}:{key}:{instruction.due.isoformat()}",
                recipients=[instruction.crm_user_id],
                title=_REMINDER_TITLES[key].format(number=letter.number, due=_fmt(instruction.due)),
                subtitle=letter.subject,
                due=instruction.due,
            )
        sent += 1
    if sent:
        log.info("instruction_reminders_sent", count=sent, day=today.isoformat())
    return sent


def overdue_clause(today: date) -> Any:
    """Условие «у письма есть просроченное поручение» для выборки `Letter`."""
    return exists().where(
        and_(Instruction.letter_id == Letter.id, Instruction.status == IN_WORK, Instruction.due < today)
    )


__all__ = [
    "EdsError",
    "acknowledge",
    "active_employees",
    "close_by_outgoing",
    "complete",
    "decide_extension",
    "is_participant",
    "my_tasks",
    "next_workday",
    "overdue_clause",
    "prev_workday",
    "reminder_due",
    "request_extension",
    "require_readable",
    "resolve_office",
    "save_draft",
    "send_reminders",
    "suggested_due",
    "track_of",
    "validate_draft",
]
