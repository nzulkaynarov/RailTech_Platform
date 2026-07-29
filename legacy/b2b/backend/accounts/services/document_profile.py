"""Company Document Profile service — the branded requisites a selling company prints
on its OWN commercial documents (КП, договор).

Rule 8: all business logic (the OWNER-of-own-company gate, the get-or-create, the
field whitelist, the logo upload + validation) lives here. The view is a thin wrapper
that authorizes the request only by handing the object + actor to these functions.
"""

import logging
from typing import Optional, Tuple

from django.core.exceptions import ValidationError as DjangoValidationError

from core.validators import is_hex_color, validate_image_upload

from ..models import Company, CompanyDocumentProfile, CustomUser

logger = logging.getLogger(__name__)

# The textual requisites the OWNER may flat-write. `logo` is uploaded separately
# (multipart), `company` / timestamps are immutable — never accept them from the body.
_EDITABLE_FIELDS = (
    "legal_name",
    "inn",
    "legal_address",
    "bank_details",
    "signatory_name",
    "signatory_position",
    "footer_text",
    "accent_color",
    "secondary_color",
    "cover_letter_text",
)

# Theme choice fields (D2, Odoo Document Layout model) — validated against the model's
# choice sets, never written raw (a bad value would land in a PDF <style>/class attr).
_EDITABLE_CHOICE_FIELDS = {
    "layout_preset": {code for code, _label in CompanyDocumentProfile.LAYOUT_CHOICES},
    "font_family": {code for code, _label in CompanyDocumentProfile.FONT_CHOICES},
}

# Layout toggles (P3) — coerced to bool, so a False value isn't turned into "" like the text fields.
_EDITABLE_BOOL_FIELDS = (
    "use_company_defaults",
    "show_logo",
    "show_lead_time",
    "show_fx_note",
    "show_cover_letter",
    "show_bank_in_header",
)


def is_company_owner(user: "CustomUser", company: Company) -> bool:
    """True if `user` may manage `company`'s org-admin config (document profile, КП defaults,
    numbering). ADR-0005 U2: gated on the `settings.edit` CompanyRole PERMISSION — not the OWNER
    WorkspaceRole — so a delegated «Администратор компании» can manage it, not only the founder.
    member_has_permission already returns True for the OWNER (is_system role / legacy OWNER
    short-circuit) and False for a regular member (settings.edit ∈ _ADMIN_PERMS), so this stays
    a strict tenant-scoped gate. Platform admin / superuser pass for moderation/support.
    (Name kept for call-site stability; semantics widened from owner-only to settings.edit.)
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
        return True
    from .permissions import member_has_permission

    return member_has_permission(user, company.id, "settings.edit")


def get_document_profile(company: Company) -> CompanyDocumentProfile:
    """The company's branded document profile (get-or-create via the model accessor)."""
    return company.document_profile


def update_document_profile(
    user: "CustomUser", company: Company, data: dict
) -> Tuple[Optional[CompanyDocumentProfile], Optional[str]]:
    """OWNER updates THEIR OWN company's document requisites. Returns (profile, error_code).

    Only the whitelisted textual fields are written; logo / company / timestamps are
    ignored. Refuses with NOT_COMPANY_OWNER when the actor doesn't own this company.
    """
    if not is_company_owner(user, company):
        return None, "NOT_COMPANY_OWNER"
    # SEC (audit #9): accent/secondary colours are interpolated raw into a <style> block in
    # the PDF templates, so an unvalidated value ("red;background:url(http://10.0.0.2)") is
    # CSS injection → WeasyPrint SSRF/LFI on render. Reject anything but a #hex colour.
    accent = data.get("accent_color")
    if accent not in (None, "") and not is_hex_color(accent):
        return None, "INVALID_ACCENT_COLOR"
    secondary = data.get("secondary_color")
    if secondary not in (None, "") and not is_hex_color(secondary):
        return None, "INVALID_SECONDARY_COLOR"
    for field, allowed in _EDITABLE_CHOICE_FIELDS.items():
        if field in data and data[field] not in allowed:
            return None, f"INVALID_{field.upper()}"
    profile = get_document_profile(company)
    changed = []
    for field in _EDITABLE_FIELDS:
        if field in data:
            setattr(profile, field, data[field] or "")
            changed.append(field)
    for field in _EDITABLE_CHOICE_FIELDS:
        if field in data:
            setattr(profile, field, data[field])
            changed.append(field)
    for field in _EDITABLE_BOOL_FIELDS:
        if field in data:
            setattr(profile, field, _as_bool(data[field]))
            changed.append(field)
    if changed:
        profile.save(update_fields=[*changed, "updated_at"])
        _invalidate_branded_pdfs(company)
    return profile, None


def _invalidate_branded_pdfs(company: Company) -> None:
    """Brand/theme edits must re-render still-mutable cached PDFs (Odoo model: a report is a
    VIEW of live data — our pdf_file is only a cache of it).

    Cleared (lazily re-rendered with the new brand on next download / render task):
      • Quote — unfrozen only (a frozen КП is the client-received snapshot, PandaDoc model);
      • Contract — until SIGNED (a signed contract is a legal artifact);
      • Act / Invoice — DRAFT only (ISSUED docs are what the buyer received).
    Files are left in storage (same as every other invalidate-on-write path). Local import —
    accounts must not import crm at module load.
    """
    from crm.constants import ActStatusCode, ContractStatusCode, InvoiceStatusCode
    from crm.models import Act, Contract, Invoice, Quote

    Quote.objects.filter(seller_company=company, frozen_at__isnull=True).exclude(pdf_file="").update(pdf_file="")
    Contract.objects.filter(
        quote__seller_company=company,
        status__code__in=[
            ContractStatusCode.DRAFT,
            ContractStatusCode.PENDING_CLIENT,
            ContractStatusCode.PENDING_MANAGER,
        ],
    ).exclude(pdf_file="").update(pdf_file="")
    Invoice.objects.filter(contract__quote__seller_company=company, status__code=InvoiceStatusCode.DRAFT).exclude(
        pdf_file=""
    ).update(pdf_file="")
    Act.objects.filter(contract__quote__seller_company=company, status__code=ActStatusCode.DRAFT).exclude(
        pdf_file=""
    ).update(pdf_file="")


def _as_bool(value) -> bool:
    """Coerce a JSON-ish value to bool (handles the string forms a form/query can send)."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def upload_document_profile_logo(
    user: "CustomUser", company: Company, logo_file
) -> Tuple[Optional[CompanyDocumentProfile], Optional[str]]:
    """OWNER uploads/replaces the logo printed on the company's documents.

    Reuses validate_image_upload (same gate as the company-logo action). Returns
    (profile, error_code): NOT_COMPANY_OWNER, NO_FILE_PROVIDED or INVALID_IMAGE.
    """
    if not is_company_owner(user, company):
        return None, "NOT_COMPANY_OWNER"
    if not logo_file:
        return None, "NO_FILE_PROVIDED"
    try:
        validate_image_upload(logo_file)
    except DjangoValidationError as exc:
        logger.info("Document-profile logo rejected for company %s: %s", company.id, exc)
        return None, "INVALID_IMAGE"
    profile = get_document_profile(company)
    if profile.logo:
        profile.logo.delete(save=False)
    profile.logo = logo_file
    profile.save(update_fields=["logo", "updated_at"])
    _invalidate_branded_pdfs(company)
    return profile, None
