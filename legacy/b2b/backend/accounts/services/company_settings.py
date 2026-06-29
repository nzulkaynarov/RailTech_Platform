"""Company Settings service — the КП defaults + document-numbering scheme a selling
company configures once (OWNER-gated, tenant-scoped to the actor's OWN company).

Rule 8: all business logic (the OWNER-of-own-company gate, the get-or-create, the
field whitelist + FK-by-code resolution) lives here. The view is a thin wrapper that
authorizes the request only by handing the object + actor to these functions.
"""

import logging
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

from ..models import Company, CompanySettings, CustomUser
from .document_profile import is_company_owner

logger = logging.getLogger(__name__)

# Scalar fields the OWNER may flat-write. FK fields (delivery_basis / cost_currency)
# are resolved by CODE separately; `company` / timestamps are immutable.
_DECIMAL_FIELDS = ("default_vat_rate", "default_margin_percent", "min_margin_percent", "target_margin_percent")
_TEXT_FIELDS = ("doc_number_prefix",)


def get_company_settings(company: Company) -> CompanySettings:
    """The company's КП-defaults + numbering settings (get-or-create via the accessor)."""
    return company.settings


def _resolve_currency(code: str):
    from master_data.models import Currency

    return Currency.objects.filter(code=(code or "").strip().upper()).first()


def _resolve_basis(code: str):
    from master_data.models import DeliveryBasis

    return DeliveryBasis.objects.filter(code=(code or "").strip().upper()).first()


def update_company_settings(
    user: "CustomUser", company: Company, data: dict
) -> Tuple[Optional[CompanySettings], Optional[str]]:
    """OWNER updates THEIR OWN company's КП defaults + numbering prefix.

    Returns (settings, error_code). Currencies / delivery basis are accepted as CODES
    (e.g. "USD", "FCA"); an empty string clears the FK. Numeric defaults accept null to
    clear. Refuses with NOT_COMPANY_OWNER when the actor doesn't own this company, and
    BAD_* on an unparseable value. Only whitelisted fields are written.
    """
    if not is_company_owner(user, company):
        return None, "NOT_COMPANY_OWNER"
    settings_row = get_company_settings(company)
    changed = []

    if "default_cost_currency" in data:
        code = data.get("default_cost_currency")
        if code in (None, ""):
            settings_row.default_cost_currency = None
        else:
            currency = _resolve_currency(code)
            if currency is None:
                return None, "BAD_CURRENCY"
            settings_row.default_cost_currency = currency
        changed.append("default_cost_currency")

    if "default_delivery_basis" in data:
        code = data.get("default_delivery_basis")
        if code in (None, ""):
            settings_row.default_delivery_basis = None
        else:
            basis = _resolve_basis(code)
            if basis is None:
                return None, "BAD_DELIVERY_BASIS"
            settings_row.default_delivery_basis = basis
        changed.append("default_delivery_basis")

    for field in _DECIMAL_FIELDS:
        if field in data:
            raw = data.get(field)
            if raw in (None, ""):
                setattr(settings_row, field, None)
            else:
                try:
                    setattr(settings_row, field, Decimal(str(raw)))
                except (InvalidOperation, ValueError):
                    return None, "BAD_NUMBER"
            changed.append(field)

    if "default_offer_validity_days" in data:
        raw = data.get("default_offer_validity_days")
        if raw in (None, ""):
            settings_row.default_offer_validity_days = None
        else:
            try:
                days = int(raw)
            except (TypeError, ValueError):
                return None, "BAD_NUMBER"
            if days < 0:
                return None, "BAD_NUMBER"
            settings_row.default_offer_validity_days = days
        changed.append("default_offer_validity_days")

    for field in _TEXT_FIELDS:
        if field in data:
            value = (data.get(field) or "").strip()[:16]
            if field == "doc_number_prefix" and value:
                # The prefix is the GLOBAL discriminator that keeps per-company document numbers
                # (ACME-КП-2026-00001, ACME-CT-2026-00001 …) from colliding on the globally-unique
                # `number`. Two companies sharing a prefix would each mint the same string → an
                # IntegrityError 500 on the second send (audit M1). Enforce case-insensitive
                # uniqueness across companies before accepting it.
                clash = (
                    CompanySettings.objects.filter(doc_number_prefix__iexact=value)
                    .exclude(company_id=company.id)
                    .exists()
                )
                if clash:
                    return None, "DOC_PREFIX_TAKEN"
            setattr(settings_row, field, value)
            changed.append(field)

    if changed:
        settings_row.save(update_fields=[*changed, "updated_at"])
    return settings_row, None
