import logging
from typing import Optional, Tuple

from django.db import transaction

from ..models import (
    Company,
    CompanyMember,
    CustomUser,
    VerificationStatus,
    WorkspaceRole,
)

logger = logging.getLogger(__name__)


@transaction.atomic
def submit_company_profile(
    user: CustomUser,
    inn: str,
    company_name: str,
    workspace_role_code: str,
    company_type_code: str = "CLIENT",
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Step 3: User fills in company info, assigns company type, and creates membership.
    """
    if not all([inn, company_name, workspace_role_code]):
        return None, "PROFILE_FIELDS_REQUIRED"

    # Status lookups
    submitted_status = VerificationStatus.objects.filter(code="PROFILE_SUBMITTED").first()
    w_role = WorkspaceRole.objects.filter(code=workspace_role_code).first()

    if not w_role:
        return None, "WORKSPACE_ROLE_NOT_FOUND"

    from ..models import CompanyType

    company_type = CompanyType.objects.filter(code=company_type_code).first()

    # Reject onboarding into someone else's tenant by INN collision.
    # `get_or_create(inn=...)` used to silently attach the new user as OWNER of
    # whoever already claimed that INN; that's a cross-tenant data-leak vector
    # (placeholder INNs like 123456789 caused four unrelated users to land in
    # one company on prod, see project-known-bug-silent-company-merge).
    existing = Company.objects.filter(inn=inn).first()
    if existing and not CompanyMember.objects.filter(user=user, company=existing).exists():
        return None, "COMPANY_INN_TAKEN"

    if existing:
        company = existing  # idempotent: same user re-submitting their own INN
    else:
        company = Company.objects.create(
            inn=inn, name=company_name, verification_status=submitted_status
        )

    # Assign company type
    if company_type and not company.types.filter(pk=company_type.pk).exists():
        company.types.add(company_type)

    # Create membership (Multi-tenancy V2)
    CompanyMember.objects.get_or_create(user=user, company=company, defaults={"role": w_role, "is_primary": True})

    return user, None
