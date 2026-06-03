import logging
from typing import Optional

from ..models import CustomUser, SupplierSubscription

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Actor-level guards for business services
# ──────────────────────────────────────────────────────────────────────────


def is_member_of(user: "CustomUser", company_id: int, *, capability: Optional[str] = None) -> bool:
    """True if user is an active CompanyMember of the given company.

    If `capability` is 'sell' or 'buy', also checks the membership's can_sell /
    can_buy flag. OWNER distributes these in the team; a member without the
    flag must be refused at the service layer even if the company has the
    matching CompanyType.
    """
    if not user or not user.is_authenticated:
        return False
    qs = user.memberships.filter(company_id=company_id, is_active=True)
    membership = qs.first()
    if membership is None:
        return False
    if capability == "sell":
        return bool(membership.can_sell)
    if capability == "buy":
        return bool(membership.can_buy)
    return True


def is_platform_admin_viewer(user: "CustomUser") -> bool:
    """Platform Admin acting on platform-level — never acts on behalf of a company.

    `is_superuser` is intentionally *excluded*: superuser is the DBA emergency
    bypass and must be able to fix any business record, even on behalf of a
    company. Migration accounts/0010_platform_admin_model removes any
    CompanyMember rows for users with SystemRole.ADMIN, so admin-viewer equals
    "role.code == 'ADMIN' and not is_superuser".

    Kept as a function because business services use the error code
    `ADMIN_VIEWER_CANNOT_ACT`, which conveys intent better than a generic
    "member required" when a platform admin tries to act for a company.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return False
    role_code = getattr(getattr(user, "role", None), "code", None)
    return role_code == "ADMIN"


def company_has_operational_subscription(company_id: int) -> bool:
    """True if the company has a SupplierSubscription that is_operational right now.

    Seller-side write operations (bid submit, offer CRUD, product CRUD) must be
    gated by this — SELLER / MANUFACTURER companies without a valid subscription
    cannot sell on the platform. CLIENTs don't need a subscription to buy.
    """
    sub = SupplierSubscription.objects.filter(company_id=company_id).order_by("-updated_at").first()
    if sub is None:
        return False
    return sub.is_operational
