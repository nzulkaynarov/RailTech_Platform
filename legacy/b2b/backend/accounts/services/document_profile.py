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
)

# Layout toggles (P3) — coerced to bool, so a False value isn't turned into "" like the text fields.
_EDITABLE_BOOL_FIELDS = (
    "use_company_defaults",
    "show_logo",
    "show_lead_time",
    "show_fx_note",
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
    # SEC (audit #9): accent_color is interpolated raw into a <style> block in the PDF
    # templates, so an unvalidated value ("red;background:url(http://10.0.0.2)") is CSS
    # injection → WeasyPrint SSRF/LFI on render. Reject anything but a #hex colour.
    accent = data.get("accent_color")
    if accent not in (None, "") and not is_hex_color(accent):
        return None, "INVALID_ACCENT_COLOR"
    profile = get_document_profile(company)
    changed = []
    for field in _EDITABLE_FIELDS:
        if field in data:
            setattr(profile, field, data[field] or "")
            changed.append(field)
    for field in _EDITABLE_BOOL_FIELDS:
        if field in data:
            setattr(profile, field, _as_bool(data[field]))
            changed.append(field)
    if changed:
        profile.save(update_fields=[*changed, "updated_at"])
    return profile, None


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
    return profile, None
