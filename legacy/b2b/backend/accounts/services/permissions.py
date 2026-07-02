import logging
from typing import Optional

from ..constants import SELLER_COMPANY_TYPES, WorkspaceRoleCode
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


_SELL_PERMS = {
    "quote.build",
    "quote.send",
    "quote.view_cost_margin",
    "quote.edit_pricing",
    "catalog.manage",
    "catalog.publish",
}
_BUY_PERMS = {"request.create", "quote.approve", "contract.sign", "payment.record"}
_ADMIN_PERMS = {"team.manage", "settings.edit", "charge_templates.manage"}


def member_has_permission(user: "CustomUser", company_id: int, perm: str) -> bool:
    """Company Role+Permission-set check (rbac-roles-design-2026-06-25).

    Superuser → always. Active member with a `company_role` → its permission set.
    Until a member is migrated to a CompanyRole, fall back to deriving the permission
    from the legacy OWNER role + can_sell/can_buy flags, so nothing breaks mid-rollout.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return True
    membership = (
        user.memberships.filter(company_id=company_id, is_active=True).select_related("company_role", "role").first()
    )
    if membership is None:
        return False
    if membership.company_role_id:
        return membership.company_role.has_perm(perm)
    # Legacy fallback (no CompanyRole assigned yet).
    if membership.role_id and getattr(membership.role, "code", None) == WorkspaceRoleCode.OWNER:
        return True
    if perm in _ADMIN_PERMS:
        return False
    if perm in _SELL_PERMS:
        return bool(membership.can_sell)
    if perm in _BUY_PERMS:
        return bool(membership.can_buy)
    return bool(membership.can_sell or membership.can_buy)  # e.g. data.export


def is_seller(user: "CustomUser") -> bool:
    """True if the user is on the seller team — an active can_sell membership in a
    SELLER-type company (SUPPLIER / MANUFACTURER).

    CRITICAL: `can_sell` DEFAULTS TO TRUE on every CompanyMember, so checking
    can_sell alone would make EVERY user (incl. brand-new CLIENTS) a "seller" and
    grant them the cross-tenant "see all deals" queryset — a data leak. The
    company-type filter is what keeps a client a client. Since the seller operates
    across ALL buyer заявки/deals (single-seller model, RailTech) and is not a
    member of the buyer's deal.company, seller-side authz keys off this rather than
    deal-company membership.
    """
    if not user or not user.is_authenticated:
        return False
    return user.memberships.filter(
        is_active=True,
        can_sell=True,
        company__types__code__in=SELLER_COMPANY_TYPES,
    ).exists()


def primary_seller_company_id(user: "CustomUser") -> Optional[int]:
    """The seller company to anchor Quote.prepared_by on (prefers the primary
    membership). None if the user has no can_sell membership in a SELLER company."""
    if not user or not user.is_authenticated:
        return None
    membership = (
        user.memberships.filter(
            is_active=True,
            can_sell=True,
            company__types__code__in=SELLER_COMPANY_TYPES,
        )
        .order_by("-is_primary", "id")
        .first()
    )
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


def operator_has_permission(user: "CustomUser", perm: str) -> bool:
    """Platform-operator sub-capability check (ADR-0004 G1) — THE operator enforcement point.

    Mirrors `member_has_permission` but PLATFORM-scoped (no company_id): it gates which
    platform-staff actions an operator may take, not tenant operations.

      * superuser → always (DBA emergency bypass, parity with the other guards)
      * not a platform operator at all (`is_platform_admin` False) → never
      * operator with no `operator_role` assigned → full access (backward-compatible:
        the legacy single ADMIN == SUPER_OPERATOR; granular restriction is opt-in once a
        narrower role is assigned, so an un-migrated/new admin is never accidentally locked out)
      * otherwise → the assigned OperatorRole's permission set
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return True
    if not getattr(user, "is_platform_admin", False):
        return False
    op_role = getattr(user, "operator_role", None)
    if op_role is None:
        return True
    return op_role.has_perm(perm)


