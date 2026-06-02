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

    company, created = Company.objects.get_or_create(
        inn=inn, defaults={"name": company_name, "verification_status": submitted_status}
    )

    # Assign company type
    if company_type and not company.types.filter(pk=company_type.pk).exists():
        company.types.add(company_type)

    # Create membership (Multi-tenancy V2)
    CompanyMember.objects.get_or_create(user=user, company=company, defaults={"role": w_role, "is_primary": True})

    return user, None
