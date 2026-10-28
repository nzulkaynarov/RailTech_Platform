"""Счета и оплаты бухгалтера (D2-4; SPEC-v3 §3.1 шаг 8, §7.3 «Счета и оплаты»).

Что здесь. Доска счетов по вкладкам, карточка счёта, подтверждение оплаты по платёжке клиента (полное и частичное),
платёжка клиента на подтверждение (`PaymentConfirmation`, ERP-04), запрос платёжки у клиента. Деньги по-прежнему
записывает `crm.services.billing.record_payment` (права, остаток, идемпотентность по референсу, событие шины
`invoice.paid`, квитанция): здесь только оркестровка вокруг него и связь платёжки с платежом.

Просрочка не хранится статусом: счёт «Просрочен», когда срок оплаты прошёл, а остаток есть (так же вычисляет её задача
напоминаний `crm.send_payment_reminders`). Вкладки взаимно исключают друг друга, чтобы счёт был ровно в одной очереди:
«К выставлению» (черновик) → «Платёжки на подтверждение» (есть платёжка без подтверждения) → «Просрочены» → «Ждут оплаты».

Себестоимости и маржи в этих данных нет (решение архитектора Q-D2-1-4: бухгалтер видит только итоги счёта).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional, Tuple

from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone
from finance.models import Invoice, Payment, PaymentConfirmation

from accounts.models import CustomUser
from crm.constants import InvoiceStatusCode
from crm.models import ActivityLog

TABS = ("to_issue", "awaiting", "proofs", "overdue", "all")
TAB_COUNTED = ("to_issue", "awaiting", "proofs", "overdue")
OPEN_STATUSES = (InvoiceStatusCode.ISSUED, InvoiceStatusCode.PARTIAL, InvoiceStatusCode.OVERDUE)
HISTORY_EVENTS = ("payment.recorded", "payment_doc.attached", "payment_doc.requested")
MAX_LIMIT = 100

#: Слова статуса строки (SPEC-v3 §2.4 «Счёт»); интерфейс подписывает их сам, коды — часть контракта.
DISPLAY_STATUSES = ("draft", "issued", "proof_received", "partially_paid", "paid", "overdue", "cancelled")


def today() -> date:
    return timezone.localdate()


def _pending_proof():
    return PaymentConfirmation.objects.filter(invoice=OuterRef("pk"), status=PaymentConfirmation.Status.PENDING)


def _is_overdue_q(day: date) -> Q:
    return Q(status__code__in=OPEN_STATUSES, due_date__lt=day, has_proof=False)


def annotated(day: date | None = None) -> QuerySet:
    """Счета с признаками очереди: есть платёжка без подтверждения, когда пришла старейшая."""
    return Invoice.objects.select_related("deal__company", "status", "currency").annotate(
        has_proof=Exists(_pending_proof()),
        proof_at=Subquery(_pending_proof().order_by("received_at").values("received_at")[:1]),
    )


def tab_q(tab: str, day: date) -> Q:
    open_q = Q(status__code__in=OPEN_STATUSES)
    if tab == "to_issue":
        return Q(status__code=InvoiceStatusCode.DRAFT)
    if tab == "proofs":
        return open_q & Q(has_proof=True)
    if tab == "overdue":
        return _is_overdue_q(day)
    if tab == "awaiting":
        return open_q & Q(has_proof=False) & ~Q(due_date__lt=day)
    return Q(pk__isnull=False)


def display_status(invoice: Invoice, has_proof: bool, day: date) -> str:
    code = invoice.status_code
    if code == InvoiceStatusCode.CANCELLED:
        return "cancelled"
    if code == InvoiceStatusCode.PAID:
        return "paid"
    if code == InvoiceStatusCode.DRAFT:
        return "draft"
    if has_proof:
        return "proof_received"
    if invoice.due_date and invoice.due_date < day and invoice.balance_due > 0:
        return "overdue"
    return "partially_paid" if code == InvoiceStatusCode.PARTIAL else "issued"


def counts(day: date) -> dict[str, int]:
    """Число счетов на каждой вкладке одним запросом."""
    aggregates = {tab: Count("pk", filter=tab_q(tab, day)) for tab in TAB_COUNTED}
    return annotated().aggregate(**aggregates)


def board(*, tab: str, day: date, q: str = "", limit: int = 50, offset: int = 0) -> Tuple[QuerySet, int]:
    """Страница счетов вкладки: самые срочные сверху. Возвращает выборку страницы и общее число."""
    qs = annotated().filter(tab_q(tab, day))
    needle = q.strip()
    if needle:
        qs = qs.filter(Q(number__icontains=needle) | Q(deal__company__name__icontains=needle))
    if tab == "proofs":
        qs = qs.order_by("proof_at", "id")
    elif tab in ("awaiting", "overdue"):
        qs = qs.order_by("due_date", "id")
    elif tab == "to_issue":
        qs = qs.order_by("created_at", "id")
    else:
        qs = qs.order_by("-created_at", "-id")
    total = qs.count()
    limit = max(1, min(limit, MAX_LIMIT))
    return qs[max(offset, 0) : max(offset, 0) + limit], total


def get_invoice(invoice_id: int) -> Optional[Invoice]:
    return annotated().filter(pk=invoice_id).first()


def history(invoice: Invoice) -> list[ActivityLog]:
    """Журнал счёта: платежи, платёжки, запросы платёжки (записи `ActivityLog` по номеру счёта)."""
    return list(
        ActivityLog.objects.filter(
            deal_id=invoice.deal_id, event_code__in=HISTORY_EVENTS, event_params__number=invoice.number
        )
        .select_related("user")
        .order_by("-timestamp", "-id")[:50]
    )


def last_doc_request(invoice: Invoice) -> Optional[ActivityLog]:
    return (
        ActivityLog.objects.filter(
            deal_id=invoice.deal_id, event_code="payment_doc.requested", event_params__number=invoice.number
        )
        .order_by("-timestamp", "-id")
        .first()
    )


def _log(invoice: Invoice, actor: CustomUser, code: str, action: str, detail: str, params: dict[str, Any]) -> None:
    ActivityLog.objects.create(
        action=action,
        detail=detail,
        event_code=code,
        event_params={"number": invoice.number, **params},
        user=actor,
        level="INFO",
        deal=invoice.deal,
        company_id=invoice.deal.company_id,
        entity_type="invoice",
        entity_id=invoice.pk,
    )


def _may_pay(actor: CustomUser) -> bool:
    from accounts.services.permissions import staff_has_permission

    return bool(getattr(actor, "is_superuser", False) or staff_has_permission(actor, "finance.payment"))


def _forbidden(actor: CustomUser) -> Optional[str]:
    """Код отказа, если сотрудник не вправе подтверждать оплату: не сотрудник своей компании / нет права роли."""
    if getattr(actor, "is_superuser", False):
        return None
    from accounts.services import primary_seller_company_id

    if primary_seller_company_id(actor) is None:
        return "MEMBER_REQUIRED_FOR_ACTION"
    return None if _may_pay(actor) else "ROLE_NOT_PERMITTED"


@dataclass
class Confirmed:
    payment: Payment
    replayed: bool


def confirm_payment(
    invoice_id: int,
    actor: CustomUser,
    *,
    amount: Decimal,
    paid_at: date,
    reference: str = "",
    confirmation_id: Optional[int] = None,
) -> Tuple[Optional[Confirmed], Optional[str]]:
    """«Подтвердить оплату» (SPEC-v3 §3.1 шаг 8): сумма и дата — по выписке банка, платёжка клиента — по желанию.

    Полная оплата закрывает счёт (`PAID`, событие шины `invoice.paid`, стадия проекта «Оплата выполнена» выводится из
    оплаченных счетов — `integration.services.stages`), неполная — `PARTIAL` с видимым остатком. Сумма больше остатка —
    `PAYMENT_EXCEEDS_BALANCE_DUE`, ничего не записывается. Повтор идемпотентен: тот же `confirmation_id` с той же суммой и датой
    (платёжка уже подтверждена; другая сумма или дата — 409 `PAYMENT_REFERENCE_CONFLICT`), тот же `reference`, а по уже оплаченному счёту — та же сумма и дата возвращают прежний платёж.
    """
    from crm.services.billing import record_payment

    denied = _forbidden(actor)
    if denied:
        return None, denied
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update(of=("self",)).select_related("deal").filter(pk=invoice_id).first()
        if invoice is None:
            return None, "NOT_FOUND"
        confirmation = None
        if confirmation_id is not None:
            confirmation = (
                PaymentConfirmation.objects.select_for_update(of=("self",))
                .filter(pk=confirmation_id, invoice_id=invoice.pk)
                .select_related("payment")
                .first()
            )
            if confirmation is None:
                return None, "CONFIRMATION_NOT_FOUND"
            if confirmation.status == PaymentConfirmation.Status.CONFIRMED and confirmation.payment is not None:
                done = confirmation.payment
                # Тот же платёж — повтор; другая сумма или дата по уже подтверждённой платёжке — конфликт, как у референса.
                if done.amount == amount and done.paid_at == paid_at:
                    return Confirmed(done, True), None
                return None, "PAYMENT_REFERENCE_CONFLICT"
        if invoice.status_code == InvoiceStatusCode.PAID:
            last = invoice.payments.order_by("-id").first()
            if last is not None and last.amount == amount and last.paid_at == paid_at:
                return Confirmed(last, True), None
        if paid_at > today():
            return None, "PAYMENT_DATE_IN_FUTURE"
        ref = reference.strip() or (f"conf-{confirmation.pk}" if confirmation is not None else "")
        payment, err = record_payment(invoice.pk, actor, amount=amount, paid_at=paid_at, reference=ref)
        if err:
            return None, err
        assert payment is not None
        replayed = bool(getattr(payment, "idempotent_replay", False))
        if confirmation is not None:
            confirmation.status = PaymentConfirmation.Status.CONFIRMED
            confirmation.payment = payment
            confirmation.confirmed_by = actor
            confirmation.confirmed_at = timezone.now()
            confirmation.save(update_fields=["status", "payment", "confirmed_by", "confirmed_at"])
            if not payment.proof_file:
                Payment.objects.filter(pk=payment.pk).update(proof_file=confirmation.file.name)
                payment.refresh_from_db()
        return Confirmed(payment, replayed), None


def attach_confirmation(
    invoice_id: int,
    actor: CustomUser,
    *,
    file: Any,
    source: str,
    claimed_amount: Optional[Decimal] = None,
    claimed_date: Optional[date] = None,
    note: str = "",
) -> Tuple[Optional[PaymentConfirmation], Optional[str]]:
    """Бухгалтер прикладывает платёжку клиента (пришла по почте или в бот; из кабинета придёт сама, ERP-04)."""
    denied = _forbidden(actor)
    if denied:
        return None, denied
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update(of=("self",)).select_related("deal").filter(pk=invoice_id).first()
        if invoice is None:
            return None, "NOT_FOUND"
        if invoice.status_code not in OPEN_STATUSES:
            return None, "INVOICE_NOT_OPEN"
        confirmation = PaymentConfirmation.objects.create(
            invoice=invoice,
            source=source,
            file=file,
            original_name=(getattr(file, "name", "") or "")[:255],
            claimed_amount=claimed_amount,
            claimed_date=claimed_date,
            note=note.strip(),
            recorded_by=actor,
        )
        _log(
            invoice,
            actor,
            "payment_doc.attached",
            "Приложена платёжка клиента",
            f"Счёт {invoice.number}: платёжка ({confirmation.get_source_display()})",
            {"confirmation_id": confirmation.pk, "source": source},
        )
        return confirmation, None


def request_payment_doc(invoice_id: int, actor: CustomUser) -> Tuple[Optional[ActivityLog], Optional[str]]:
    """Отметить «платёжку запросили у клиента».

    Канала «ERP → клиент» для этого сообщения в main нет (клиент — контакт CRM, письма ERP уходят сотрудникам клиента,
    которых нет, FIX-13; бот пишет клиенту по событиям). Операция фиксирует запрос в журнале счёта; текст клиенту
    сотрудник отправляет через «Чаты». Автоотправка — событие шины и потребитель в CRM (хвост B-D24-1).
    """
    denied = _forbidden(actor)
    if denied:
        return None, denied
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update(of=("self",)).select_related("deal").filter(pk=invoice_id).first()
        if invoice is None:
            return None, "NOT_FOUND"
        if invoice.status_code not in OPEN_STATUSES:
            return None, "INVOICE_NOT_OPEN"
        _log(
            invoice,
            actor,
            "payment_doc.requested",
            "Запрошена платёжка у клиента",
            f"Счёт {invoice.number}: платёжка запрошена",
            {},
        )
        entry = last_doc_request(invoice)
        return entry, None


def pending_confirmations_count(invoice: Invoice) -> int:
    return invoice.confirmations.filter(status=PaymentConfirmation.Status.PENDING).count()


__all__ = [
    "DISPLAY_STATUSES",
    "OPEN_STATUSES",
    "TABS",
    "annotated",
    "attach_confirmation",
    "board",
    "confirm_payment",
    "counts",
    "display_status",
    "get_invoice",
    "history",
    "last_doc_request",
    "request_payment_doc",
    "today",
]
