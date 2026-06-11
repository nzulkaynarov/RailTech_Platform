import logging
from typing import Optional

from ..constants import WorkspaceRoleCode
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


def is_seller(user: "CustomUser") -> bool:
    """True if the user is on the seller team — any active membership with can_sell.

    Single-seller model (today RailTech is the only seller): the seller operates
    across ALL buyer заявки/deals to build КП, sign as manager, invoice, fulfill.
    The seller is NOT a member of the buyer's deal.company, so seller-side authz
    keys off this capability rather than deal-company membership. When multi-seller
    lands, scope this per accepted SupplierBid instead of "sees everything".
    """
    if not user or not user.is_authenticated:
        return False
    return user.memberships.filter(is_active=True, can_sell=True).exists()


def primary_seller_company_id(user: "CustomUser") -> Optional[int]:
    """The seller company to anchor Quote.prepared_by on (prefers the primary
    membership). None if the user has no can_sell membership."""
    if not user or not user.is_authenticated:
        return None
    membership = user.memberships.filter(is_active=True, can_sell=True).order_by("-is_primary", "id").first()
    return membership.company_id if membership else None


def has_workspace_role(user: "CustomUser", company_id: int, role_codes) -> bool:
    """True if `user` is an active member of `company_id` holding one of `role_codes`.

    OWNER always passes — they administer the team and are the escape hatch. Used
    to gate the КП approval chain so each step is advanced only by the right role,
    and only inside the company that owns the quote (no cross-tenant action).
    """
    if not user or not user.is_authenticated:
        return False
    membership = user.memberships.filter(company_id=company_id, is_active=True).select_related("role").first()
    if membership is None or membership.role is None:
        return False
    code = membership.role.code
    return code == WorkspaceRoleCode.OWNER or code in set(role_codes)


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
