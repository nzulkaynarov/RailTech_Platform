from typing import List, Optional, Tuple

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import (
    Company,
    CompanyMember,
    CompanyRoleApplication,
    CustomUser,
    SupplierSubscription,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)


def create_pending_user(email: str, first_name: str, last_name: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Step 1: Create a user in a pending state and send verification email.
    """
    if not email or not first_name or not last_name:
        return None, "Email, first name and last name are required"

    if CustomUser.objects.filter(email=email).exists():
        return None, "Пользователь с таким email уже существует."

    # Assign default GUEST role from Master Data
    guest_role = SystemRole.objects.filter(code='GUEST').first()

    user = CustomUser.objects.create(
        username=email,
        email=email,
        first_name=first_name,
        last_name=last_name,
        is_active=False,
        role=guest_role
    )
    user.set_unusable_password()
    user.save()

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    base_url = settings.FRONTEND_URL
    setup_url = f"{base_url}/setup-password?uid={uid}&token={token}"

    send_mail(
        "Подтверждение регистрации RailTech B2B",
        f"Здравствуйте, {first_name}!\n\nДля завершения регистрации перейдите по ссылке:\n{setup_url}",
        settings.DEFAULT_FROM_EMAIL,
        [email],
        fail_silently=False,
    )
    return user, None


def verify_and_setup_password(uidb64: str, token: str, password: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        return None, "Invalid user"

    if not default_token_generator.check_token(user, token):
        return None, "Invalid or expired token"

    user.set_password(password)
    user.is_active = True
    user.save()
    return user, None


def submit_company_profile(
    user: CustomUser,
    inn: str,
    company_name: str,
    workspace_role_code: str,
    company_type_code: str = 'CLIENT',
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Step 3: User fills in company info, assigns company type, and creates membership.
    """
    if not all([inn, company_name, workspace_role_code]):
        return None, "INN, company name and role are required"

    # Status lookups
    submitted_status = VerificationStatus.objects.filter(code='PROFILE_SUBMITTED').first()
    w_role = WorkspaceRole.objects.filter(code=workspace_role_code).first()

    if not w_role:
        return None, f"Role '{workspace_role_code}' not found in master data."

    from .models import CompanyType
    company_type = CompanyType.objects.filter(code=company_type_code).first()

    company, created = Company.objects.get_or_create(
        inn=inn,
        defaults={
            'name': company_name,
            'verification_status': submitted_status
        }
    )

    # Assign company type
    if company_type and not company.types.filter(pk=company_type.pk).exists():
        company.types.add(company_type)

    # Create membership (Multi-tenancy V2)
    CompanyMember.objects.get_or_create(
        user=user,
        company=company,
        defaults={
            'role': w_role,
            'is_primary': True
        }
    )

    return user, None


def invite_workspace_member(company: Company, email: str, role_code: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    if not email:
        return None, "Email is required"

    if CustomUser.objects.filter(email=email).exists():
        return None, "Пользователь с таким email уже существует."

    w_role = WorkspaceRole.objects.filter(code=role_code).first()
    if not w_role:
        return None, f"Role '{role_code}' not found."

    # Assign default GUEST role (same as registration flow)
    guest_role = SystemRole.objects.filter(code='GUEST').first()

    user = CustomUser.objects.create(
        username=email,
        email=email,
        is_active=False,
        role=guest_role
    )
    user.set_unusable_password()
    user.save()

    CompanyMember.objects.create(
        user=user,
        company=company,
        role=w_role,
        is_primary=True
    )

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    base_url = settings.FRONTEND_URL
    setup_url = f"{base_url}/setup-password?uid={uid}&token={token}"

    send_mail(
        "Приглашение в команду RailTech B2B",
        f"Вас пригласили в команду {company.name}. Установите пароль: {setup_url}",
        settings.DEFAULT_FROM_EMAIL,
        [email]
    )
    return user, None


# ──────────────────────────────────────────────────────────────────────────
# Admin operations — single source of truth for business logic.
# Called from both Django Unfold actions and DRF endpoints.
# See ADR-0001 and CLAUDE.md IRON RULE 8.
# ──────────────────────────────────────────────────────────────────────────


def assign_sales_manager_role(users: QuerySet[CustomUser]) -> Tuple[int, Optional[str]]:
    """
    Assign SALES_MANAGER role to users and grant Django staff access.

    Returns: (count_updated, error_message_or_None)
    """
    sales_role = SystemRole.objects.filter(code='SALES_MANAGER').first()
    if not sales_role:
        return 0, "SystemRole 'SALES_MANAGER' not found in master data"
    updated = users.update(is_staff=True, role=sales_role)
    return updated, None


def verify_company_kyc(
    company: Company,
    approver: CustomUser,
    level_code: str = 'L2_VERIFIED',
    require_documents: bool = True,
) -> Tuple[Optional[Company], Optional[str]]:
    """
    Move a company through KYC verification levels (L1 → L2 → L3).

    - level_code: target VerificationStatus.code
    - require_documents: when True, refuse to verify if no KYC documents uploaded
    Returns: (company, error_message_or_None)
    """
    target_status = VerificationStatus.objects.filter(code=level_code).first()
    if not target_status:
        return None, f"VerificationStatus '{level_code}' not found"

    if require_documents and not company.kyc_documents.exists():
        return None, f"Company '{company.name}' has no KYC documents"

    company.verification_status = target_status
    company.save(update_fields=['verification_status'])
    # TODO: hook for pghistory event / notification when triggers wired
    return company, None


def bulk_verify_kyc(
    companies: QuerySet[Company],
    approver: CustomUser,
    level_code: str = 'L2_VERIFIED',
) -> Tuple[int, List[str]]:
    """
    Bulk wrapper around verify_company_kyc for admin actions.

    Returns: (approved_count, list_of_skipped_company_names)
    """
    approved = 0
    skipped: List[str] = []
    for company in companies:
        _, error = verify_company_kyc(company, approver, level_code, require_documents=True)
        if error:
            skipped.append(company.name)
        else:
            approved += 1
    return approved, skipped


def approve_role_application(
    application: CompanyRoleApplication,
    reviewer: CustomUser,
) -> Tuple[Optional[CompanyRoleApplication], Optional[str]]:
    """
    Approve a CompanyRoleApplication: validate required documents per type,
    set status to APPROVED, attach the requested CompanyType to the company.

    Returns: (application, error_message_or_None)
    """
    if application.status not in ('PENDING', 'PAYMENT_REQUIRED', 'DOCUMENTS_REQUIRED'):
        return None, f"Application is in state '{application.status}', cannot approve"

    requested_code = application.requested_type.code
    if requested_code == 'SUPPLIER':
        if not application.contract_file or not application.nda_file:
            return None, f"{application.company.name}: contract + NDA required for SUPPLIER"
    elif requested_code == 'MANUFACTURER':
        if not application.partnership_agreement:
            return None, f"{application.company.name}: partnership agreement required for MANUFACTURER"

    application.status = 'APPROVED'
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

    application.company.types.add(application.requested_type)
    return application, None


def reject_role_application(
    application: CompanyRoleApplication,
    reviewer: CustomUser,
    reason: str = '',
) -> Tuple[Optional[CompanyRoleApplication], Optional[str]]:
    """Reject a CompanyRoleApplication. Returns (app, error_or_None)."""
    if application.status not in ('PENDING', 'PAYMENT_REQUIRED', 'DOCUMENTS_REQUIRED'):
        return None, f"Application is in state '{application.status}', cannot reject"

    application.status = 'REJECTED'
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    if reason:
        application.review_notes = reason
        application.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'])
    else:
        application.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])
    return application, None


