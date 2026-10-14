"""
Accounts views package.

Re-exports all ViewSets and Views for backwards compatibility so that
``from accounts.views import CompanyViewSet`` continues to work unchanged.
"""

from accounts.views.applications import CompanyEntitlementViewSet, SupplierSubscriptionViewSet  # noqa: F401
from accounts.views.auth import (  # noqa: F401
    CookieTokenObtainPairView,
    CookieTokenRefreshView,
    ForgotPasswordView,
    LogoutView,
    MeView,
    ResetPasswordView,
    SessionListView,
    SessionsRevokeOthersView,
    SetupPasswordView,
    ThrottledTokenObtainPairView,
    TOTPDisableView,
    TOTPLoginView,
    TOTPSetupView,
    TOTPVerifyView,
    WsTicketView,
)
from accounts.views.clients import ContactViewSet  # noqa: F401
from accounts.views.company import CompanyViewSet  # noqa: F401
from accounts.views.lookups import CompanyTypeViewSet, SystemRoleViewSet, WorkspaceRoleViewSet  # noqa: F401
from accounts.views.roles import CompanyRoleViewSet, PermissionCatalogView  # noqa: F401
from accounts.views.users import UserViewSet  # noqa: F401

__all__ = [
    "CompanyRoleViewSet",
    "PermissionCatalogView",
    # company
    "CompanyViewSet",
    # client base (CRM Phase B)
    "ContactViewSet",
    # users
    "UserViewSet",
    # auth
    "SetupPasswordView",
    "ForgotPasswordView",
    "ResetPasswordView",
    "MeView",
    "LogoutView",
    "WsTicketView",
    "ThrottledTokenObtainPairView",
    "CookieTokenObtainPairView",
    "CookieTokenRefreshView",
    "TOTPSetupView",
    "TOTPVerifyView",
    "TOTPDisableView",
    "TOTPLoginView",
    "SessionListView",
    "SessionsRevokeOthersView",
    # applications & subscriptions
    "SupplierSubscriptionViewSet",
    "CompanyEntitlementViewSet",
    # lookups
    "CompanyTypeViewSet",
    "SystemRoleViewSet",
    "WorkspaceRoleViewSet",
]
