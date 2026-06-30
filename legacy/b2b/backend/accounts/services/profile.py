import logging
from typing import Optional, Tuple

from django.db import transaction

from ..constants import COMPANY_ADMIN_ROLE_NAME
from ..models import Company, CompanyMember, CustomUser, VerificationStatus, WorkspaceRole

logger = logging.getLogger(__name__)


@transaction.atomic
def submit_company_profile(
    user: CustomUser,
    company_name: str,
    position: str = "",
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Step 3: minimal onboarding. Everyone self-registers as a Buyer (CLIENT) and
    becomes OWNER of a brand-new company.

    INN and company type are deferred (INN → KYC; selling → CompanyRoleApplication),
    so there is no INN collision and no silent cross-tenant merge to guard against.
    Idempotent: a user who already has a primary company is returned unchanged.
    """
    if not company_name:
        return None, "PROFILE_FIELDS_REQUIRED"

    # Already onboarded — don't create a second company on a repeat submit.
    if user.memberships.filter(is_active=True).exists():
        if position and user.position != position:
            user.position = position
            user.save(update_fields=["position"])
        return user, None

    from ..models import CompanyType

    submitted_status = VerificationStatus.objects.filter(code="PROFILE_SUBMITTED").first()
    owner_role = WorkspaceRole.objects.filter(code="OWNER").first()
    client_type = CompanyType.objects.filter(code="CLIENT").first()

    if not owner_role:
        return None, "WORKSPACE_ROLE_NOT_FOUND"

    company = Company.objects.create(name=company_name, verification_status=submitted_status)
    if client_type:
        company.types.add(client_type)

    member = CompanyMember.objects.create(user=user, company=company, role=owner_role, is_primary=True)
    # Seed the company's default CompanyRoles (so the access matrix isn't empty for a fresh
    # tenant) and give the founding OWNER the immutable «Администратор компании» role — otherwise
    # the G4 permission engine is silently bypassed for every company registered after mig 0023.
    from .roles import ensure_default_company_roles

    member.company_role = ensure_default_company_roles(company)[COMPANY_ADMIN_ROLE_NAME]
    member.save(update_fields=["company_role"])

    if position:
        user.position = position
        user.save(update_fields=["position"])

    return user, None
