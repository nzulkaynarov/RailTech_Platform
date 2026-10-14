"""Права ПОКУПАТЕЛЬСКОГО аккаунта — переходно до M2-ERP-01.

Покупательский аккаунт — участник компании-КЛИЕНТА, который до портала (Cabinet + `/api/portal/v1/*`)
ещё действует в ERP: создаёт запрос, принимает КП, подписывает договор, принимает акт и поставку.
Его права выводятся по-старому — из должности OWNER (WorkspaceRole) и флагов участника
`can_buy` / `can_sell`, а если компании-клиенту когда-то выдали роли с правами — из них.

Сотрудников бэк-офиса (участников своей компании) этот модуль НЕ касается: их права — только
объединение ролей (`accounts.services.permissions.staff_permissions`), без выводов из флагов.
Модуль удаляется вместе с покупательскими путями в M2-ERP-01.
"""

from ..constants import WorkspaceRoleCode

# Наборы прав, которые старая модель выводила из флагов участника (rbac 2026-06-25).
_SELL_DERIVED = {
    "deal.manage",
    "quote.build",
    "quote.send",
    "quote.view_cost_margin",
    "quote.edit_pricing",
    "catalog.manage",
    "catalog.publish",
    "supply.manage",
}
_BUY_DERIVED = {"request.create", "quote.approve", "contract.sign", "payment.record"}
_ADMIN_ONLY = {"team.manage", "settings.edit", "settings.charge_templates"}


def buyer_has_permission(user, company_id, perm: str) -> bool:
    """Право участника компании-клиента `company_id` (покупательский аккаунт, до M2-ERP-01)."""
    if not user or not user.is_authenticated or not company_id:
        return False
    membership = (
        user.memberships.filter(company_id=company_id, is_active=True)
        .select_related("role")
        .prefetch_related("company_roles")
        .first()
    )
    if membership is None:
        return False
    roles = list(membership.company_roles.all())
    if roles:
        return any(role.has_perm(perm) for role in roles)
    # Покупательские действия (акцепт КП, подпись договора, оплата, заявка) — только с флагом
    # `can_buy`, в том числе у владельца: так было в сервисах до M1-ERP-05 (`is_member_of(…, "buy")`).
    if perm in _BUY_DERIVED:
        return bool(membership.can_buy)
    if membership.role_id and membership.role.code == WorkspaceRoleCode.OWNER:
        return True
    if perm in _ADMIN_ONLY:
        return False
    if perm in _SELL_DERIVED:
        return bool(membership.can_sell)
    return bool(membership.can_sell or membership.can_buy)


def is_buyer_account(user) -> bool:
    """Есть ли у пользователя активное членство в компании, отличной от своей (покупатель)."""
    if not user or not user.is_authenticated:
        return False
    from core.tenant import own_company_id

    qs = user.memberships.filter(is_active=True)
    own_id = own_company_id()
    if own_id is not None:
        qs = qs.exclude(company_id=own_id)
    return qs.exists()
