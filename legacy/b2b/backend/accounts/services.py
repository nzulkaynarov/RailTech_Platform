import logging
from typing import List, Optional, Tuple

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from notifications.emails import EmailDeliveryError, send_templated_email

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

logger = logging.getLogger(__name__)


def create_pending_user(email: str, first_name: str, last_name: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Step 1: Create a user in a pending state and send verification email.
    """
    if not email or not first_name or not last_name:
        return None, "REGISTRATION_FIELDS_REQUIRED"

    if CustomUser.objects.filter(email=email).exists():
        return None, "USER_EMAIL_ALREADY_EXISTS"

    # Default system role at registration: USER.
    user_role = SystemRole.objects.filter(code="USER").first()

    user = CustomUser.objects.create(
        username=email,
        email=email,
        first_name=first_name,
        last_name=last_name,
        is_active=False,
        role=user_role,
    )
    user.set_unusable_password()
    user.save()

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    base_url = settings.FRONTEND_URL
    setup_url = f"{base_url}/setup-password?uid={uid}&token={token}"

    try:
        send_templated_email(
            "setup_password",
            {"first_name": first_name, "setup_url": setup_url},
            to=[email],
            channel="transactional",
            user=user,
        )
    except EmailDeliveryError:
        # Email failed — clean up the orphaned user so they can retry
        user.delete()
        return None, "EMAIL_SEND_FAILED"

    return user, None


def send_password_reset_email(email: str) -> Tuple[bool, Optional[str]]:
    """
    Triggers a password-reset email for an existing active user. Silently
    succeeds when the email is unknown to avoid user enumeration.
    Returns: (delivered, error_code_or_None). `delivered=False` + no error
    means email was unknown; we still return True/None to the caller so the
    frontend shows the same outcome either way.
    """
    email = (email or "").strip().lower()
    if not email:
        return False, "EMAIL_REQUIRED"
    user = CustomUser.objects.filter(email__iexact=email).first()
    if not user:
        # Do not leak account existence — caller should show "if an account
        # exists, a link was sent" regardless.
        return True, None
    if not user.is_active:
        return True, None

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    base_url = settings.FRONTEND_URL
    reset_url = f"{base_url}/reset-password?uid={uid}&token={token}"

    try:
        send_templated_email(
            "reset_password",
            {"first_name": user.first_name or "", "reset_url": reset_url},
            to=[user.email],
            channel="transactional",
            user=user,
        )
    except EmailDeliveryError:
        logger.exception("Failed to send password reset email to %s", user.email)
        return False, "EMAIL_SEND_FAILED"
    return True, None


def reset_password(uidb64: str, token: str, password: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    """Verify reset token and set a new password. Reuses Django's default token generator."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        return None, "RESET_PASSWORD_INVALID_USER"
    if not default_token_generator.check_token(user, token):
        return None, "RESET_PASSWORD_INVALID_TOKEN"
    if not password or len(password) < 8:
        return None, "RESET_PASSWORD_WEAK"
    user.set_password(password)
    if not user.is_active:
        user.is_active = True
    user.save(update_fields=["password", "is_active"])
    return user, None


def verify_and_setup_password(uidb64: str, token: str, password: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        return None, "SETUP_PASSWORD_INVALID_USER"

    if not default_token_generator.check_token(user, token):
        return None, "SETUP_PASSWORD_INVALID_TOKEN"

    user.set_password(password)
    user.is_active = True
    user.save()
    return user, None


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

    from .models import CompanyType

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


def invite_workspace_member(company: Company, email: str, role_code: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    if not email:
        return None, "EMAIL_REQUIRED"

    if CustomUser.objects.filter(email=email).exists():
        return None, "USER_EMAIL_ALREADY_EXISTS"

    w_role = WorkspaceRole.objects.filter(code=role_code).first()
    if not w_role:
        return None, "SYSTEM_ROLE_NOT_FOUND"

    # Default system role for invited member: USER (пользователь компании).
    user_role = SystemRole.objects.filter(code="USER").first()

    user = CustomUser.objects.create(
        username=email,
        email=email,
        is_active=False,
        role=user_role,
    )
    user.set_unusable_password()
    user.save()

    CompanyMember.objects.create(user=user, company=company, role=w_role, is_primary=True)

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    base_url = settings.FRONTEND_URL
    setup_url = f"{base_url}/setup-password?uid={uid}&token={token}"

    send_templated_email(
        "invite_member",
        {"company_name": company.name, "setup_url": setup_url},
        to=[email],
        channel="transactional",
        user=user,
        fail_silently=True,
    )
    return user, None


# ──────────────────────────────────────────────────────────────────────────
# Admin operations — single source of truth for business logic.
# Called from both Django Unfold actions and DRF endpoints.
# See ADR-0001 and CLAUDE.md IRON RULE 8.
# ──────────────────────────────────────────────────────────────────────────


def change_user_role(
    user: CustomUser,
    role_code: str,
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Change SystemRole of a user.

    Инварианты платформы:
      - ADMIN выдаётся только пользователям без активных memberships
        (Platform Admin — владелец платформы, не привязан ни к одной компании).
      - Понизить ADMIN → USER разрешено всегда.
      - USER можно выдать любому юзеру.
    """
    if not role_code:
        return None, "ROLE_CODE_REQUIRED"
    role = SystemRole.objects.filter(code=role_code).first()
    if not role:
        return None, "SYSTEM_ROLE_NOT_FOUND"
    if role.code == "ADMIN":
        has_active_memberships = user.memberships.filter(is_active=True).exists()
        if has_active_memberships:
            return None, "ADMIN_ROLE_REQUIRES_NO_MEMBERSHIPS"
    user.role = role
    user.save(update_fields=["role"])
    return user, None


def add_company_member(
    user: CustomUser,
    company: Company,
    workspace_role_code: str,
    is_primary: bool = False,
) -> Tuple[Optional["CompanyMember"], Optional[str]]:
    """
    Add or update a CompanyMember link between user and company.

    Инварианты платформы:
      - Platform Admin (role=ADMIN) не может быть членом компании.
      - workspace_role должен быть применим к типам компании (applicable_to_types).
    """
    if user.role and user.role.code == "ADMIN":
        return None, "PLATFORM_ADMIN_CANNOT_JOIN_COMPANY"
    role = WorkspaceRole.objects.filter(code=workspace_role_code).first()
    if not role:
        return None, "WORKSPACE_ROLE_NOT_FOUND"
    applicable = role.applicable_to_types.all()
    if applicable.exists():
        company_type_codes = set(company.types.values_list("code", flat=True))
        allowed_codes = set(applicable.values_list("code", flat=True))
        if not (company_type_codes & allowed_codes):
            return None, "WORKSPACE_ROLE_NOT_APPLICABLE_TO_COMPANY_TYPE"
    membership, _created = CompanyMember.objects.update_or_create(
        user=user,
        company=company,
        defaults={"role": role, "is_primary": is_primary, "is_active": True},
    )
    return membership, None


def verify_company_kyc(
    company: Company,
    approver: CustomUser,
    level_code: str = "L2_VERIFIED",
    require_documents: bool = True,
    reason: str = "",
) -> Tuple[Optional[Company], Optional[str]]:
    """
    Move a company through KYC verification levels (L1 → L2 → L3).

    - level_code: target VerificationStatus.code
    - require_documents: when True, refuse to verify if no KYC documents uploaded
    - reason: required when moving DOWN (e.g. revoking to L1_UNVERIFIED)
    Returns: (company, error_message_or_None)
    """
    target_status = VerificationStatus.objects.filter(code=level_code).first()
    if not target_status:
        return None, "VERIFICATION_STATUS_NOT_FOUND"

    # Downgrades/revokes must carry a reason for audit purposes.
    LEVEL_RANK = {
        "L1_UNVERIFIED": 0,
        "PROFILE_SUBMITTED": 1,
        "L2_VERIFIED": 2,
        "L3_CONTRACTED": 3,
    }
    current_code = company.verification_status.code if company.verification_status_id else "L1_UNVERIFIED"
    is_downgrade = LEVEL_RANK.get(level_code, 0) < LEVEL_RANK.get(current_code, 0)
    if is_downgrade and not (reason or "").strip():
        return None, "REASON_REQUIRED"

    if require_documents and not is_downgrade and not company.kyc_documents.exists():
        return None, "KYC_DOCUMENTS_MISSING"

    before_code = current_code
    before_name = company.verification_status.name if company.verification_status_id else ""
    company.verification_status = target_status
    company.save(update_fields=["verification_status"])

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="company",
        entity_id=company.id,
        action="KYC: понижение уровня" if is_downgrade else "KYC: подтверждение",
        detail=f"{company.name}: {before_name or before_code} → {target_status.name}",
        actor=approver,
        reason=reason,
        before={"verification_status": before_code},
        after={"verification_status": level_code},
        level="WARNING" if is_downgrade else "SUCCESS",
    )

    # Notify owner(s) by email and in-app (only on upgrades)
    if not is_downgrade:
        try:
            _send_kyc_status_email(company, level_code)
        except Exception:
            logger.exception("Failed to send KYC status email for company %s", company.pk)
        try:
            _create_kyc_notification(company, level_code)
        except Exception:
            logger.exception("Failed to create KYC notification for company %s", company.pk)
    return company, None


def _send_kyc_status_email(company: Company, level_code: str) -> None:
    owners = list(
        CustomUser.objects.filter(
            memberships__company=company,
            memberships__is_primary=True,
            memberships__is_active=True,
        ).distinct()
    )
    if not owners:
        return
    context = {
        "company_name": company.name,
        "company_inn": company.inn,
        "level_code": level_code,
        "frontend_url": getattr(settings, "FRONTEND_URL", "http://localhost:5173"),
    }
    # Send one email per owner so each row in EmailLog is searchable by user.
    for owner in owners:
        send_templated_email(
            "kyc_verified",
            context,
            to=[owner.email],
            channel="transactional",
            user=owner,
            fail_silently=True,
        )


def _create_kyc_notification(company: Company, level_code: str) -> None:
    from notifications.models import Notification, NotificationType

    owners = CustomUser.objects.filter(
        memberships__company=company,
        memberships__is_primary=True,
        memberships__is_active=True,
    ).distinct()
    nt = NotificationType.objects.filter(code="SUCCESS").first()
    for u in owners:
        Notification.objects.create(
            user=u,
            type=nt,
            title="Статус KYC обновлён",
            message=f"KYC для {company.name} — {level_code}",
            link="/cabinet/profile",
        )


def bulk_verify_kyc(
    companies: QuerySet[Company],
    approver: CustomUser,
    level_code: str = "L2_VERIFIED",
    reason: str = "",
) -> Tuple[int, List[dict]]:
    """
    Bulk wrapper around verify_company_kyc for admin actions.

    Returns: (approved_count, list_of_skipped_reports [{company_id, name, error}])
    """
    approved = 0
    skipped: List[dict] = []
    for company in companies:
        _, error = verify_company_kyc(
            company,
            approver,
            level_code,
            require_documents=True,
            reason=reason,
        )
        if error:
            skipped.append({"company_id": company.id, "name": company.name, "error": error})
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
    if application.status not in ("PENDING", "PAYMENT_REQUIRED", "DOCUMENTS_REQUIRED"):
        return None, "ROLE_APPLICATION_CANNOT_APPROVE"

    requested_code = application.requested_type.code
    if requested_code == "SUPPLIER":
        if not application.contract_file or not application.nda_file:
            return None, "ROLE_APPLICATION_MISSING_CONTRACT_NDA"
    elif requested_code == "MANUFACTURER":
        if not application.partnership_agreement:
            return None, "ROLE_APPLICATION_MISSING_PARTNERSHIP"

    before_status = application.status
    application.status = "APPROVED"
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

    application.company.types.add(application.requested_type)

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="role_application",
        entity_id=application.id,
        action="Заявка на роль одобрена",
        detail=f"{application.company.name} → {application.requested_type.name}",
        actor=reviewer,
        before={"status": before_status},
        after={"status": "APPROVED"},
        level="SUCCESS",
    )
    log_admin_action(
        entity_type="company",
        entity_id=application.company_id,
        action=f"Добавлена роль: {application.requested_type.code}",
        detail=f"Одобрена заявка #{application.id}",
        actor=reviewer,
        after={"added_type": application.requested_type.code},
        level="SUCCESS",
    )

    # Auto-create TRIAL subscription for SUPPLIER / MANUFACTURER — 30 days
    if requested_code in ("SUPPLIER", "MANUFACTURER"):
        try:
            ensure_trial_subscription(application.company)
        except Exception:
            logger.exception("Failed to create trial subscription for company %s", application.company_id)

    # Notify applicant
    try:
        _send_role_application_email(application, approved=True)
    except Exception:
        logger.exception("Failed to send role application approval email for application %s", application.pk)

    return application, None


def ensure_trial_subscription(company: Company, trial_days: int = 30) -> SupplierSubscription:
    """Create a TRIAL subscription for the company if missing."""
    from datetime import timedelta

    sub = getattr(company, "subscription", None)
    if sub:
        return sub
    today = timezone.now().date()
    sub = SupplierSubscription.objects.create(
        company=company,
        plan="BASIC",
        status="TRIAL",
        monthly_rate=0,
        valid_from=today,
        valid_until=today + timedelta(days=trial_days),
        next_payment_date=today + timedelta(days=trial_days),
        notes=f"Auto-created TRIAL on {today}",
    )
    return sub


def _send_role_application_email(app: CompanyRoleApplication, approved: bool) -> None:
    owners = list(
        CustomUser.objects.filter(
            memberships__company=app.company,
            memberships__is_primary=True,
            memberships__is_active=True,
        ).distinct()
    )
    if not owners:
        return
    template = "role_application_approved" if approved else "role_application_rejected"
    context = {
        "company_name": app.company.name,
        "requested_type_name": app.requested_type.name,
        "review_notes": app.review_notes or "",
        "trial_granted": approved and app.requested_type.code in ("SUPPLIER", "MANUFACTURER"),
        "frontend_url": getattr(settings, "FRONTEND_URL", "http://localhost:5173"),
    }
    for owner in owners:
        send_templated_email(
            template,
            context,
            to=[owner.email],
            channel="transactional",
            user=owner,
            fail_silently=True,
        )


def record_subscription_payment(
    subscription: SupplierSubscription,
    amount,
    months: int = 1,
    actor: Optional[CustomUser] = None,
    manual: bool = True,
) -> Tuple[Optional[SupplierSubscription], Optional[str]]:
    """Extend subscription and set ACTIVE after a successful payment.

    NOTE: manual=True flag indicates the payment was recorded by hand (no provider webhook).
    Logged in ActivityLog with MANUAL_MODE marker so reconciliation is possible later
    when a real payment provider (Click/Payme/Stripe) replaces the manual flow.
    See memory `tech_debt_payment_esign.md`.

    Returns (subscription, error_or_None). Platform-admin viewers cannot pay
    on behalf of a company (`ADMIN_VIEWER_CANNOT_ACT`); the paying user must be
    an active member of the subscription's company with `can_sell` (subscription
    is a seller-side billing concern), or a superuser.
    """
    from datetime import timedelta

    from crm.models import ActivityLog

    if actor is not None:
        if is_platform_admin_viewer(actor):
            return None, "ADMIN_VIEWER_CANNOT_ACT"
        if not (
            getattr(actor, "is_superuser", False) or is_member_of(actor, subscription.company_id, capability="sell")
        ):
            return None, "MEMBER_REQUIRED_FOR_ACTION"
    today = timezone.now().date()
    base = max(today, subscription.valid_until or today)
    subscription.valid_until = base + timedelta(days=30 * months)
    subscription.last_payment_date = today
    subscription.next_payment_date = subscription.valid_until
    subscription.status = "ACTIVE"
    subscription.save(
        update_fields=[
            "valid_until",
            "last_payment_date",
            "next_payment_date",
            "status",
            "updated_at",
        ]
    )
    marker = "[MANUAL_MODE] " if manual else ""
    ActivityLog.objects.create(
        action=f"{marker}Оплата подписки",
        detail=(
            f"Подписка компании {subscription.company.name}: "
            f"+{months} мес, сумма {amount}. Действует до {subscription.valid_until}."
        ),
        user=actor,
        level="SUCCESS",
    )
    return subscription, None


def check_and_expire_subscriptions() -> dict:
    """Move expired TRIAL/ACTIVE subscriptions to PAST_DUE, then to SUSPENDED if 14+ days overdue."""
    from datetime import timedelta

    today = timezone.now().date()
    # Step 1: fresh expirations → PAST_DUE
    just_expired = SupplierSubscription.objects.filter(
        status__in=["TRIAL", "ACTIVE"],
        valid_until__lt=today,
    )
    past_due_count = just_expired.update(status="PAST_DUE")
    # Step 2: PAST_DUE >= 14 days → SUSPENDED
    threshold = today - timedelta(days=14)
    suspended_count = SupplierSubscription.objects.filter(
        status="PAST_DUE",
        valid_until__lt=threshold,
    ).update(status="SUSPENDED")
    return {"past_due": past_due_count, "suspended": suspended_count}


def reject_role_application(
    application: CompanyRoleApplication,
    reviewer: CustomUser,
    reason: str = "",
) -> Tuple[Optional[CompanyRoleApplication], Optional[str]]:
    """Reject a CompanyRoleApplication. Reason is required for audit. Returns (app, error_or_None)."""
    if application.status not in ("PENDING", "PAYMENT_REQUIRED", "DOCUMENTS_REQUIRED"):
        return None, "ROLE_APPLICATION_CANNOT_REJECT"
    if not (reason or "").strip():
        return None, "REASON_REQUIRED"

    before_status = application.status
    application.status = "REJECTED"
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.review_notes = reason
    application.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_notes", "updated_at"])

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="role_application",
        entity_id=application.id,
        action="Заявка на роль отклонена",
        detail=f"{application.company.name} → {application.requested_type.name}",
        actor=reviewer,
        reason=reason,
        before={"status": before_status},
        after={"status": "REJECTED"},
        level="WARNING",
    )

    try:
        _send_role_application_email(application, approved=False)
    except Exception:
        logger.exception("Failed to send role application rejection email for application %s", application.pk)

    return application, None


def bulk_approve_role_applications(
    applications: QuerySet[CompanyRoleApplication],
    reviewer: CustomUser,
) -> Tuple[int, List[str]]:
    """Bulk approve. Returns (approved_count, list_of_error_messages)."""
    approved = 0
    errors: List[str] = []
    pending = applications.filter(status__in=["PENDING", "PAYMENT_REQUIRED", "DOCUMENTS_REQUIRED"])
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
    pending = applications.filter(status__in=["PENDING", "PAYMENT_REQUIRED", "DOCUMENTS_REQUIRED"])
    rejected = 0
    for app in pending:
        _, error = reject_role_application(app, reviewer)
        if not error:
            rejected += 1
    return rejected


def change_user_password(
    user: CustomUser,
    current_password: str,
    new_password: str,
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Change user password after verifying the current one.
    Returns: (user, error_or_None)
    """
    if not user.check_password(current_password):
        return None, "CURRENT_PASSWORD_WRONG"
    user.set_password(new_password)
    user.save(update_fields=["password"])
    return user, None


def toggle_user_active(
    user: CustomUser,
    requester: CustomUser,
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Toggle user's is_active flag. Prevents self-deactivation.
    Returns: (user, error_or_None)
    """
    if user.pk == requester.pk:
        return None, "CANNOT_DEACTIVATE_SELF"
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    return user, None


def upload_kyc_document(
    company: Company,
    file_obj,
    doc_type_code: str = "OTHER",
) -> Tuple[Optional["KYCDocument"], Optional[str]]:  # noqa: F821
    """
    Upload a KYC document for a company with file validation.
    Returns: (document, error_or_None)
    """
    from django.core.exceptions import ValidationError as DjangoValidationError
    from django.core.validators import FileExtensionValidator

    from .models import KYCDocType, KYCDocument

    allowed_extensions = ["pdf", "jpg", "jpeg", "png", "doc", "docx"]
    max_size = 10 * 1024 * 1024  # 10MB

    if file_obj.size > max_size:
        return None, "FILE_TOO_LARGE"

    ext_validator = FileExtensionValidator(allowed_extensions)
    try:
        ext_validator(file_obj)
    except DjangoValidationError as e:
        return None, str(e)

    d_type = KYCDocType.objects.filter(code=doc_type_code).first()
    doc = KYCDocument.objects.create(
        company=company,
        file=file_obj,
        doc_type=d_type,
        original_filename=file_obj.name,
    )
    return doc, None


def delete_kyc_document(
    company: Company,
    doc_id: int,
) -> Tuple[bool, Optional[str]]:
    """
    Delete a KYC document belonging to a company.
    Returns: (success, error_or_None)
    """
    from .models import KYCDocument

    doc = KYCDocument.objects.filter(company=company, id=doc_id).first()
    if not doc:
        return False, "Document not found"
    doc.file.delete(save=False)
    doc.delete()
    return True, None


def change_subscription_status(
    subscriptions: QuerySet[SupplierSubscription],
    new_status: str,
) -> int:
    """
    Change subscription status (ACTIVE / SUSPENDED / CANCELLED / TRIAL).
    Returns: count of updated rows.
    """
    valid_statuses = {"ACTIVE", "SUSPENDED", "CANCELLED", "TRIAL", "PAST_DUE"}
    if new_status not in valid_statuses:
        raise ValueError(f"Invalid status '{new_status}'. Allowed: {valid_statuses}")
    return subscriptions.update(status=new_status)


# ──────────────────────────────────────────────────────────────────────────
# Actor-level guards for business services
# ──────────────────────────────────────────────────────────────────────────


def is_member_of(user: "CustomUser", company_id: int, *, capability: Optional[str] = None) -> bool:
    """True if user is an active CompanyMember of the given company.

    If `capability` is 'sell' or 'buy', also checks the membership's can_sell /
    can_buy flag. OWNER distributes these in the team; a member without the
    flag must be refused at the service layer even if the company has the
    matching CompanyType.
    """
    if not user or not user.is_authenticated:
        return False
    qs = user.memberships.filter(company_id=company_id, is_active=True)
    membership = qs.first()
    if membership is None:
        return False
    if capability == "sell":
        return bool(membership.can_sell)
    if capability == "buy":
        return bool(membership.can_buy)
    return True


def is_platform_admin_viewer(user: "CustomUser") -> bool:
    """Platform Admin acting on platform-level — never acts on behalf of a company.

    `is_superuser` is intentionally *excluded*: superuser is the DBA emergency
    bypass and must be able to fix any business record, even on behalf of a
    company. Migration accounts/0010_platform_admin_model removes any
    CompanyMember rows for users with SystemRole.ADMIN, so admin-viewer equals
    "role.code == 'ADMIN' and not is_superuser".

    Kept as a function because business services use the error code
    `ADMIN_VIEWER_CANNOT_ACT`, which conveys intent better than a generic
    "member required" when a platform admin tries to act for a company.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return False
    role_code = getattr(getattr(user, "role", None), "code", None)
    return role_code == "ADMIN"


def company_has_operational_subscription(company_id: int) -> bool:
    """True if the company has a SupplierSubscription that is_operational right now.

    Seller-side write operations (bid submit, offer CRUD, product CRUD) must be
    gated by this — SELLER / MANUFACTURER companies without a valid subscription
    cannot sell on the platform. CLIENTs don't need a subscription to buy.
    """
    sub = SupplierSubscription.objects.filter(company_id=company_id).order_by("-updated_at").first()
    if sub is None:
        return False
    return sub.is_operational
