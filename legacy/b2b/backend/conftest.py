import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from accounts.models import Company, CompanyMember, SystemRole, WorkspaceRole, VerificationStatus

User = get_user_model()


@pytest.fixture
def api_client():
    """REST API client for making requests."""
    return APIClient()


@pytest.fixture
def authenticated_client(api_client, user_factory):
    """API client with authenticated user."""
    user = user_factory()
    refresh = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    return api_client


@pytest.fixture
def user_factory(db):
    """Factory for creating test users."""
    def create_user(
        email='testuser@example.com',
        username='testuser',
        password='testpass123',
        first_name='Test',
        last_name='User',
        is_active=True,
        is_staff=False
    ):
        user = User.objects.create_user(
            email=email,
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            is_active=is_active,
            is_staff=is_staff,
        )
        return user
    return create_user


@pytest.fixture
def company_factory(db):
    """Factory for creating test companies."""
    def create_company(
        name='Test Company',
        inn='1234567890',
        email='company@example.com',
        phone='+1234567890',
        legal_address='123 Main St',
        website='https://example.com',
        country=None,
        kyc_notes='',
    ):
        # Get or create verification status
        verification_status, _ = VerificationStatus.objects.get_or_create(
            code='L1_UNVERIFIED',
            defaults={'name': 'L1 Unverified'}
        )

        company = Company.objects.create(
            name=name,
            inn=inn,
            email=email,
            phone=phone,
            legal_address=legal_address,
            website=website,
            country=country,
            kyc_notes=kyc_notes,
            verification_status=verification_status,
        )
        return company
    return create_company


@pytest.fixture
def system_role_factory(db):
    """Factory for creating system roles."""
    def create_role(
        code='CLIENT',
        name='Client',
        is_staff_level=False
    ):
        role, _ = SystemRole.objects.get_or_create(
            code=code,
            defaults={'name': name, 'is_staff_level': is_staff_level}
        )
        return role
    return create_role


@pytest.fixture
def workspace_role_factory(db):
    """Factory for creating workspace roles."""
    def create_role(
        code='OWNER',
        name='Owner'
    ):
        role, _ = WorkspaceRole.objects.get_or_create(
            code=code,
            defaults={'name': name}
        )
        return role
    return create_role


@pytest.fixture
def authenticated_user(user_factory):
    """Create a default authenticated user."""
    return user_factory(
        email='auth@example.com',
        username='authuser',
        password='authpass123'
    )
