"""«Оплачено»: бухгалтер оплачивает согласованную директором служебную записку (SPEC-v3 §3.2 п. 5, §2.4).

Маршрут «директор → бухгалтер» (`approvals.steps_for`) приводит записку с суммой к статусу `to_accountant` — «Передана
бухгалтеру» (приложенный счёт поставщика остаётся в файлах документа). Бухгалтер оплачивает её вне платформы и фиксирует
факт здесь: дата, сумма, платёжка. Операция закрывает шаг «Бухгалтер» (`approval.decided`, решение `approve`), переводит
документ в `paid`, архивирует его и пишет в журнал `document.paid`. Другого пути к `paid` нет: решение `approve` на шаге
бухгалтера через `/approvals/{id}/decision` отклоняется (`payment_required`).
"""

import uuid
from decimal import Decimal

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import conflict, forbidden_reason, invalid_fields, not_found
from app.models import ApprovalRoute, ApprovalStep, Document, DocumentPayment, Employee
from app.schemas.approvals import Decision, DecisionIn, RouteStatus
from app.schemas.documents import DocumentKind, DocumentPaymentIn, DocumentStatus
from app.security.permissions import EdsPermission as P
from app.services import access, approvals, files, journal


def is_accountant_step(step: ApprovalStep) -> bool:
    return step.assignee_permission == P.PAYMENTS_CONFIRM.value


async def _current_accountant_step(
    session: AsyncSession, employee: Employee, document: Document
) -> tuple[ApprovalRoute, list[ApprovalStep], ApprovalStep]:
    route = (
        await session.execute(
            select(ApprovalRoute)
            .where(ApprovalRoute.document_id == document.id, ApprovalRoute.status == RouteStatus.OPEN.value)
            .order_by(ApprovalRoute.round.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if route is None or route.current_step is None:
        raise conflict("route_closed", "Маршрут уже завершён.", status=document.status)
    steps = await approvals.load_steps(session, route.id)
    current = next(s for s in steps if s.index == route.current_step)
    if not is_accountant_step(current):
        raise conflict("invalid_state", "Записка ещё не передана бухгалтеру.", status=document.status)
    # Объектная проверка: шаг ждёт этого сотрудника, разделение обязанностей не мешает (автор не платит свою записку).
    if not await approvals.may_decide(session, employee, route.id, current.index):
        raise forbidden_reason("not_your_step", "Сейчас решение за другим сотрудником.")
    return route, steps, current


def _check_money(document: Document, body: DocumentPaymentIn) -> Decimal:
    amount = Decimal(body.amount.amount)
    if amount <= 0:
        raise invalid_fields("Сумма оплаты должна быть больше нуля.", amount="must_be_positive")
    if body.amount.currency != document.currency:
        raise invalid_fields("Валюта оплаты должна совпадать с валютой записки.", amount="currency_mismatch")
    if document.amount is not None and amount > document.amount:
        raise invalid_fields("Сумма оплаты больше согласованной директором.", amount="exceeds_approved")
    if body.paid_on > clock.company_date(clock.now()):
        raise invalid_fields("Дата оплаты не может быть в будущем.", paid_on="in_future")
    return amount


async def pay(
    session: AsyncSession, bus: AsyncBus, *, employee: Employee, document_id: uuid.UUID, body: DocumentPaymentIn
) -> Document:
    """Оплатить записку на шаге бухгалтера.

    Порядок отказов: не виден → 404; не записка → 409; оплачена другими данными → 409 `already_paid`; не на этом шаге →
    409; не ваш шаг → 403; сумма, валюта, дата → 422. Повтор с теми же данными — тот же документ без изменений.
    """
    document = (
        await session.execute(select(Document).where(Document.id == document_id).with_for_update())
    ).scalar_one_or_none()
    if document is None or not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    if document.kind != DocumentKind.MEMO.value or document.amount is None:
        raise conflict("invalid_state", "Оплачивается только служебная записка с суммой.", status=document.status)
    paid = await session.get(DocumentPayment, document.id)
    if paid is not None:
        same = (
            paid.paid_on == body.paid_on
            and f"{paid.amount:.2f}" == body.amount.amount
            and paid.currency == body.amount.currency
        )
        if same:
            return document
        raise conflict("already_paid", "Записка уже оплачена.", status=document.status)
    if document.status != DocumentStatus.TO_ACCOUNTANT.value:
        raise conflict("invalid_state", "Записка не передана бухгалтеру на оплату.", status=document.status)
    route, steps, current = await _current_accountant_step(session, employee, document)
    amount = _check_money(document, body)
    if body.receipt_file_id is not None:
        await files.attach(session, [body.receipt_file_id], actor_id=employee.crm_user_id, document_id=document.id)
    now = clock.now()
    session.add(
        DocumentPayment(
            document_id=document.id,
            paid_on=body.paid_on,
            amount=amount,
            currency=body.amount.currency,
            receipt_file_id=body.receipt_file_id,
            note=(body.note or "").strip() or None,
            paid_by_crm_user_id=employee.crm_user_id,
            created_at=now,
        )
    )
    await session.flush()
    await journal.record(
        session,
        "document.paid",
        by=employee.crm_user_id,
        document_id=document.id,
        approval_id=route.id,
        comment=f"{body.paid_on.strftime('%d.%m.%Y')}, {body.amount.amount} {body.amount.currency}",
        file_id=body.receipt_file_id,
    )
    decision = DecisionIn(decision=Decision.APPROVE, comment=(body.note or "").strip() or None)
    await approvals.complete_step(session, bus, employee, route, steps, current, decision)
    return document


__all__ = ["is_accountant_step", "pay"]
