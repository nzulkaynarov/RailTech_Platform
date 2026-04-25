"""
Accounts views package.

Re-exports all ViewSets and Views for backwards compatibility so that
``from accounts.views import CompanyViewSet`` continues to work unchanged.
"""

from accounts.views.company import CompanyViewSet  # noqa: F401
from accounts.views.users import UserViewSet  # noqa: F401
from accounts.views.auth import (  # noqa: F401
    RegisterView, SetupPasswordView, SubmitProfileView,
    ForgotPasswordView, ResetPasswordView, MeView,
)
from accounts.views.applications import (  # noqa: F401
    SupplierSubscriptionViewSet, CompanyRoleApplicationViewSet,
)
from accounts.views.lookups import (  # noqa: F401
    CompanyTypeViewSet, SystemRoleViewSet, WorkspaceRoleViewSet,
)

__all__ = [
    # company
    'CompanyViewSet',
    # users
    'UserViewSet',
    # auth
    'RegisterView',
    'SetupPasswordView',
    'SubmitProfileView',
    'ForgotPasswordView',
    'ResetPasswordView',
    'MeView',
    # applications & subscriptions
    'SupplierSubscriptionViewSet',
    'CompanyRoleApplicationViewSet',
    # lookups
    'CompanyTypeViewSet',
    'SystemRoleViewSet',
    'WorkspaceRoleViewSet',
]
