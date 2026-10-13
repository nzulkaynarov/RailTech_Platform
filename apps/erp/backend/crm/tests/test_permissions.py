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
        user.is_superuser = False
        request = self._make_request(user)
        assert perm.has_permission(request, None) is False

    def test_platform_admin_allowed(self):
        perm = IsPlatformAdmin()
        user = MagicMock()
        user.is_authenticated = True
        user.is_superuser = True
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
        user.is_superuser = False
        request = self._make_request(method="POST", user=user)
        assert perm.has_permission(request, None) is False

    def test_write_allowed_for_admin(self):
        perm = IsPlatformAdminOrReadOnly()
        user = MagicMock()
        user.is_authenticated = True
        user.is_superuser = True
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
        user.is_superuser = True
        request = self._make_request(user)
        assert perm.has_object_permission(request, None, MagicMock()) is True

    def test_company_member_allowed(self):
        perm = IsCompanyMemberOrPlatformAdmin()
        company = MagicMock()
        user = MagicMock()
        user.is_authenticated = True
        user.is_superuser = False
        user.memberships.filter.return_value.exists.return_value = True

        # A plain company-owning resource (has .company, NOT a routed Deal): spec the
        # mock so hasattr(obj, "seller_routings"/"deal_id"/"quote") is False and the
        # seller-routing branch stays inert — this test asserts the company-membership
        # grant, not the seller path (which reaches the ORM under force=True).
        obj = MagicMock(spec=["company"])
        obj.company = company

        request = self._make_request(user)
        assert perm.has_object_permission(request, None, obj) is True

    def test_non_member_denied(self):
        perm = IsCompanyMemberOrPlatformAdmin()
        company = MagicMock()
        user = MagicMock()
        user.is_authenticated = True
        user.is_superuser = False
        user.memberships.filter.return_value.exists.return_value = False

        # Same spec as test_company_member_allowed: this test asserts the company-membership
        # DENIAL, so the seller-routing branch must stay inert. Without the spec the branch
        # runs, and whether it short-circuits depends on the exact ORM call chain inside
        # is_seller() — which made the test pass by accident rather than by intent.
        obj = MagicMock(spec=["company"])
        obj.company = company

        request = self._make_request(user)
        assert perm.has_object_permission(request, None, obj) is False
