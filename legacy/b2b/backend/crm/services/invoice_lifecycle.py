"""Invoice DRAFT lifecycle (Wave C — ERP draft→posted split).

An invoice is born a DRAFT (see ``billing.generate_invoice_from_contract``). These services take it
through its lifecycle: edit while DRAFT (due_date / notes), explicitly ISSUE (renders the PDF,
notifies the buyer), or CANCEL (never once paid). Split out of ``billing.py`` to keep that file
under the 500-line cap; the numbering / PDF-render helpers still live there and are imported here.
"""

from typing import Optional, Tuple

from django.db import transaction

from notifications.services import spa_link

from ..constants import InvoiceStatusCode
from ..models import ActivityLog
from .billing import _istatus


def _notify_invoice_issued_to_buyer(invoice) -> None:
    """Alert the BUYER team that the invoice is now issued (payable). FK→deal so the deep-link
    derives from it, matching the platform's notification convention."""
    from .deal_notifications import buyer_team_user_ids, notify_deal_users

    deal = invoice.deal
    notify_deal_users(
        buyer_team_user_ids(deal),
        deal=deal,
        title="Инвойс выставлен",
        message=f"По сделке #{deal.pk} выставлен инвойс {invoice.number} к оплате",
        # Точная ссылка вместо реестра: раньше человек попадал в общий список счетов и искал
        # там тот, о котором его известили.
        link=spa_link("invoices", invoice.id),
        type_code="INFO",
    )


def notify_seller_invoice_draft(invoice) -> None:
    """Alert the routed seller team that an invoice DRAFT was auto-created on deal win — they must
    review it and explicitly issue it (владелец не теряет контроль; ERP canon). FK→deal."""
    from .deal_notifications import notify_deal_users, seller_team_user_ids

    deal = invoice.deal
    notify_deal_users(
        seller_team_user_ids(deal),
        deal=deal,
        title="Инвойс создан черновиком",
        message=f"По сделке #{deal.pk} создан инвойс {invoice.number} — проверьте и выставьте",
        link=spa_link("invoices", invoice.id),
        type_code="INFO",
    )


def _assert_seller_may_act_on_invoice(invoice, user) -> Optional[str]:
    """Shared seller-side gate for invoice lifecycle actions (issue / cancel): viewer-block,
    seller-role, routing-scope. Returns an error code or None."""
    from accounts.services import is_platform_admin_viewer, is_seller, seller_company_routed_to_deal

    if is_platform_admin_viewer(user):
        return "ADMIN_VIEWER_CANNOT_ACT"
    if not (getattr(user, "is_superuser", False) or is_seller(user)):
        return "MEMBER_REQUIRED_FOR_ACTION"
    if not getattr(user, "is_superuser", False) and not seller_company_routed_to_deal(user, invoice.deal_id):
        return "MEMBER_REQUIRED_FOR_ACTION"
    return None


@transaction.atomic
def issue_invoice(invoice, user) -> Tuple[Optional[object], Optional[str]]:
    """Issue a DRAFT invoice → ISSUED: stamps the issue date, renders the PDF off-thread and
    notifies the buyer. Seller-side action; only DRAFT invoices can be issued."""
    from django.utils import timezone

    from accounts.services import assert_seller_can_operate

    if gate_err := _assert_seller_may_act_on_invoice(invoice, user):
        return None, gate_err
    if sub_err := assert_seller_can_operate(user):
        return None, sub_err
    if invoice.status_code != InvoiceStatusCode.DRAFT:
        return None, "INVOICE_ALREADY_ISSUED"

    invoice.status = _istatus(InvoiceStatusCode.ISSUED)
    invoice.issued_at = timezone.now().date()
    invoice.save(update_fields=["status", "issued_at", "updated_at"])

    # Render off the request thread, after commit (F1.6 — avoids orphan PDFs on rollback).
    from ..tasks import render_document_pdf

    invoice_id = invoice.id
    transaction.on_commit(lambda: render_document_pdf.delay("invoice", invoice_id))
    ActivityLog.objects.create(
        action="Инвойс выставлен",
        detail=f"Инвойс {invoice.number} по сделке #{invoice.deal_id}",
        event_code="invoice.issued",
        event_params={"number": invoice.number, "deal_id": invoice.deal_id},
        user=user,
        level="INFO",
        deal=invoice.deal,
        company_id=invoice.deal.company_id,
    )
    _notify_invoice_issued_to_buyer(invoice)
    return invoice, None


@transaction.atomic
def cancel_invoice(invoice, user) -> Tuple[Optional[object], Optional[str]]:
    """Cancel an invoice → CANCELLED. Seller-side. A paid / partially-paid invoice can NOT be
    cancelled (money already moved). Drops any cached PDF so a stale copy can't be downloaded."""
    from decimal import Decimal as D

    if gate_err := _assert_seller_may_act_on_invoice(invoice, user):
        return None, gate_err
    if invoice.status_code == InvoiceStatusCode.CANCELLED:
        return None, "INVOICE_ALREADY_CANCELLED"
    if (invoice.amount_paid or D("0")) > 0 or invoice.status_code in {
        InvoiceStatusCode.PAID,
        InvoiceStatusCode.PARTIAL,
    }:
        return None, "INVOICE_CANNOT_CANCEL_PAID"

    invoice.status = _istatus(InvoiceStatusCode.CANCELLED)
    if invoice.pdf_file:
        invoice.pdf_file.delete(save=False)
    invoice.save(update_fields=["status", "pdf_file", "updated_at"])
    ActivityLog.objects.create(
        action="Инвойс отменён",
        detail=f"Инвойс {invoice.number} по сделке #{invoice.deal_id}",
        event_code="invoice.cancelled",
        event_params={"number": invoice.number, "deal_id": invoice.deal_id},
        user=user,
        level="WARNING",
        deal=invoice.deal,
        company_id=invoice.deal.company_id,
    )
    return invoice, None


@transaction.atomic
def update_invoice_draft(invoice, user, *, due_date=None, notes=None) -> Tuple[Optional[object], Optional[str]]:
    """Edit a DRAFT invoice's due_date / notes. Amounts are NEVER hand-edited — they mirror the
    contract/КП (Rule 1). Only DRAFT invoices are editable; ISSUED+ are immutable (trust).

    Seller-side only: the same gate as issue/cancel (viewer-block + seller-role + routing-scope).
    Closes the hole where the buyer (both sides land in the invoice queryset) or a platform-admin
    viewer could rewrite another seller's draft due_date / notes."""
    if gate_err := _assert_seller_may_act_on_invoice(invoice, user):
        return None, gate_err
    if invoice.status_code != InvoiceStatusCode.DRAFT:
        return None, "INVOICE_NOT_EDITABLE"

    update_fields = ["updated_at"]
    if due_date is not None:
        invoice.due_date = due_date
        update_fields.append("due_date")
    if notes is not None:
        invoice.notes = notes
        update_fields.append("notes")
    invoice.save(update_fields=update_fields)
    return invoice, None
