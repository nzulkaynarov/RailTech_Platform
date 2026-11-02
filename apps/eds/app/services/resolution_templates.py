"""Шаблоны резолюций (EDS-REG, R2; исследование 2026-11-02 «Маршруты» §4.2; эталоны — Directum RX, 1С:ДО 3.0).

* Видит сотрудник общие шаблоны и свои личные; чужие личные — нет (404, существование не раскрывается).
* Личный шаблон заводит директор или делопроизводитель для себя; общий — администратор (`bus.manage`).
* Вид — закрытый список поведения (`execute`, `reply`, `info`); у «Для сведения» нет ответственного и срока.
* Люди — активные сотрудники проекции на момент сохранения; при применении форма всё равно проверяет их заново.
* Каждое изменение — строка журнала `resolution_template.*` в той же транзакции.
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import conflict, forbidden_reason, invalid_fields, not_found
from app.models import Employee, ResolutionTemplate
from app.schemas.letters import ResolutionKind
from app.schemas.resolution_templates import ResolutionTemplate as TemplateOut
from app.schemas.resolution_templates import (
    ResolutionTemplateIn,
    ResolutionTemplateList,
    ResponsibleType,
    TemplateScope,
)
from app.security.permissions import EdsPermission as P
from app.services import journal
from app.services.people import Directory, active_ids, load_directory

LIMIT = 500


def _is_admin(employee: Employee) -> bool:
    return P.BUS_MANAGE.value in employee.permissions_eds


def _can_edit(row: ResolutionTemplate, employee: Employee) -> bool:
    if row.scope == TemplateScope.COMPANY:
        return _is_admin(employee)
    return row.owner_crm_user_id == employee.crm_user_id


def _people(row: ResolutionTemplate) -> Iterable[int | None]:
    return [row.responsible_crm_user_id, row.owner_crm_user_id, *row.co_executor_ids, *row.acquaint_ids]


def _present(row: ResolutionTemplate, employee: Employee, directory: Directory) -> TemplateOut:
    return TemplateOut(
        id=row.id,
        name=row.name,
        scope=TemplateScope(row.scope),
        kind=ResolutionKind(row.kind),
        text=row.text,
        responsible_type=ResponsibleType(row.responsible_type),
        responsible=directory.person_or_none(row.responsible_crm_user_id),
        co_executors=[directory.person(int(i)) for i in row.co_executor_ids],
        acquaint=[directory.person(int(i)) for i in row.acquaint_ids],
        due_days=row.due_days,
        owner=directory.person_or_none(row.owner_crm_user_id),
        editable=_can_edit(row, employee),
    )


async def list_for(session: AsyncSession, employee: Employee) -> ResolutionTemplateList:
    """Общие шаблоны и свои личные: сначала свои, потом общие, по названию."""
    rows = list(
        (
            await session.execute(
                select(ResolutionTemplate)
                .where(
                    or_(
                        ResolutionTemplate.scope == TemplateScope.COMPANY.value,
                        ResolutionTemplate.owner_crm_user_id == employee.crm_user_id,
                    )
                )
                .order_by(ResolutionTemplate.scope.desc(), func.lower(ResolutionTemplate.name))
                .limit(LIMIT)
            )
        ).scalars()
    )
    directory = await load_directory(session, (uid for row in rows for uid in _people(row)))
    return ResolutionTemplateList(items=[_present(row, employee, directory) for row in rows])


def _normalized(data: ResolutionTemplateIn) -> ResolutionTemplateIn:
    """У «Для сведения» нет ответственного, соисполнителей и срока; ответственный-сотрудник — только у `person`."""
    if data.kind is ResolutionKind.INFO:
        return data.model_copy(
            update={
                "responsible_type": ResponsibleType.NONE,
                "responsible_crm_user_id": None,
                "co_executor_ids": [],
                "due_days": None,
            }
        )
    if data.responsible_type is not ResponsibleType.PERSON:
        return data.model_copy(update={"responsible_crm_user_id": None})
    return data


async def _validate(session: AsyncSession, data: ResolutionTemplateIn) -> None:
    if data.responsible_type is ResponsibleType.PERSON and data.responsible_crm_user_id is None:
        raise invalid_fields("Выберите ответственного.", responsible_crm_user_id="required")
    people = [*data.co_executor_ids, *data.acquaint_ids]
    if data.responsible_crm_user_id is not None:
        people.append(data.responsible_crm_user_id)
    active = await active_ids(session, people)
    bad: dict[str, str] = {}
    if data.responsible_crm_user_id is not None and data.responsible_crm_user_id not in active:
        bad["responsible_crm_user_id"] = "not_active_employee"
    if any(i not in active for i in data.co_executor_ids):
        bad["co_executor_ids"] = "not_active_employee"
    if any(i not in active for i in data.acquaint_ids):
        bad["acquaint_ids"] = "not_active_employee"
    if bad:
        raise invalid_fields("Сотрудник не найден или отключён.", **bad)


def _require_scope(scope: TemplateScope, employee: Employee) -> None:
    if scope is TemplateScope.COMPANY and not _is_admin(employee):
        raise forbidden_reason("company_template_admin_only", "Общие шаблоны ведёт администратор.")
    if scope is TemplateScope.PERSONAL and not {
        P.LETTERS_RESOLVE.value,
        P.LETTERS_REGISTER.value,
    } & set(employee.permissions_eds):
        raise forbidden_reason("personal_template_not_allowed", "Личные шаблоны — у тех, кто готовит резолюции.")


async def _name_taken(
    session: AsyncSession, data: ResolutionTemplateIn, owner: int | None, except_id: uuid.UUID | None
) -> bool:
    stmt = select(func.count()).where(
        ResolutionTemplate.scope == data.scope.value,
        func.lower(ResolutionTemplate.name) == data.name.lower(),
    )
    stmt = stmt.where(
        ResolutionTemplate.owner_crm_user_id.is_(None)
        if owner is None
        else ResolutionTemplate.owner_crm_user_id == owner
    )
    if except_id is not None:
        stmt = stmt.where(ResolutionTemplate.id != except_id)
    return bool((await session.execute(stmt)).scalar_one())


def _fill(row: ResolutionTemplate, data: ResolutionTemplateIn) -> None:
    row.name = data.name
    row.kind = data.kind.value
    row.text = data.text
    row.responsible_type = data.responsible_type.value
    row.responsible_crm_user_id = data.responsible_crm_user_id
    row.co_executor_ids = list(dict.fromkeys(data.co_executor_ids))
    row.acquaint_ids = list(dict.fromkeys(data.acquaint_ids))
    row.due_days = data.due_days
    row.updated_at = clock.now()


async def _out(session: AsyncSession, row: ResolutionTemplate, employee: Employee) -> TemplateOut:
    return _present(row, employee, await load_directory(session, _people(row)))


async def create(session: AsyncSession, employee: Employee, data: ResolutionTemplateIn) -> TemplateOut:
    _require_scope(data.scope, employee)
    data = _normalized(data)
    await _validate(session, data)
    owner = employee.crm_user_id if data.scope is TemplateScope.PERSONAL else None
    if await _name_taken(session, data, owner, None):
        raise conflict("name_taken", "Шаблон с таким названием уже есть.")
    now = clock.now()
    row = ResolutionTemplate(
        id=uuid.uuid4(),
        scope=data.scope.value,
        owner_crm_user_id=owner,
        created_by=employee.crm_user_id,
        created_at=now,
    )
    _fill(row, data)
    session.add(row)
    await session.flush()
    await journal.record(session, "resolution_template.created", by=employee.crm_user_id, comment=row.name)
    return await _out(session, row, employee)


async def _editable(session: AsyncSession, template_id: uuid.UUID, employee: Employee) -> ResolutionTemplate:
    row = await session.get(ResolutionTemplate, template_id, with_for_update=True)
    visible = row is not None and (
        row.scope == TemplateScope.COMPANY.value or row.owner_crm_user_id == employee.crm_user_id
    )
    if row is None or not visible:
        raise not_found("Шаблон не найден.")
    if not _can_edit(row, employee):
        raise forbidden_reason("company_template_admin_only", "Общие шаблоны ведёт администратор.")
    return row


async def update(
    session: AsyncSession, employee: Employee, template_id: uuid.UUID, data: ResolutionTemplateIn
) -> TemplateOut:
    row = await _editable(session, template_id, employee)
    if data.scope.value != row.scope:
        raise invalid_fields("Личный шаблон не становится общим и наоборот.", scope="scope_immutable")
    data = _normalized(data)
    await _validate(session, data)
    if await _name_taken(session, data, row.owner_crm_user_id, row.id):
        raise conflict("name_taken", "Шаблон с таким названием уже есть.")
    _fill(row, data)
    await session.flush()
    await journal.record(session, "resolution_template.updated", by=employee.crm_user_id, comment=row.name)
    return await _out(session, row, employee)


async def delete(session: AsyncSession, employee: Employee, template_id: uuid.UUID) -> None:
    row = await _editable(session, template_id, employee)
    name = row.name
    await session.delete(row)
    await session.flush()
    await journal.record(session, "resolution_template.deleted", by=employee.crm_user_id, comment=name)