def can_view_quote_costs(user: "CustomUser") -> bool:
    """True if the viewer may see КП cost/margin fields (base price, logistics, customs,
    margin, landed cost, charges). Superuser / platform-admin always; otherwise a member of
    a SELLER company who holds the `quote.view_cost_margin` permission. This is the sensitive
    gate that replaces the blanket "any seller sees cost" — a restricted seller-team role
    (e.g. Наблюдатель) no longer sees margin."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False) or is_platform_admin_viewer(user):
        return True
    seller_company_ids = (
        user.memberships.filter(is_active=True, company__types__code__in=SELLER_COMPANY_TYPES)
        .values_list("company_id", flat=True)
        .distinct()
    )
    return any(member_has_permission(user, cid, "quote.view_cost_margin") for cid in seller_company_ids)


def can_view_quote_costs_for(user: "CustomUser", quote) -> bool:
    """Per-quote cost/margin gate (audit C1). `can_view_quote_costs` answers "may this user
    EVER see cost?"; this also requires the quote to belong to the viewer's OWN company —
    on a deal routed to competing sellers A and B, A must not read B's КП cost/margin.
    Superuser / platform-admin see all; an unclaimed (prepared_by=None) request quote carries
    no real cost yet and is owned by whichever seller builds it.
    """
    if not can_view_quote_costs(user):
        return False
    if getattr(user, "is_superuser", False) or is_platform_admin_viewer(user):
        return True
    prepared_by_id = getattr(quote, "prepared_by_id", None)
    if prepared_by_id is None:
        return True
    from accounts.models import CompanyMember

    viewer_company_ids = set(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    preparer_company_ids = set(
        CompanyMember.objects.filter(user_id=prepared_by_id, is_active=True).values_list("company_id", flat=True)
    )
    return bool(viewer_company_ids & preparer_company_ids)


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


def assert_seller_can_operate(actor: "CustomUser") -> Optional[str]:
    """Subscription gate for paid seller writes (send КП, sign contract, issue act).

    Returns an error code string to abort with, or None if the actor may proceed:
      * superuser → None (DBA emergency bypass, parity with the other guards)
      * no seller company / no operational SupplierSubscription → "SUBSCRIPTION_REQUIRED"

    Callers must already have established that `actor` is a seller (is_seller);
    this layers the *paid* requirement on top. CLIENT/buyer actions never call it.
    Documented in ADR-0002 ("subscription-gated seller writes").
    """
    if getattr(actor, "is_superuser", False):
        return None
    company_id = primary_seller_company_id(actor)
    if company_id is None or not company_has_operational_subscription(company_id):
        return "SUBSCRIPTION_REQUIRED"
    return None


# Frontend context-switcher value, sent on every SPA request so the backend can
# scope data to the role the user is currently ACTING as (not just what their
# memberships allow). A user who is both a seller and a buyer must, while in the
# BUYER context, see only their own company's deals — not every buyer's заявка.
_SELLER_CONTEXTS = {"SELLER", "MANUFACTURER"}


def acting_context(request) -> str:
    """The X-Active-Context header value (BUYER / SELLER / MANUFACTURER), upper-cased.
    Empty string when absent (non-SPA client)."""
    return (request.META.get("HTTP_X_ACTIVE_CONTEXT") or "").strip().upper()


def seller_sees_all_deals(user: "CustomUser", request) -> bool:
    """Whether this request should receive the cross-company seller queryset.

    True for a platform admin (always), or a seller acting in a SELLER/MANUFACTURER
    context. A seller acting in the BUYER context is scoped to its own company —
    this is what stops a dual seller+buyer user from seeing other buyers' заявки
    while purchasing. SECURITY NOTE: this only ever NARROWS access — it never
    grants more than is_seller() already would, so a forged/missing header can't
    leak data a pure buyer shouldn't see (they fail is_seller and stay scoped).
    A missing header defaults to seller-see-all to preserve non-SPA API clients;
    the SPA always sends the header.
    """
    if getattr(user, "is_platform_admin", False):
        return True
    if not is_seller(user):
        return False
    ctx = acting_context(request)
    return ctx == "" or ctx in _SELLER_CONTEXTS


def seller_visible_deal_ids(user: "CustomUser", request) -> Optional[set]:
    """The deal ids a context-acting seller may see: those routed to one of their
    seller companies (DealSellerRouting) OR offering one of their catalog products
    (defense-in-depth for drafts whose routing rows aren't written yet). This is
    the multi-seller confidentiality boundary that replaces the old see-all leak.

    Returns None when the user is NOT a routing-scoped seller — the caller then
    applies platform-admin see-all (check `is_platform_admin` first) or the
    buyer-company scope. A seller acting in the BUYER context also gets None, so a
    dual seller+buyer user is scoped to its own company while purchasing.
    """
    if getattr(user, "is_platform_admin", False):
        return None
    if not is_seller(user):
        return None
    if acting_context(request) not in ({""} | _SELLER_CONTEXTS):
        return None
    from crm.models import Deal

    seller_company_ids = list(
        user.memberships.filter(
            is_active=True, can_sell=True, company__types__code__in=SELLER_COMPANY_TYPES
        ).values_list("company_id", flat=True)
    )
    # ROUTING ROWS ONLY. A prior version also OR'd in "deals that merely offer one of my
    # products" — but that leaked: a buyer adding seller A's product to a deal routed to
    # seller B made the whole of B's deal visible to A (review 2026-06-25, CRITICAL).
    # submit_request already writes a DealSellerRouting row per product owner, so the
    # "offers my product" case is covered for submitted deals; unrouted drafts must stay
    # invisible to every seller.
    return set(
        Deal.objects.filter(seller_routings__seller_company_id__in=seller_company_ids).values_list("id", flat=True)
    )


def seller_can_access_deal(user: "CustomUser", request, deal_id) -> bool:
    """Object-level counterpart of `seller_visible_deal_ids` — a single EXISTS query
    for one deal. A context-acting seller may act on `deal_id` IFF it is routed to
    one of their seller companies or offers one of their catalog products.
    """
    if not is_seller(user):
        return False
    if acting_context(request) not in ({""} | _SELLER_CONTEXTS):
        return False
    from crm.models import Deal

    seller_company_ids = list(
        user.memberships.filter(
            is_active=True, can_sell=True, company__types__code__in=SELLER_COMPANY_TYPES
        ).values_list("company_id", flat=True)
    )
    # Routing rows only — see seller_visible_deal_ids (the product-owner OR-clause leaked).
    return Deal.objects.filter(pk=deal_id, seller_routings__seller_company_id__in=seller_company_ids).exists()


def seller_company_routed_to_deal(user: "CustomUser", deal_id) -> bool:
    """Service-layer (NO request/acting-context) binding: True if the actor has a can_sell
    SELLER company that is a routing target of `deal_id`. Seller write actions (contract
    sign, act issuance, fulfillment state) must bind to the specific deal they're routed
    to — `is_seller(actor)` alone let any seller act on a competitor's deal (review
    2026-06-25 platform audit H3/H4/M1).
    """
    if not user or not user.is_authenticated:
        return False
    from crm.models import Deal

    seller_company_ids = list(
        user.memberships.filter(
            is_active=True, can_sell=True, company__types__code__in=SELLER_COMPANY_TYPES
        ).values_list("company_id", flat=True)
    )
    if not seller_company_ids:
        return False
    return Deal.objects.filter(pk=deal_id, seller_routings__seller_company_id__in=seller_company_ids).exists()


def routed_seller_company_id(user: "CustomUser", deal_id) -> Optional[int]:
    """WHICH of the actor's can_sell SELLER companies is a routing target of `deal_id`, or None.

    Stronger form of `seller_company_routed_to_deal` that returns the company id, so the КП
    approval chain can anchor the КП-owning company to a *verified routed seller* before it
    writes `quote.prepared_by`. Without this, any authenticated user could claim an unclaimed
    buyer-request КП and drive its approval chain cross-tenant (audit F0).
    """
    if not user or not user.is_authenticated:
        return None
    from crm.models import DealSellerRouting

    routed_ids = set(DealSellerRouting.objects.filter(deal_id=deal_id).values_list("seller_company_id", flat=True))
    if not routed_ids:
        return None
    # The actor's active can_sell SELLER memberships that are routed to this deal, ordered
    # DETERMINISTICALLY (audit M5 — no arbitrary .first()): prefer the primary membership, then
    # prefer a company where the actor holds a chain-advancing role (OWNER/SALES_MANAGER), so the
    # downstream role check in submit_for_review resolves against the RIGHT company.
    memberships = (
        user.memberships.filter(
            is_active=True,
            can_sell=True,
            company__types__code__in=SELLER_COMPANY_TYPES,
            company_id__in=routed_ids,
        )
        .select_related("role")
        .order_by("-is_primary", "company_id")
    )
    chain_roles = {WorkspaceRoleCode.OWNER, WorkspaceRoleCode.SALES_MANAGER}
    fallback_id = None
    for membership in memberships:
        if fallback_id is None:
            fallback_id = membership.company_id
        if membership.role and membership.role.code in chain_roles:
            return membership.company_id
    return fallback_id


def seller_acting_company_ids(user: "CustomUser", request):
    """The viewer's can_sell SELLER company ids when ACTING as a seller (seller context),
    else None. Used to scope quote querysets to the seller's OWN КП — on a deal routed to
    competing sellers, each must see only the quotes their own company prepared (audit H1).
    """
    if getattr(user, "is_platform_admin", False):
        return None
    if not is_seller(user):
        return None
    if acting_context(request) not in ({""} | _SELLER_CONTEXTS):
        return None
    return set(
        user.memberships.filter(
            is_active=True, can_sell=True, company__types__code__in=SELLER_COMPANY_TYPES
        ).values_list("company_id", flat=True)
    )


def can_edit_quote_pricing(user: "CustomUser") -> bool:
    """True if the user may WRITE КП pricing (price/margin/logistics/customs/charges).
    Superuser / platform-admin always; otherwise a member of a SELLER company holding the
    `quote.edit_pricing` permission. `can_sell` defaults True, so without this a view-only
    CompanyRole (Наблюдатель) could still tamper with pricing (audit H2)."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False) or is_platform_admin_viewer(user):
        return True
    seller_company_ids = (
        user.memberships.filter(is_active=True, company__types__code__in=SELLER_COMPANY_TYPES)
        .values_list("company_id", flat=True)
        .distinct()
    )
    return any(member_has_permission(user, cid, "quote.edit_pricing") for cid in seller_company_ids)
