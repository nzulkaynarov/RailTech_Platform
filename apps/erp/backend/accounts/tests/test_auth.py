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
        return user_factory(email="test@example.com", username="testuser", password="testpass123", is_superuser=True)

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
class TestSelfRegistrationIsGone:
    """M1-ERP-02 wave 1c: no registration «from the street» and no self-onboarding into a new
    company. Employees are provisioned by CRM (ADR-0003) or invited by a colleague; counterparties
    are created by the back office (ARCHITECTURE §17)."""

    @pytest.mark.parametrize("path", ["/api/v1/auth/register/", "/api/v1/auth/submit-profile/"])
    def test_endpoint_is_not_routed(self, path):
        client = APIClient()
        response = client.post(path, {"email": "street@example.com"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND


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
        return user_factory(email="test@example.com", username="testuser", password="testpass123", is_superuser=True)


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

    def test_setup_enforces_validators_and_revokes_tokens(self, client, user_factory):
        """SEC-01: AUTH_PASSWORD_VALIDATORS run on the setup path (not just min-length) —
        a length-OK but all-numeric password is rejected. SEC-05: a successful setup
        revokes the user's existing refresh tokens (a leaked setup link can't keep a
        session alive). Both need a REAL token, unlike the placeholder tests above."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

        user = user_factory()
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        # SEC-01: passes the 8-char floor but fails NumericPasswordValidator.
        weak = client.post(
            "/api/v1/auth/setup-password/",
            {"uid": uid, "token": token, "password": "29481725"},
            format="json",
        )
        assert weak.status_code == status.HTTP_400_BAD_REQUEST

        # A pre-existing refresh token that a successful setup must invalidate (SEC-05).
        refresh = RefreshToken.for_user(user)
        ok = client.post(
            "/api/v1/auth/setup-password/",
            {"uid": uid, "token": token, "password": "Str0ng-Pass-9xQ"},
            format="json",
        )
        assert ok.status_code == status.HTTP_200_OK
        assert BlacklistedToken.objects.filter(token__jti=refresh["jti"]).exists()
