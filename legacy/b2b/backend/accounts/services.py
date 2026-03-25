from typing import Tuple, Optional
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import send_mail
from django.conf import settings
from .models import Company, CustomUser, CompanyMember, SystemRole, WorkspaceRole, VerificationStatus


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
    workspace_role_code: str
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Step 3: User fills in company info and creates membership.
    """
    if not all([inn, company_name, workspace_role_code]):
        return None, "INN, company name and role are required"

    # Status lookups
    submitted_status = VerificationStatus.objects.filter(code='PROFILE_SUBMITTED').first()
    w_role = WorkspaceRole.objects.filter(code=workspace_role_code).first()

    if not w_role:
        return None, f"Role '{workspace_role_code}' not found in master data."

    company, created = Company.objects.get_or_create(
        inn=inn,
        defaults={
            'name': company_name,
            'verification_status': submitted_status
        }
    )

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
