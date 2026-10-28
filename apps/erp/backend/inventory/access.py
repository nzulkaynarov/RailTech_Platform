"""Права склада и закупок (D2-2): кто читает, кто действует, кто видит цены поставщиков.

Чтение склада и заказов поставщикам открыто любому сотруднику компании (активному участнику своей компании) — отдельного
кода права «читать склад» в ERP нет (`erp.stock: read` в каталоге Платформы кода ERP не даёт; как и у расчёта D2-1, граница
чтения — «сотрудник»). Действия — коды ERP из раздела `erp.stock` (platform-rbac.yaml): заказы поставщикам, резервы,
приёмка, корректировки, запросы цен — `supply.manage`; отгрузки — `fulfillment.manage`. Цены поставщиков (цена в заказе,
сумма заказа) — по тем же правилам, что в расчёте D2-1: `quote.view_cost_margin` или право визы товаров
`quote.visa_goods` (зона товаров). Администратор (`is_superuser`) — всё.
"""

from __future__ import annotations

from typing import Any

from accounts.constants import Permission
from accounts.services.permissions import is_seller, member_has_permission


class StockError(Exception):
    """Отказ правила склада или закупок; вьюхи отдают `{"detail": code}` со статусом `status`."""

    def __init__(self, code: str, status: int = 409, **extra: Any) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.extra = extra


def _own_company_id():
    from core.tenant import own_company_id

    return own_company_id()


def has_perm(user, perm: str) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    company_id = _own_company_id()
    return bool(company_id) and member_has_permission(user, company_id, perm)


def require_staff(user) -> None:
    if not (getattr(user, "is_superuser", False) or is_seller(user)):
        raise StockError("BACKOFFICE_ONLY", 403)


def require_perm(user, perm: str) -> None:
    require_staff(user)
    if not has_perm(user, perm):
        raise StockError("ROLE_NOT_PERMITTED", 403)


def require_supply(user) -> None:
    require_perm(user, Permission.SUPPLY_MANAGE.value)


def require_fulfillment(user) -> None:
    require_perm(user, Permission.FULFILLMENT_MANAGE.value)


def can_manage_supply(user) -> bool:
    return has_perm(user, Permission.SUPPLY_MANAGE.value)


def can_manage_fulfillment(user) -> bool:
    return has_perm(user, Permission.FULFILLMENT_MANAGE.value)


def can_see_supplier_prices(user) -> bool:
    """Цены поставщиков: `quote.view_cost_margin` или зона товаров (`quote.visa_goods`), как в расчёте D2-1."""
    return has_perm(user, Permission.QUOTE_VIEW_COST_MARGIN.value) or has_perm(user, Permission.QUOTE_VISA_GOODS.value)


def person_name(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or user.email or "").strip() or f"Сотрудник #{user.pk}"
