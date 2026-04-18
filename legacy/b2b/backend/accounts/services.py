from typing import List, Optional, Tuple

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
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
        return None, 'REGISTRATION_FIELDS_REQUIRED'

    if CustomUser.objects.filter(email=email).exists():
        return None, 'USER_EMAIL_ALREADY_EXISTS'

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

    try:
        send_mail(
            "Подтверждение регистрации RailTech B2B",
            f"Здравствуйте, {first_name}!\n\nДля завершения регистрации перейдите по ссылке:\n{setup_url}",
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
    except Exception:
        # Email failed — clean up the orphaned user so they can retry
        user.delete()
        return None, 'EMAIL_SEND_FAILED'

    return user, None


def verify_and_setup_password(uidb64: str, token: str, password: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        return None, 'SETUP_PASSWORD_INVALID_USER'

    if not default_token_generator.check_token(user, token):
        return None, 'SETUP_PASSWORD_INVALID_TOKEN'

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
    company_type_code: str = 'CLIENT',
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Step 3: User fills in company info, assigns company type, and creates membership.
    """
    if not all([inn, company_name, workspace_role_code]):
        return None, 'PROFILE_FIELDS_REQUIRED'

    # Status lookups
    submitted_status = VerificationStatus.objects.filter(code='PROFILE_SUBMITTED').first()
    w_role = WorkspaceRole.objects.filter(code=workspace_role_code).first()

    if not w_role:
        return None, 'WORKSPACE_ROLE_NOT_FOUND'

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
        return None, 'EMAIL_REQUIRED'

    if CustomUser.objects.filter(email=email).exists():
        return None, 'USER_EMAIL_ALREADY_EXISTS'

    w_role = WorkspaceRole.objects.filter(code=role_code).first()
    if not w_role:
        return None, 'SYSTEM_ROLE_NOT_FOUND'

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
        return 0, 'SALES_MANAGER_ROLE_NOT_FOUND'
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
        return None, 'VERIFICATION_STATUS_NOT_FOUND'

    if require_documents and not company.kyc_documents.exists():
        return None, 'KYC_DOCUMENTS_MISSING'

    company.verification_status = target_status
    company.save(update_fields=['verification_status'])
    # Notify owner(s) by email and in-app
    try:
        _send_kyc_status_email(company, level_code)
    except Exception:
        pass  # email failure shouldn't roll back KYC
    try:
        _create_kyc_notification(company, level_code)
    except Exception:
        pass
    return company, None


def _send_kyc_status_email(company: Company, level_code: str) -> None:
    owners = CustomUser.objects.filter(
        memberships__company=company, memberships__is_primary=True, memberships__is_active=True,
    ).distinct()
    if not owners.exists():
        return
    subject_map = {
        'L2_VERIFIED': f"RailTech: KYC компании {company.name} подтверждён",
        'L3_CONTRACTED': f"RailTech: контракт с RailTech активирован",
    }
    body_map = {
        'L2_VERIFIED': (
            "Здравствуйте!\n\n"
            f"KYC уровень L2 для компании {company.name} (ИНН {company.inn}) успешно подтверждён.\n"
            "Теперь вы можете работать в полном объёме в RailTech.\n\n"
            "— RailTech B2B"
        ),
        'L3_CONTRACTED': (
            "Здравствуйте!\n\n"
            f"Контракт для компании {company.name} активирован. Все премиум-функции открыты.\n\n"
            "— RailTech B2B"
        ),
    }
    subject = subject_map.get(level_code, f"RailTech: обновление статуса KYC → {level_code}")
    body = body_map.get(level_code, f"Статус верификации изменён на {level_code}.")
    send_mail(
        subject, body,
        getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@railtech.uz'),
        list(owners.values_list('email', flat=True)),
        fail_silently=True,
    )


def _create_kyc_notification(company: Company, level_code: str) -> None:
    from notifications.models import Notification, NotificationType
    owners = CustomUser.objects.filter(
        memberships__company=company, memberships__is_primary=True, memberships__is_active=True,
    ).distinct()
    nt = NotificationType.objects.filter(code='SUCCESS').first()
    for u in owners:
        Notification.objects.create(
            user=u, type=nt,
            title="Статус KYC обновлён",
            message=f"KYC для {company.name} — {level_code}",
            link="/cabinet/profile",
        )


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
        return None, 'ROLE_APPLICATION_CANNOT_APPROVE'

    requested_code = application.requested_type.code
    if requested_code == 'SUPPLIER':
        if not application.contract_file or not application.nda_file:
            return None, 'ROLE_APPLICATION_MISSING_CONTRACT_NDA'
    elif requested_code == 'MANUFACTURER':
        if not application.partnership_agreement:
            return None, 'ROLE_APPLICATION_MISSING_PARTNERSHIP'

    application.status = 'APPROVED'
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

    application.company.types.add(application.requested_type)

    # Auto-create TRIAL subscription for SUPPLIER / MANUFACTURER — 30 days
    if requested_code in ('SUPPLIER', 'MANUFACTURER'):
        try:
            ensure_trial_subscription(application.company)
        except Exception:
            pass  # don't roll back approval

    # Notify applicant
    try:
        _send_role_application_email(application, approved=True)
    except Exception:
        pass

    return application, None


def ensure_trial_subscription(company: Company, trial_days: int = 30) -> SupplierSubscription:
    """Create a TRIAL subscription for the company if missing."""
    from datetime import timedelta
    sub = getattr(company, 'subscription', None)
    if sub:
        return sub
    today = timezone.now().date()
    sub = SupplierSubscription.objects.create(
        company=company, plan='BASIC', status='TRIAL',
        monthly_rate=0, valid_from=today,
        valid_until=today + timedelta(days=trial_days),
        next_payment_date=today + timedelta(days=trial_days),
        notes=f"Auto-created TRIAL on {today}",
    )
    return sub


def _send_role_application_email(app: CompanyRoleApplication, approved: bool) -> None:
    owners = CustomUser.objects.filter(
        memberships__company=app.company, memberships__is_primary=True, memberships__is_active=True,
    ).distinct()
    if not owners.exists():
        return
    subject = (
        f"RailTech: заявка на роль {app.requested_type.name} одобрена"
        if approved else
        f"RailTech: заявка на роль {app.requested_type.name} отклонена"
    )
    if approved:
        body = (
            f"Заявка компании {app.company.name} на роль {app.requested_type.name} одобрена.\n"
            f"Для поставщиков/производителей активирован пробный период 30 дней.\n\n— RailTech B2B"
        )
    else:
        body = (
            f"К сожалению, заявка на роль {app.requested_type.name} отклонена.\n"
            f"Комментарий: {app.review_notes or '—'}\n\n— RailTech B2B"
        )
    send_mail(
        subject, body,
        getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@railtech.uz'),
        list(owners.values_list('email', flat=True)),
        fail_silently=True,
    )


def record_subscription_payment(
    subscription: SupplierSubscription, amount, months: int = 1,
    actor: Optional[CustomUser] = None, manual: bool = True,
) -> SupplierSubscription:
    """Extend subscription and set ACTIVE after a successful payment.

    NOTE: manual=True flag indicates the payment was recorded by hand (no provider webhook).
    Logged in ActivityLog with MANUAL_MODE marker so reconciliation is possible later
    when a real payment provider (Click/Payme/Stripe) replaces the manual flow.
    See memory `tech_debt_payment_esign.md`.
    """
    from datetime import timedelta
    from crm.models import ActivityLog
    today = timezone.now().date()
    base = max(today, subscription.valid_until or today)
    subscription.valid_until = base + timedelta(days=30 * months)
    subscription.last_payment_date = today
    subscription.next_payment_date = subscription.valid_until
    subscription.status = 'ACTIVE'
    subscription.save(update_fields=[
        'valid_until', 'last_payment_date', 'next_payment_date', 'status', 'updated_at',
    ])
    marker = '[MANUAL_MODE] ' if manual else ''
    ActivityLog.objects.create(
        action=f"{marker}Оплата подписки",
        detail=(
            f"Подписка компании {subscription.company.name}: "
            f"+{months} мес, сумма {amount}. Действует до {subscription.valid_until}."
        ),
        user=actor, level='SUCCESS',
    )
    return subscription


def check_and_expire_subscriptions() -> dict:
    """Move expired TRIAL/ACTIVE subscriptions to PAST_DUE, then to SUSPENDED if 14+ days overdue."""
    from datetime import timedelta
    today = timezone.now().date()
    # Step 1: fresh expirations → PAST_DUE
    just_expired = SupplierSubscription.objects.filter(
        status__in=['TRIAL', 'ACTIVE'], valid_until__lt=today,
    )
    past_due_count = just_expired.update(status='PAST_DUE')
    # Step 2: PAST_DUE >= 14 days → SUSPENDED
    threshold = today - timedelta(days=14)
    suspended_count = SupplierSubscription.objects.filter(
        status='PAST_DUE', valid_until__lt=threshold,
    ).update(status='SUSPENDED')
    return {'past_due': past_due_count, 'suspended': suspended_count}


def reject_role_application(
    application: CompanyRoleApplication,
    reviewer: CustomUser,
    reason: str = '',
) -> Tuple[Optional[CompanyRoleApplication], Optional[str]]:
    """Reject a CompanyRoleApplication. Returns (app, error_or_None)."""
    if application.status not in ('PENDING', 'PAYMENT_REQUIRED', 'DOCUMENTS_REQUIRED'):
        return None, 'ROLE_APPLICATION_CANNOT_REJECT'

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
        return None, 'CURRENT_PASSWORD_WRONG'
    user.set_password(new_password)
    user.save(update_fields=['password'])
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
        return None, 'CANNOT_DEACTIVATE_SELF'
    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])
    return user, None


def upload_kyc_document(
    company: Company,
    file_obj,
    doc_type_code: str = 'OTHER',
) -> Tuple[Optional['KYCDocument'], Optional[str]]:
    """
    Upload a KYC document for a company with file validation.
    Returns: (document, error_or_None)
    """
    from django.core.validators import FileExtensionValidator
    from django.core.exceptions import ValidationError as DjangoValidationError
    from .models import KYCDocType, KYCDocument

    allowed_extensions = ['pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx']
    max_size = 10 * 1024 * 1024  # 10MB

    if file_obj.size > max_size:
        return None, 'FILE_TOO_LARGE'

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
    valid_statuses = {'ACTIVE', 'SUSPENDED', 'CANCELLED', 'TRIAL', 'PAST_DUE'}
    if new_status not in valid_statuses:
        raise ValueError(f"Invalid status '{new_status}'. Allowed: {valid_statuses}")
    return subscriptions.update(status=new_status)
