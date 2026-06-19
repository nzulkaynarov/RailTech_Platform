from typing import Optional, Tuple

from django.db import IntegrityError, transaction

from accounts.models import CustomUser

from ..constants import ActStatusCode, ContractStatusCode, InvoiceStatusCode
from ..models import ActivityLog
from ._params import PaymentData

# ──────────────────────────────────────────────────────────────────────────
# Invoices, Payments, Acts
# ──────────────────────────────────────────────────────────────────────────


def _next_invoice_number() -> str:
    # Race-safe per-year counter (was count()+1 → duplicate-number 500 under load).
    from .numbering import next_document_number

    return next_document_number("INV", "INV")


def _next_act_number() -> str:
    from .numbering import next_document_number

    return next_document_number("ACT", "ACT")


@transaction.atomic
def generate_invoice_from_contract(
    contract_id: int,
    actor: Optional[CustomUser] = None,
    due_days: int = 14,
) -> Tuple[Optional["Invoice"], Optional[str]]:  # noqa: F821
    from datetime import timedelta

    from django.utils import timezone

    from accounts.services import assert_seller_can_operate, is_platform_admin_viewer, is_seller

    from ..models import Contract, Invoice, InvoiceItem

    if actor is not None and is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    # Issuing the invoice is a seller-side action.
    if actor is not None and not (getattr(actor, "is_superuser", False) or is_seller(actor)):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    # Paid-seller gate (skipped for the actor=None automation path).
    if actor is not None and (sub_err := assert_seller_can_operate(actor)):
        return None, sub_err
    contract = Contract.objects.select_related("quote__deal").get(pk=contract_id)

    if contract.status != ContractStatusCode.SIGNED:
        return None, "INVOICE_REQUIRES_SIGNED_CONTRACT"

    # Idempotency: one signed contract yields one invoice. Re-issuing would
    # double-count receivables. Return the existing invoice instead.
    existing_invoice = Invoice.objects.filter(contract=contract).first()
    if existing_invoice is not None:
        return existing_invoice, None

    quote = contract.quote
    invoice = Invoice.objects.create(
        deal=contract.deal,
        contract=contract,
        number=_next_invoice_number(),
        status=InvoiceStatusCode.ISSUED,
        issued_at=timezone.now().date(),
        due_date=(timezone.now() + timedelta(days=due_days)).date(),
        subtotal_excl_vat=quote.subtotal_excl_vat,
        vat_amount=quote.vat_amount,
        total_incl_vat=quote.total_incl_vat,
        currency=quote.items.first().frozen_currency if quote.items.exists() else None,
        created_by=actor,
    )

    for qi in quote.items.select_related("product").all():
        InvoiceItem.objects.create(
            invoice=invoice,
            description=(qi.product.name if qi.product else qi.imported_raw_name) or "Позиция",
            quantity=qi.quantity,
            unit_price_excl_vat=qi.final_price_excl_vat,
            line_total_excl_vat=(qi.final_price_excl_vat * qi.quantity),
            source_quote_item=qi,
        )

    _render_invoice_pdf(invoice)
    ActivityLog.objects.create(
        action="Инвойс выставлен",
        detail=f"Инвойс {invoice.number} по сделке #{invoice.deal_id}",
        user=actor,
        level="INFO",
    )
    return invoice, None


def _render_invoice_pdf(invoice) -> None:
    from io import BytesIO

    from django.core.files.base import ContentFile
    from django.template.loader import render_to_string
    from weasyprint import HTML

    html_string = render_to_string(
        "crm/invoice_pdf.html",
        {
            "invoice": invoice,
            "items": invoice.items.select_related("source_quote_item").all(),
            "company": invoice.deal.company,
        },
    )
    buf = BytesIO()
    HTML(string=html_string).write_pdf(buf)
    invoice.pdf_file.save(f"Invoice_{invoice.number}.pdf", ContentFile(buf.getvalue()), save=True)


