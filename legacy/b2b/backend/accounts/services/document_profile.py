"""Company Document Profile service — the branded requisites a selling company prints
on its OWN commercial documents (КП, договор).

Rule 8: all business logic (the OWNER-of-own-company gate, the get-or-create, the
field whitelist, the logo upload + validation) lives here. The view is a thin wrapper
that authorizes the request only by handing the object + actor to these functions.
"""

import logging
from typing import Optional, Tuple

from django.core.exceptions import ValidationError as DjangoValidationError

from core.validators import validate_image_upload

from ..constants import WorkspaceRoleCode
from ..models import Company, CompanyDocumentProfile, CompanyMember, CustomUser

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


def is_company_owner(user: "CustomUser", company: Company) -> bool:
    """True if `user` is an active OWNER member of `company` (or platform admin/superuser).

    The document profile is tenant org-admin data: only the company's own OWNER may
    read/write it; a member of another tenant is refused (never another company).
    Platform admin / superuser pass for moderation/support.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
        return True
    return CompanyMember.objects.filter(
        user=user,
        company=company,
        is_active=True,
        role__code=WorkspaceRoleCode.OWNER,
    ).exists()


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
    profile = get_document_profile(company)
    changed = []
    for field in _EDITABLE_FIELDS:
        if field in data:
            setattr(profile, field, data[field] or "")
            changed.append(field)
    if changed:
        profile.save(update_fields=[*changed, "updated_at"])
    return profile, None


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
