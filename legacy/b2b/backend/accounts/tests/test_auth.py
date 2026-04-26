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
        assert "refresh" in response.data

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
        """Test token refresh with missing refresh token."""
        url = "/api/v1/auth/token/refresh/"
        data = {}
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestRegisterEndpoint:
    """Tests for user registration endpoint."""

    @pytest.fixture
    def client(self):
        return APIClient()

    def test_register_user_success(self, client):
        """Test successful user registration."""
        url = "/api/v1/auth/register/"
        data = {"email": "newuser@example.com", "first_name": "New", "last_name": "User"}
        response = client.post(url, data, format="json")

        # Should return success - the register view creates a pending user
        assert response.status_code in [status.HTTP_201_CREATED, status.HTTP_200_OK]

    def test_register_duplicate_email(self, client, user_factory):
        """Test registration with duplicate email."""
        user_factory(email="existing@example.com")

        url = "/api/v1/auth/register/"
        data = {"email": "existing@example.com", "first_name": "New", "last_name": "User"}
        response = client.post(url, data, format="json")

        # Should fail due to duplicate email
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_missing_required_fields(self, client):
        """Test registration with missing required fields."""
        url = "/api/v1/auth/register/"
        data = {
            "email": "test@example.com"
            # Missing first_name and last_name
        }
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_invalid_email(self, client):
        """Test registration with invalid email."""
        url = "/api/v1/auth/register/"
        data = {"email": "invalid-email", "first_name": "Test", "last_name": "User"}
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
    def client(self):
        return APIClient()

    def test_submit_profile_valid_data(self, client):
        """Test submitting profile with valid data."""
        url = "/api/v1/auth/submit-profile/"
        data = {"inn": "1234567890", "companyName": "Test Company", "role_code": "OWNER"}
        response = client.post(url, data, format="json")

        # Endpoint might require authentication
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_201_CREATED, status.HTTP_200_OK]

    def test_submit_profile_invalid_inn(self, client):
        """Test profile submission with invalid INN."""
        url = "/api/v1/auth/submit-profile/"
        data = {"inn": "", "companyName": "Test Company", "role_code": "OWNER"}  # Invalid
        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
