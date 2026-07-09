"""
Accounts views package.

Re-exports all ViewSets and Views for backwards compatibility so that
``from accounts.views import CompanyViewSet`` continues to work unchanged.
"""

from accounts.views.applications import (  # noqa: F401
    CompanyEntitlementViewSet,
    CompanyRoleApplicationViewSet,
    SupplierSubscriptionViewSet,
)
from accounts.views.auth import (  # noqa: F401
    CookieTokenObtainPairView,
    CookieTokenRefreshView,
    ForgotPasswordView,
    LogoutView,
    MeView,
    RegisterView,
    ResetPasswordView,
    SetupPasswordView,
    SubmitProfileView,
    ThrottledTokenObtainPairView,
    WsTicketView,
    TOTPSetupView,
    TOTPVerifyView,
    TOTPDisableView,
    TOTPLoginView,
)
from accounts.views.clients import ContactViewSet  # noqa: F401
from accounts.views.company import CompanyViewSet  # noqa: F401
from accounts.views.lookups import CompanyTypeViewSet, SystemRoleViewSet, WorkspaceRoleViewSet  # noqa: F401
from accounts.views.operators import OperatorPermissionCatalogView, OperatorRoleViewSet  # noqa: F401
from accounts.views.roles import CompanyRoleViewSet, PermissionCatalogView  # noqa: F401
from accounts.views.users import UserViewSet  # noqa: F401

__all__ = [
    "CompanyRoleViewSet",
    "PermissionCatalogView",
    "OperatorRoleViewSet",
    "OperatorPermissionCatalogView",
    # company
    "CompanyViewSet",
    # client base (CRM Phase B)
    "ContactViewSet",
    # users
    "UserViewSet",
    # auth
    "RegisterView",
    "SetupPasswordView",
    "SubmitProfileView",
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
    # applications & subscriptions
    "SupplierSubscriptionViewSet",
    "CompanyRoleApplicationViewSet",
    "CompanyEntitlementViewSet",
    # lookups
    "CompanyTypeViewSet",
    "SystemRoleViewSet",
    "WorkspaceRoleViewSet",
]