@transaction.atomic
def record_payment(
    payment_data_or_invoice_id,
    actor: CustomUser,
    amount=None,
    paid_at=None,
    method: str = "BANK_TRANSFER",
    reference: str = "",
    proof_file=None,
    manual: bool = True,
) -> Tuple[Optional[object], Optional[str]]:
    """Record payment against an invoice.

    Accepts either a PaymentData dataclass or positional/keyword args for
    backwards compatibility. New callers should prefer PaymentData.

    NOTE: manual=True marks the record as hand-entered (no payment-provider webhook).
    Logged with [MANUAL_MODE] tag in ActivityLog -- needed for later reconciliation
    once Click/Payme/Stripe webhooks replace the manual flow. See memory
    `tech_debt_payment_esign.md`.
    """
    # Unpack PaymentData if provided
    if isinstance(payment_data_or_invoice_id, PaymentData):
        pd = payment_data_or_invoice_id
        invoice_id = pd.invoice_id
        amount = pd.amount
        paid_at = pd.paid_at
        method = pd.method
        reference = pd.reference
        proof_file = pd.proof_file
        manual = pd.manual
    else:
        invoice_id = payment_data_or_invoice_id

    from decimal import Decimal as D

    from accounts.services import is_member_of, is_platform_admin_viewer

    from ..models import Invoice, Payment

    invoice = Invoice.objects.select_for_update().select_related("deal").get(pk=invoice_id)
    # Actor-guard: platform-admin viewer cannot execute business actions.
    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    # Payment is recorded by the buyer side of the deal -- must be member w/ can_buy.
    if not (getattr(actor, "is_superuser", False) or is_member_of(actor, invoice.deal.company_id, capability="buy")):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if invoice.status in {InvoiceStatusCode.CANCELLED}:
        return None, "INVOICE_CANCELLED"
    amount_d = D(str(amount))
    if amount_d <= 0:
        return None, "PAYMENT_AMOUNT_MUST_BE_POSITIVE"

    if proof_file:
        from core.validators import validate_document_upload

        validate_document_upload(proof_file)

    # Idempotency: a bank reference uniquely identifies a real-world payment.
    # A double-submit with the same reference must not be counted twice.
    if reference:
        existing = Payment.objects.filter(invoice=invoice, reference=reference).first()
        if existing is not None:
            return existing, None

    try:
        # Savepoint so a unique-constraint hit (concurrent same-reference
        # insert that slipped past the check above) rolls back cleanly without
        # poisoning the outer transaction.
        with transaction.atomic():
            payment = Payment.objects.create(
                invoice=invoice,
                amount=amount_d,
                method=method,
                paid_at=paid_at,
                reference=reference,
                proof_file=proof_file,
                recorded_by=actor,
            )
    except IntegrityError:
        existing = Payment.objects.filter(invoice=invoice, reference=reference).first()
        if existing is not None:
            return existing, None
        raise

    invoice.amount_paid = (invoice.amount_paid or D("0")) + amount_d
    if invoice.amount_paid >= invoice.total_incl_vat:
        invoice.status = InvoiceStatusCode.PAID
    else:
        invoice.status = InvoiceStatusCode.PARTIAL
    invoice.save(update_fields=["amount_paid", "status", "updated_at"])

    marker = "[MANUAL_MODE] " if manual else ""
    ActivityLog.objects.create(
        action=f"{marker}Зафиксирован платёж",
        detail=f"Инвойс {invoice.number}: получено {amount_d} (итого {invoice.amount_paid}/{invoice.total_incl_vat})",
        user=actor,
        level="SUCCESS",
    )
    return payment, None


@transaction.atomic
def generate_act(
    invoice_id: int,
    actor: Optional[CustomUser] = None,
) -> Tuple[Optional[object], Optional[str]]:
    from django.utils import timezone

    from accounts.services import assert_seller_can_operate, is_platform_admin_viewer, is_seller

    from ..models import Act, Invoice

    if actor is not None and is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    # Issuing the act (acceptance certificate) is a seller-side action.
    if actor is not None and not (getattr(actor, "is_superuser", False) or is_seller(actor)):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    # Paid-seller gate (skipped for the actor=None automation path).
    if actor is not None and (sub_err := assert_seller_can_operate(actor)):
        return None, sub_err
    invoice = Invoice.objects.select_related("contract", "deal").get(pk=invoice_id)
    if invoice.status not in {InvoiceStatusCode.PAID, InvoiceStatusCode.PARTIAL, InvoiceStatusCode.ISSUED}:
        return None, "ACT_INVALID_INVOICE_STATUS"

    act = Act.objects.create(
        deal=invoice.deal,
        contract=invoice.contract,
        invoice=invoice,
        number=_next_act_number(),
        status=ActStatusCode.ISSUED,
        issued_at=timezone.now().date(),
        total_amount=invoice.total_incl_vat,
        created_by=actor,
    )
    _render_act_pdf(act)
    return act, None


def _render_act_pdf(act) -> None:
    from io import BytesIO

    from django.core.files.base import ContentFile
    from django.template.loader import render_to_string
    from weasyprint import HTML

    html_string = render_to_string(
        "crm/act_pdf.html",
        {
            "act": act,
            "invoice": act.invoice,
            "company": act.deal.company,
        },
    )
    buf = BytesIO()
    HTML(string=html_string).write_pdf(buf)
    act.pdf_file.save(f"Act_{act.number}.pdf", ContentFile(buf.getvalue()), save=True)


@transaction.atomic
def sign_act(act_id: int, actor: CustomUser, signed_file=None) -> Tuple[Optional[object], Optional[str]]:
    from django.utils import timezone

    from accounts.services import is_platform_admin_viewer

    from ..models import Act

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    act = Act.objects.select_for_update().get(pk=act_id)
    if act.status != ActStatusCode.ISSUED:
        return None, "ACT_SIGN_NOT_ALLOWED"
    act.status = ActStatusCode.SIGNED
    act.signed_at = timezone.now()
    if signed_file is not None:
        act.signed_file = signed_file
    act.save(update_fields=["status", "signed_at", "signed_file", "updated_at"])
    return act, None
