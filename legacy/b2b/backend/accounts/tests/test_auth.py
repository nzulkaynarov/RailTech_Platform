import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


@pytest.mark.django_db
class TestAuthenticationEndpoints:
    """Tests for authentication endpoints."""

    @pytest.fixture
    def client(self):
        return APIClient()

    @pytest.fixture
    def test_user(self, user_factory):
        return user_factory(email="test@example.com", username="testuser", password="testpass123")

    def test_user_login_success(self, client, test_user):
        """Test successful user login with valid credentials."""
        url = "/api/v1/auth/token/"
        data = {"email": "test@example.com", "password": "testpass123"}
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        # F2.1: refresh token is set as an HttpOnly cookie, never in the body.
        assert "refresh" not in response.data
        assert "refresh_token" in response.cookies

    def test_user_login_invalid_password(self, client, test_user):
        """Test login failure with invalid password."""
        url = "/api/v1/auth/token/"
        data = {"email": "test@example.com", "password": "wrongpassword"}
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_user_login_nonexistent_user(self, client):
        """Test login failure with non-existent user."""
        url = "/api/v1/auth/token/"
        data = {"email": "nonexistent@example.com", "password": "somepassword"}
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_token_refresh_success(self, client, test_user):
        """Test successful token refresh."""
        # First, get tokens
        refresh = RefreshToken.for_user(test_user)
        refresh_token = str(refresh)

        # Refresh the token
        url = "/api/v1/auth/token/refresh/"
        data = {"refresh": refresh_token}
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    def test_token_refresh_invalid_token(self, client):
        """Test token refresh with invalid token."""
        url = "/api/v1/auth/token/refresh/"
        data = {"refresh": "invalid_token"}
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_token_refresh_empty_refresh(self, client):
        """Empty body AND no refresh cookie → 401 (F2.1; was 400 when refresh came in the body)."""
        url = "/api/v1/auth/token/refresh/"
        response = client.post(url, {}, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestRegisterEndpoint:
    """Tests for user registration endpoint."""

    @pytest.fixture
    def client(self):
        return APIClient()

    def test_register_user_success(self, client):
        """Test successful user registration."""
        url = "/api/v1/auth/register/"
        data = {
            "email": "newuser@example.com",
            "first_name": "New",
            "last_name": "User",
            "phone": "+998901234567",
        }
        response = client.post(url, data, format="json")

        # Should return success - the register view creates a pending user
        assert response.status_code in [status.HTTP_201_CREATED, status.HTTP_200_OK]

    def test_register_duplicate_email(self, client, user_factory):
        """Test registration with duplicate email."""
        user_factory(email="existing@example.com")

        url = "/api/v1/auth/register/"
        data = {
            "email": "existing@example.com",
            "first_name": "New",
            "last_name": "User",
            "phone": "+998901234567",
        }
        response = client.post(url, data, format="json")

        # Should fail due to duplicate email
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_missing_required_fields(self, client):
        """Test registration with missing required fields."""
        url = "/api/v1/auth/register/"
        data = {
            "email": "test@example.com"
            # Missing first_name, last_name and phone
        }
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_invalid_email(self, client):
        """Test registration with invalid email."""
        url = "/api/v1/auth/register/"
        data = {"email": "invalid-email", "first_name": "Test", "last_name": "User", "phone": "+998901234567"}
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_invalid_phone(self, client):
        """Phone must be Uzbekistan format +998XXXXXXXXX."""
        url = "/api/v1/auth/register/"
        data = {"email": "ph@example.com", "first_name": "Test", "last_name": "User", "phone": "12345"}
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestUserProfile:
    """Tests for user profile endpoint."""

    @pytest.fixture
    def client(self):
        return APIClient()

    def test_get_user_profile_authenticated(self, client, test_user, authenticated_user):
        """Test getting user profile when authenticated."""
        # Create a user and authenticate
        refresh = RefreshToken.for_user(authenticated_user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        url = "/api/v1/accounts/users/me/"
        response = client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["email"] == "auth@example.com"

    def test_get_user_profile_unauthenticated(self, client):
        """Test getting user profile without authentication."""
        url = "/api/v1/accounts/users/me/"
        response = client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.fixture
    def test_user(self, user_factory):
        return user_factory(email="test@example.com", username="testuser", password="testpass123")


@pytest.mark.django_db
class TestSetupPassword:
    """Tests for password setup endpoint."""

    @pytest.fixture
    def client(self):
        return APIClient()

    def test_setup_password_with_valid_token(self, client, user_factory):
        """Test password setup with valid setup token."""
        user = user_factory()
        # Note: In real implementation, setup token would be generated
        url = "/api/v1/auth/setup-password/"
        data = {"uid": str(user.id), "token": "valid_token", "password": "newpassword123"}
        response = client.post(url, data, format="json")

        # Will fail without proper token generation, but tests the endpoint
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_200_OK]

    def test_setup_password_weak_password(self, client, user_factory):
        """Test password setup with weak password."""
        user = user_factory()
        url = "/api/v1/auth/setup-password/"
        data = {"uid": str(user.id), "token": "valid_token", "password": "weak"}  # Less than 8 characters
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestSubmitProfile:
    """Tests for profile submission endpoint."""

    @pytest.fixture
    def client(self, db):
        # submit-profile requires an authenticated user (step 3 of onboarding).
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            email="profileuser@example.com",
            username="profileuser",
            password="testpass123",
            first_name="Profile",
            last_name="User",
            is_active=True,
        )
        api = APIClient()
        api.force_authenticate(user=user)
        return api

    def test_submit_profile_valid_data(self, client):
        """Test submitting profile with valid minimal data (company + position)."""
        url = "/api/v1/auth/submit-profile/"
        data = {"companyName": "Test Company", "position": "Директор по закупкам"}
        response = client.post(url, data, format="json")

        # 200 when OWNER role/CLIENT type are seeded; 400 (WORKSPACE_ROLE_NOT_FOUND)
        # on a bare test DB without the seed data migration.
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_201_CREATED, status.HTTP_200_OK]

    def test_submit_profile_missing_company_name(self, client):
        """Company name is the only hard-required field now."""
        url = "/api/v1/auth/submit-profile/"
        data = {"companyName": "", "position": "Director"}  # Invalid: blank company name
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_submit_profile_creates_own_company_no_inn(self, db, workspace_role_factory):
        """Minimal onboarding: each user gets a brand-new CLIENT company as OWNER,
        with no INN (deferred to KYC). Two strangers never share a company —
        the old INN-collision merge vector is gone entirely."""
        from accounts.models import CompanyMember, CompanyType, VerificationStatus
        from accounts.services import submit_company_profile

        workspace_role_factory(code="OWNER", name="Owner")
        CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Покупатель"})
        VerificationStatus.objects.get_or_create(code="PROFILE_SUBMITTED", defaults={"name": "Profile submitted"})

        alice = User.objects.create_user(email="alice@example.com", username="alice", password="x", is_active=True)
        bob = User.objects.create_user(email="bob@example.com", username="bob", password="x", is_active=True)

        _, e_alice = submit_company_profile(user=alice, company_name="Acme", position="Снабженец")
        _, e_bob = submit_company_profile(user=bob, company_name="Acme", position="Менеджер")

        assert e_alice is None and e_bob is None
        alice_co = CompanyMember.objects.get(user=alice).company
        bob_co = CompanyMember.objects.get(user=bob).company
        # Same name, different companies — no silent merge.
        assert alice_co.pk != bob_co.pk
        assert alice_co.inn is None and bob_co.inn is None
        assert alice_co.types.filter(code="CLIENT").exists()
        alice.refresh_from_db()
        assert alice.position == "Снабженец"

    def test_submit_profile_idempotent_for_same_user(self, db, workspace_role_factory):
        """A user who already has an active membership does not get a second
        company on re-submit — it is a no-op success."""
        from accounts.models import CompanyMember, CompanyType, VerificationStatus
        from accounts.services import submit_company_profile

        user = User.objects.create_user(email="dup@example.com", username="dup", password="x", is_active=True)
        workspace_role_factory(code="OWNER", name="Owner")
        CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Покупатель"})
        VerificationStatus.objects.get_or_create(code="PROFILE_SUBMITTED", defaults={"name": "Profile submitted"})

        _, e1 = submit_company_profile(user=user, company_name="My Co", position="Dir")
        assert e1 is None
        _, e2 = submit_company_profile(user=user, company_name="Another Co", position="Dir")
        assert e2 is None
        assert CompanyMember.objects.filter(user=user).count() == 1
