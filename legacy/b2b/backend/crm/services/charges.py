"""КП charge-template logic — apply per-Incoterm charge profiles to a quote.

Self-contained service unit: selecting a delivery basis on a КП auto-creates the
template's expense items as editable QuoteCharge rows. Kept out of the (already
large) quotes.py service so the feature stays an isolated unit.
"""

from django.db import transaction

from crm.models import ChargeTemplate, Quote, QuoteCharge
from master_data.models import DeliveryBasis


def _seller_company_id_for(quote: Quote, actor):
    """The seller company whose templates apply — the company building the КП.

    Prefer the actor (the seller setting the basis), else the quote's preparer.
    Returns None → use the platform's global default templates.
    """
    from accounts.services.permissions import primary_seller_company_id

    if actor is not None:
        company_id = primary_seller_company_id(actor)
        if company_id:
            return company_id
    preparer = getattr(quote, "prepared_by", None)
    if preparer is not None:
        return primary_seller_company_id(preparer)
    return None


def apply_charge_template_to_quote(quote: Quote, actor=None) -> int:
    """
    Create QuoteCharge rows from the quote's delivery-basis template.

    Idempotent by charge_type: a type already present on the КП is skipped, so
    re-selecting the same basis (or switching back) never duplicates rows and
    never clobbers the seller's manual edits. Returns the number of rows created.
    """
    if not quote.delivery_basis_id:
        return 0

    # Scope to the seller company's own templates; fall back to the platform's
    # global defaults (company IS NULL) when the company has none for this basis.
    company_id = _seller_company_id_for(quote, actor)
    by_basis = ChargeTemplate.objects.filter(delivery_basis_id=quote.delivery_basis_id, is_active=True)
    own = by_basis.filter(company_id=company_id) if company_id else by_basis.none()
    templates = own if own.exists() else by_basis.filter(company__isnull=True)

    existing_type_ids = set(quote.charges.values_list("charge_type_id", flat=True))
    templates = templates.exclude(charge_type_id__in=existing_type_ids).select_related("charge_type")

    created = 0
    for template in templates:
        charge = QuoteCharge(
            quote=quote,
            charge_type=template.charge_type,
            amount=template.default_amount,
            rate_percent=template.default_rate_percent,
            is_deduction=template.is_deduction,
            from_template=True,
            created_by=actor,
        )
        # Batch insert; recalc once at the end instead of per-row.
        charge.save(skip_recalculate=True)
        created += 1

    if created:
        quote.recalculate_totals()
    return created


@transaction.atomic
def set_quote_delivery_basis(quote_id: int, basis_id, actor):
    """
    Set the КП delivery basis (seller action) and auto-apply its charge template.

    Returns (quote, None) on success or (None, error_code). Thin service the
    viewset calls — keeps the endpoint a wrapper (Rule 8).
    """
    from accounts.services.permissions import is_platform_admin_viewer, is_seller

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    if not (getattr(actor, "is_superuser", False) or is_seller(actor)):
        return None, "ONLY_SELLER_CAN_BUILD_QUOTE"

    quote = Quote.objects.select_for_update().get(pk=quote_id)
    if quote.frozen_at:
        return None, "QUOTE_FROZEN"

    basis = None
    if basis_id:
        basis = DeliveryBasis.objects.filter(pk=basis_id).first()
        if not basis:
            return None, "DELIVERY_BASIS_NOT_FOUND"

    quote.delivery_basis = basis
    quote.save(update_fields=["delivery_basis", "updated_at"])
    apply_charge_template_to_quote(quote, actor)
    # Re-cost the lines under the NEW Incoterm: per-line freight/customs are gated by the
    # basis flags (M1), so switching basis must recompute or a now-hidden cost ghosts into
    # the total (audit M2). recalculate_quote also refreshes charges_total + VAT.
    from .quotes import QuoteCalculationService

    QuoteCalculationService.recalculate_quote(quote_id)
    quote.refresh_from_db()
    return quote, None