def bulk_approve_role_applications(
    applications: QuerySet[CompanyRoleApplication],
    reviewer: CustomUser,
) -> Tuple[int, List[str]]:
    """Bulk approve. Returns (approved_count, list_of_error_messages)."""
    approved = 0
    errors: List[str] = []
    pending = applications.filter(status__in=['PENDING', 'PAYMENT_REQUIRED', 'DOCUMENTS_REQUIRED'])
    for app in pending:
        _, error = approve_role_application(app, reviewer)
        if error:
            errors.append(error)
        else:
            approved += 1
    return approved, errors


def bulk_reject_role_applications(
    applications: QuerySet[CompanyRoleApplication],
    reviewer: CustomUser,
) -> int:
    """Bulk reject. Returns count of rejected applications."""
    pending = applications.filter(status__in=['PENDING', 'PAYMENT_REQUIRED', 'DOCUMENTS_REQUIRED'])
    rejected = 0
    for app in pending:
        _, error = reject_role_application(app, reviewer)
        if not error:
            rejected += 1
    return rejected


def change_subscription_status(
    subscriptions: QuerySet[SupplierSubscription],
    new_status: str,
) -> int:
    """
    Change subscription status (ACTIVE / SUSPENDED / CANCELLED / TRIAL).
    Returns: count of updated rows.
    """
    valid_statuses = {'ACTIVE', 'SUSPENDED', 'CANCELLED', 'TRIAL', 'EXPIRED'}
    if new_status not in valid_statuses:
        raise ValueError(f"Invalid status '{new_status}'. Allowed: {valid_statuses}")
    return subscriptions.update(status=new_status)
