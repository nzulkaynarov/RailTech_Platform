import logging
from typing import Optional

from ..constants import ALL_PERMISSIONS
from ..models import CustomUser

logger = logging.getLogger(__name__)

_CATALOG = frozenset(ALL_PERMISSIONS)


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


def staff_permissions(user: "CustomUser") -> frozenset:
    """Действующие права сотрудника бэк-офиса — объединение прав всех его ролей в своей компании.

    Администратор (`is_superuser`) — весь каталог прав. Не сотрудник своей компании (покупательский
    аккаунт, пользователь без компании) — пусто. Никаких выводов из должности OWNER или флагов
    `can_sell`/`can_buy` (сняты в M1-ERP-05): нет роли — нет права. Коды вне каталога
    (`accounts.constants.Permission`) отбрасываются.
    """
    if not user or not user.is_authenticated:
        return frozenset()
    if getattr(user, "is_superuser", False):
        return frozenset(ALL_PERMISSIONS)
    from core.tenant import own_company_id

    company_id = own_company_id()
    if company_id is None:
        return frozenset()
    from ..models import CompanyRole

    role_permissions = CompanyRole.objects.filter(
        company_id=company_id, members__user=user, members__company_id=company_id, members__is_active=True
    ).values_list("permissions", flat=True)
    granted = {code for permissions in role_permissions for code in (permissions or [])}
    return frozenset(granted & _CATALOG)


def staff_has_permission(user: "CustomUser", perm) -> bool:
    """Есть ли у сотрудника бэк-офиса право `perm` (или хотя бы одно из набора `perm`)."""
    granted = staff_permissions(user)
    if isinstance(perm, (tuple, list, set, frozenset)):
        return any(code in granted for code in perm)
    return perm in granted


def member_has_permission(user: "CustomUser", company_id: int, perm: str) -> bool:
    """Право пользователя действовать от имени компании `company_id` (M1-ERP-05).

    Администратор (`is_superuser`) — всегда. Своя компания — объединение прав ролей сотрудника
    (`staff_permissions`). Компания-клиент — покупательский аккаунт, правила до M2-ERP-01
    изолированы в `accounts.services.buyer_access`.
    """
    if not user or not user.is_authenticated or not company_id:
        return False
    if getattr(user, "is_superuser", False):
        return True
    from core.tenant import own_company_id

    if company_id == own_company_id():
        return staff_has_permission(user, perm)
    from .buyer_access import buyer_has_permission

    return buyer_has_permission(user, company_id, perm)


def is_seller(user: "CustomUser") -> bool:
    """Сотрудник бэк-офиса — активный участник компании-владельца (`core.tenant.own_company_id`).

    Сторона «продавец» больше не выводится из флага `can_sell`, типа компании или заголовка
    контекста: продавец один, и это своя компания. Что сотруднику можно делать, решают права
    роли (`member_has_permission`). Имя функции историческое (продавец один — своя компания).
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
