"""Tests for CRM-related permissions and access control logic."""

from unittest.mock import MagicMock

from core.permissions import IsCompanyMemberOrPlatformAdmin, IsPlatformAdmin, IsPlatformAdminOrReadOnly


class TestIsPlatformAdmin:
    """Tests for IsPlatformAdmin permission class."""

    def _make_request(self, user=None):
        request = MagicMock()
        request.user = user
        return request

    def test_anonymous_user_denied(self):
        perm = IsPlatformAdmin()
        user = MagicMock()
        user.is_authenticated = False
        request = self._make_request(user)
        assert perm.has_permission(request, None) is False

    def test_regular_user_denied(self):
        perm = IsPlatformAdmin()
        user = MagicMock()
        user.is_authenticated = True
        user.is_platform_admin = False
        request = self._make_request(user)
        assert perm.has_permission(request, None) is False

    def test_platform_admin_allowed(self):
        perm = IsPlatformAdmin()
        user = MagicMock()
        user.is_authenticated = True
        user.is_platform_admin = True
        request = self._make_request(user)
        assert perm.has_permission(request, None) is True

    def test_none_user_denied(self):
        perm = IsPlatformAdmin()
        request = self._make_request(None)
        assert perm.has_permission(request, None) is False


class TestIsPlatformAdminOrReadOnly:
    """Tests for IsPlatformAdminOrReadOnly permission class."""

    def _make_request(self, method="GET", user=None):
        request = MagicMock()
        request.method = method
        request.user = user
        return request

    def test_safe_methods_allowed_for_anyone(self):
        perm = IsPlatformAdminOrReadOnly()
        for method in ("GET", "HEAD", "OPTIONS"):
            request = self._make_request(method=method)
            assert perm.has_permission(request, None) is True

    def test_write_denied_for_anonymous(self):
        perm = IsPlatformAdminOrReadOnly()
        user = MagicMock()
        user.is_authenticated = False
        request = self._make_request(method="POST", user=user)
        assert perm.has_permission(request, None) is False

    def test_write_denied_for_regular_user(self):
        perm = IsPlatformAdminOrReadOnly()
        user = MagicMock()
        user.is_authenticated = True
        user.is_platform_admin = False
        request = self._make_request(method="POST", user=user)
        assert perm.has_permission(request, None) is False

    def test_write_allowed_for_admin(self):
        perm = IsPlatformAdminOrReadOnly()
        user = MagicMock()
        user.is_authenticated = True
        user.is_platform_admin = True
        request = self._make_request(method="POST", user=user)
        assert perm.has_permission(request, None) is True


class TestIsCompanyMemberOrPlatformAdmin:
    """Tests for IsCompanyMemberOrPlatformAdmin object-level permission."""

    def _make_request(self, user=None):
        request = MagicMock()
        request.user = user
        return request

    def test_anonymous_denied(self):
        perm = IsCompanyMemberOrPlatformAdmin()
        user = MagicMock()
        user.is_authenticated = False
        request = self._make_request(user)
        assert perm.has_object_permission(request, None, MagicMock()) is False

    def test_platform_admin_allowed(self):
        perm = IsCompanyMemberOrPlatformAdmin()
        user = MagicMock()
        user.is_authenticated = True
        user.is_platform_admin = True
        request = self._make_request(user)
        assert perm.has_object_permission(request, None, MagicMock()) is True

    def test_company_member_allowed(self):
        perm = IsCompanyMemberOrPlatformAdmin()
        company = MagicMock()
        user = MagicMock()
        user.is_authenticated = True
        user.is_platform_admin = False
        user.memberships.filter.return_value.exists.return_value = True

        obj = MagicMock()
        obj.company = company

        request = self._make_request(user)
        assert perm.has_object_permission(request, None, obj) is True

    def test_non_member_denied(self):
        perm = IsCompanyMemberOrPlatformAdmin()
        company = MagicMock()
        user = MagicMock()
        user.is_authenticated = True
        user.is_platform_admin = False
        user.memberships.filter.return_value.exists.return_value = False

        obj = MagicMock()
        obj.company = company

        request = self._make_request(user)
        assert perm.has_object_permission(request, None, obj) is False
