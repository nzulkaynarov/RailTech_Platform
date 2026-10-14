import logging
from typing import Optional

from ..constants import WorkspaceRoleCode
from ..models import CustomUser

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Actor-level guards for business services
#
# ERP — бэк-офис одной компании (BUSINESS §3.3: «продавец один — компания-владелец»).
# Маршрутизация заявок между продавцами («скрытая конкуренция», заголовок контекста
# покупатель / продавец) удалена в M1-ERP-02 волна 3: продавец любой сделки — своя
# компания (`core.tenant.own_company_id`), сотрудник — её активный участник, а что ему можно —
# решают права роли (`member_has_permission`).
# ──────────────────────────────────────────────────────────────────────────


def is_member_of(user: "CustomUser", company_id: int, *, capability: Optional[str] = None) -> bool:
    """True if user is an active CompanyMember of the given company.

    If `capability` is 'sell' or 'buy', also checks the membership's can_sell /
    can_buy flag. OWNER distributes these in the team; a member without the
    flag must be refused at the service layer even if the company has the
    matching CompanyType. (Покупательская сторона — до M2-ERP-01.)
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
    """Сотрудник бэк-офиса — активный участник компании-владельца (`core.tenant.own_company_id`).

    Сторона «продавец» больше не выводится из флага `can_sell`, типа компании или заголовка
    контекста: продавец один, и это своя компания. Что сотруднику можно делать, решают права
    роли (`member_has_permission`). Имя функции историческое — переименование в M1-ERP-03.
    """
    if not user or not user.is_authenticated:
        return False
    from core.tenant import own_company_id

    company_id = own_company_id()
    if company_id is None:
        return False
    return user.memberships.filter(company_id=company_id, is_active=True).exists()


def sees_all_deals(user: "CustomUser") -> bool:
    """Видит ли пользователь все сделки ERP: администратор или сотрудник компании-владельца.

    Продавец любой сделки — своя компания, поэтому фильтра маршрутизации нет. Остальные
    (покупательские аккаунты — до M2-ERP-01) видят только сделки своей компании-клиента.
    """
    if not user or not user.is_authenticated:
        return False
    return bool(getattr(user, "is_superuser", False) or is_seller(user))


def primary_seller_company_id(user: "CustomUser") -> Optional[int]:
    """Компания, от имени которой сотрудник строит КП, выставляет счёт и подписывает документы, —
    всегда компания-владелец. None, если пользователь не её сотрудник."""
    if not is_seller(user):
        return None
    from core.tenant import own_company_id

    return own_company_id()


def seller_company_ids(user: "CustomUser") -> list:
    """`[own_company_id]` для сотрудника, пусто для остальных и для администратора (он видит всё
    и без этого скоупа)."""
    if getattr(user, "is_superuser", False):
        return []
    company_id = primary_seller_company_id(user)
    return [company_id] if company_id else []


def _own_company_permission(user: "CustomUser", perm: str) -> bool:
    """Право роли сотрудника в компании-владельце; администратор — всегда."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return True
    from core.tenant import own_company_id

    company_id = own_company_id()
    return bool(company_id) and member_has_permission(user, company_id, perm)


def can_view_quote_costs(user: "CustomUser") -> bool:
    """True if the viewer may see КП cost/margin fields (base price, logistics, customs,
    margin, landed cost, charges). Administrator (`is_superuser`) always; otherwise a member of
    the own company holding `quote.view_cost_margin` — a restricted back-office role
    (e.g. Наблюдатель) does not see margin."""
    return _own_company_permission(user, "quote.view_cost_margin")


def can_view_quote_costs_for(user: "CustomUser", quote) -> bool:
    """Per-quote cost/margin gate. Every КП belongs to the own company (single seller), so this
    equals `can_view_quote_costs`; the quote argument keeps the callers' per-object call shape."""
    return can_view_quote_costs(user)


def can_edit_quote_pricing(user: "CustomUser") -> bool:
    """True if the user may WRITE КП pricing (price/margin/logistics/customs/charges).
    Administrator (`is_superuser`) always; otherwise a member of the own company holding the
    `quote.edit_pricing` permission. `can_sell` defaults True, so without the permission check a
    view-only CompanyRole (Наблюдатель) could still tamper with pricing (audit H2)."""
    return _own_company_permission(user, "quote.edit_pricing")
