"""Схемы «Счетов и оплат» бухгалтера (D2-4). Ответы собирают функции `*_row`/`card` из `finance.services.receivables`;
классы описывают форму для OpenAPI (`erp-internal.yaml`) и проверяют ввод. Себестоимости и маржи в схемах нет."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from finance.models import Invoice, Payment, PaymentConfirmation
from finance.services import receivables
from rest_framework import serializers

_DISPLAY = serializers.ChoiceField(choices=receivables.DISPLAY_STATUSES)


class ReceivableRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    deal_id = serializers.IntegerField()
    deal_title = serializers.CharField(allow_blank=True)
    deal_year = serializers.IntegerField(
        help_text="Год создания сделки: из него и id BFF составляет номер ЗВ/ПР (ERP-09)."
    )
    client_id = serializers.IntegerField()
    client_name = serializers.CharField()
    currency = serializers.CharField(allow_null=True)
    total_incl_vat = serializers.DecimalField(max_digits=14, decimal_places=2)
    amount_paid = serializers.DecimalField(max_digits=14, decimal_places=2)
    balance_due = serializers.DecimalField(max_digits=14, decimal_places=2)
    issued_at = serializers.DateField(allow_null=True)
    due_date = serializers.DateField(allow_null=True)
    status = serializers.CharField(help_text="Код статуса счёта ERP: DRAFT, ISSUED, PARTIAL, PAID, OVERDUE, CANCELLED.")
    display_status = _DISPLAY
    is_overdue = serializers.BooleanField(
        help_text="Срок оплаты прошёл, остаток есть (вычисляется по сроку, не хранится)."
    )
    days_overdue = serializers.IntegerField(allow_null=True)
    has_pending_proof = serializers.BooleanField(
        help_text="Есть платёжка клиента, которую бухгалтер ещё не подтвердил."
    )
    proof_received_at = serializers.DateTimeField(allow_null=True)


class ReceivableCountsSerializer(serializers.Serializer):
    to_issue = serializers.IntegerField()
    awaiting = serializers.IntegerField()
    proofs = serializers.IntegerField()
    overdue = serializers.IntegerField()


class ReceivableBoardSerializer(serializers.Serializer):
    tab = serializers.ChoiceField(choices=receivables.TABS)
    count = serializers.IntegerField(help_text="Всего счетов на вкладке.")
    counts = ReceivableCountsSerializer(help_text="Счета на каждой вкладке (вкладки не пересекаются).")
    results = ReceivableRowSerializer(many=True)


class ReceivableItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    description = serializers.CharField()
    quantity = serializers.IntegerField()
    unit_price_excl_vat = serializers.DecimalField(max_digits=14, decimal_places=2)
    line_total_excl_vat = serializers.DecimalField(max_digits=14, decimal_places=2)


class ReceivablePaymentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid_at = serializers.DateField()
    method = serializers.CharField()
    reference = serializers.CharField(allow_blank=True)
    receipt_number = serializers.CharField(allow_blank=True)
    has_proof = serializers.BooleanField()
    recorded_by = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()


class ReceivableConfirmationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    source = serializers.ChoiceField(choices=[c.value for c in PaymentConfirmation.Source])
    status = serializers.ChoiceField(choices=[c.value for c in PaymentConfirmation.Status])
    original_name = serializers.CharField(allow_blank=True)
    claimed_amount = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    claimed_date = serializers.DateField(allow_null=True)
    note = serializers.CharField(allow_blank=True)
    received_at = serializers.DateTimeField()
    recorded_by = serializers.CharField(
        allow_null=True, help_text="Кто приложил: сотрудник; пусто — клиент (кабинет, бот)."
    )
    payment_id = serializers.IntegerField(allow_null=True)


class ReceivableHistorySerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    code = serializers.CharField()
    text = serializers.CharField()
    by = serializers.CharField(allow_null=True)


class ReceivableCardSerializer(ReceivableRowSerializer):
    subtotal_excl_vat = serializers.DecimalField(max_digits=14, decimal_places=2)
    vat_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    notes = serializers.CharField(allow_blank=True)
    has_pdf = serializers.BooleanField()
    items = ReceivableItemSerializer(many=True)
    payments = ReceivablePaymentSerializer(many=True)
    confirmations = ReceivableConfirmationSerializer(many=True)
    history = ReceivableHistorySerializer(many=True)
    payment_doc_requested_at = serializers.DateTimeField(allow_null=True)
    can_confirm = serializers.BooleanField(help_text="Сотрудник вправе подтвердить оплату, счёт открыт и остаток есть.")
    can_attach_proof = serializers.BooleanField()
    can_request_proof = serializers.BooleanField()
    replayed = serializers.BooleanField(help_text="Повтор подтверждения: платёж уже был записан, ничего не добавлено.")


class ConfirmPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, help_text="Сумма по выписке; не больше остатка.")
    paid_at = serializers.DateField(help_text="Дата поступления по выписке; не позже сегодняшней.")
    reference = serializers.CharField(
        required=False, allow_blank=True, max_length=255, default="", help_text="Номер операции банка."
    )
    confirmation_id = serializers.IntegerField(
        required=False, allow_null=True, default=None, help_text="Платёжка клиента, которую подтверждает платёж."
    )


class AttachConfirmationSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="Платёжное поручение: PDF, изображение или документ, до 20 МБ.")
    source = serializers.ChoiceField(
        choices=[c.value for c in PaymentConfirmation.Source],
        default=PaymentConfirmation.Source.MANUAL.value,
        required=False,
    )
    claimed_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True, default=None
    )
    claimed_date = serializers.DateField(required=False, allow_null=True, default=None)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")


def _name(user: Any) -> str | None:
    if user is None:
        return None
    return (user.get_full_name() or user.email or "").strip() or None


def row(invoice: Invoice, day: date | None = None) -> dict[str, Any]:
    """Строка таблицы по счёту из `receivables.annotated()` (с `has_proof` и `proof_at`)."""
    day = day or receivables.today()
    has_proof = bool(getattr(invoice, "has_proof", False))
    display = receivables.display_status(invoice, has_proof, day)
    balance = Decimal(invoice.balance_due)
    overdue = display == "overdue"
    deal = invoice.deal
    return {
        "id": invoice.pk,
        "number": invoice.number,
        "deal_id": deal.pk,
        "deal_title": deal.title or "",
        "deal_year": deal.created_at.year,
        "client_id": deal.company_id,
        "client_name": deal.company.name if deal.company_id else "",
        "currency": invoice.currency.code if invoice.currency_id else None,
        "total_incl_vat": invoice.total_incl_vat,
        "amount_paid": invoice.amount_paid,
        "balance_due": balance,
        "issued_at": invoice.issued_at,
        "due_date": invoice.due_date,
        "status": invoice.status_code or "",
        "display_status": display,
        "is_overdue": overdue,
        "days_overdue": (day - invoice.due_date).days if overdue and invoice.due_date else None,
        "has_pending_proof": has_proof,
        "proof_received_at": getattr(invoice, "proof_at", None),
    }


def card(invoice: Invoice, *, may_pay: bool, replayed: bool = False) -> dict[str, Any]:
    day = receivables.today()
    data = row(invoice, day)
    open_invoice = invoice.status_code in receivables.OPEN_STATUSES
    last_request = receivables.last_doc_request(invoice)
    payments: list[Payment] = list(invoice.payments.select_related("recorded_by").order_by("paid_at", "id"))
    data.update(
        {
            "subtotal_excl_vat": invoice.subtotal_excl_vat,
            "vat_amount": invoice.vat_amount,
            "notes": invoice.notes or "",
            "has_pdf": bool(invoice.pdf_file),
            "items": [
                {
                    "id": item.pk,
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit_price_excl_vat": item.unit_price_excl_vat,
                    "line_total_excl_vat": item.line_total_excl_vat,
                }
                for item in invoice.items.all()
            ],
            "payments": [
                {
                    "id": p.pk,
                    "amount": p.amount,
                    "paid_at": p.paid_at,
                    "method": p.method,
                    "reference": p.reference,
                    "receipt_number": p.receipt_number,
                    "has_proof": bool(p.proof_file),
                    "recorded_by": _name(p.recorded_by),
                    "created_at": p.created_at,
                }
                for p in payments
            ],
            "confirmations": [
                {
                    "id": c.pk,
                    "source": c.source,
                    "status": c.status,
                    "original_name": c.original_name,
                    "claimed_amount": c.claimed_amount,
                    "claimed_date": c.claimed_date,
                    "note": c.note,
                    "received_at": c.received_at,
                    "recorded_by": _name(c.recorded_by),
                    "payment_id": c.payment_id,
                }
                for c in invoice.confirmations.select_related("recorded_by").order_by("received_at", "id")
            ],
            "history": [
                {"at": e.timestamp, "code": e.event_code, "text": e.action, "by": _name(e.user)}
                for e in receivables.history(invoice)
            ],
            "payment_doc_requested_at": last_request.timestamp if last_request else None,
            "can_confirm": may_pay and open_invoice and Decimal(invoice.balance_due) > 0,
            "can_attach_proof": may_pay and open_invoice,
            "can_request_proof": may_pay and open_invoice,
            "replayed": replayed,
        }
    )
    return data
