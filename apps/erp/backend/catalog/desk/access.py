"""Закрытые поля экрана «Номенклатура и поставщики»: кто видит цены поставщиков и ставки бригад (D2-3).

Поля с ограничением (SPEC-v3 §4.2, каталог ролей `platform-rbac.yaml`) режет ERP сам, а не только BFF: `/api/v1` доступен
и без Платформы. Правило то же, что решил архитектор для расчёта (D2-1, 2026-10-28):

* **цены поставщиков** (`supplier_prices`) — `quote.view_cost_margin` (группа `cost_margin`: директор, снабженец) или зона
  товаров расчёта;
* **ставки бригад** — `quote.view_cost_margin` или зона услуг расчёта (гл. инженер); снабженцу ставка бригады — через
  `cost_margin`, бухгалтеру и менеджеру её не показывают.

Администратор платформы (`is_superuser`) видит всё: `staff_permissions` отдаёт ему весь каталог прав. Платформа и здесь
строже ERP: роль «Администратор» полей `cost_margin` и `supplier_prices` не видит, BFF вырезает их из ответа.

Зоны расчёта — права `quote.visa_goods` и `quote.visa_services` (D2-1, PR #289, ErpPermission 0.8.0). Пока их нет в
каталоге прав (`accounts.constants.Permission`), `staff_permissions` их отбрасывает и работает только `cost_margin`; после
слияния D2-1 зоны подхватываются без правок кода: имена закреплены здесь, а не в каталоге.
"""

from accounts.constants import Permission
from accounts.services.permissions import is_seller, staff_has_permission

COST_MARGIN = Permission.QUOTE_VIEW_COST_MARGIN.value
GOODS_ZONE = "quote.visa_goods"
SERVICES_ZONE = "quote.visa_services"

SUPPLIER_PRICE_PERMISSIONS = (COST_MARGIN, GOODS_ZONE)
CREW_RATE_PERMISSIONS = (COST_MARGIN, SERVICES_ZONE)


def _allowed(user, codes) -> bool:
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser:
        return True
    return is_seller(user) and staff_has_permission(user, codes)


def can_view_supplier_prices(user) -> bool:
    """Цены закупки в предложениях поставщиков: `cost_margin` или зона товаров."""
    return _allowed(user, SUPPLIER_PRICE_PERMISSIONS)


def can_view_crew_rates(user) -> bool:
    """Ставка бригады или исполнителя услуг: `cost_margin` или зона услуг."""
    return _allowed(user, CREW_RATE_PERMISSIONS)
