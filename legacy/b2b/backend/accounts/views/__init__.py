"""
Accounts views package.

Re-exports all ViewSets and Views for backwards compatibility so that
``from accounts.views import CompanyViewSet`` continues to work unchanged.
"""

from accounts.views.applications import CompanyRoleApplicationViewSet, SupplierSubscriptionViewSet  # noqa: F401
from accounts.views.auth import (  # noqa: F401
    ForgotPasswordView,
    MeView,
    RegisterView,
    ResetPasswordView,
    SetupPasswordView,
    SubmitProfileView,
)
from accounts.views.company import CompanyViewSet  # noqa: F401
from accounts.views.lookups import CompanyTypeViewSet, SystemRoleViewSet, WorkspaceRoleViewSet  # noqa: F401
from accounts.views.users import UserViewSet  # noqa: F401

__all__ = [
    # company
    "CompanyViewSet",
    # users
    "UserViewSet",
    # auth
    "RegisterView",
    "SetupPasswordView",
    "SubmitProfileView",
    "ForgotPasswordView",
    "ResetPasswordView",
    "MeView",
    # applications & subscriptions
    "SupplierSubscriptionViewSet",
    "CompanyRoleApplicationViewSet",
    # lookups
    "CompanyTypeViewSet",
    "SystemRoleViewSet",
    "WorkspaceRoleViewSet",
]
