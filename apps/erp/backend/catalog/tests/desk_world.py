"""Мир тестов D2-3: своя компания, сотрудники с наборами прав ролей Платформы, поставщик с предложениями.

Наборы прав ERP — то, что CRM выдаёт сотруднику по каталогу ролей (`packages/contracts/platform-rbac.yaml`):
`erp.stock: full` → catalog.manage, catalog.publish, supply.manage, fulfillment.manage; `erp.calc: full` →
deal.manage, quote.build, quote.edit_pricing; поле `cost_margin` → quote.view_cost_margin. Права зон расчёта
(`quote.visa_goods`, `quote.visa_services`, D2-1) добавляются, когда они есть в каталоге прав.
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.constants import ALL_PERMISSIONS
from accounts.models import Company, CompanyMember, CompanyRole, CustomUser, WorkspaceRole
from accounts.testing import make_own_company
from catalog.models import Category, DomainType, Product, StockStatus, SupplierOffer
from core.models import Currency, UnitOfMeasure

STOCK_FULL = ["catalog.manage", "catalog.publish", "supply.manage", "fulfillment.manage"]
CALC_FULL = ["deal.manage", "quote.build", "quote.edit_pricing"]
COST_MARGIN = ["quote.view_cost_margin"]
SERVICES_ZONE = [code for code in ("quote.visa_services",) if code in ALL_PERMISSIONS]
GOODS_ZONE = [code for code in ("quote.visa_goods",) if code in ALL_PERMISSIONS]

ROLE_SETS = {
    # SUPPLY: erp.calc.goods + erp.stock, поля cost_margin и supplier_prices
    "supply": STOCK_FULL + CALC_FULL + COST_MARGIN + GOODS_ZONE,
    # ENGINEER: erp.calc.services + erp.stock, закрытых полей нет (кроме зоны услуг)
    "engineer": STOCK_FULL + CALC_FULL + SERVICES_ZONE,
    # DIRECTOR: все права
    "director": sorted(ALL_PERMISSIONS),
    # MANAGER: erp.stock — только чтение, прав действий нет
    "manager": [],
    # ACCOUNTANT: erp.stock — чтение, финансы
    "accountant": ["finance.invoice", "finance.payment"],
    # роль каталога без закрытых полей и без права вести каталог
    "viewer": [],
}


def client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def make_staff(company, key: str, permissions=None, label: str | None = None) -> CustomUser:
    label = label or key
    email = f"{label}@d2-3.test"
    role = WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Участник", "sort_order": 90})[0]
    company_role = CompanyRole.objects.create(
        company=company, name=f"D2-3 {label}", permissions=list(ROLE_SETS[key] if permissions is None else permissions)
    )
    user = CustomUser.objects.create_user(email=email, username=email, password="pw")
    CompanyMember.objects.create(
        user=user, company=company, role=role, company_roles=[company_role], is_active=True, is_primary=True
    )
    return user


def build_world() -> dict:
    """Своя компания, сотрудники всех ролей, поставщик с тремя предложениями (действует, скоро истекает, истекло)."""
    own = make_own_company(Company.objects.create(name="Своя компания", inn="300000001"))
    users = {key: make_staff(own, key) for key in ROLE_SETS}
    clients = {key: client_for(user) for key, user in users.items()}
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "symbol": "$", "sort_order": 1})[0]
    uzs = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "symbol": "сум", "sort_order": 2})[0]
    unit = UnitOfMeasure.objects.get_or_create(code="pcs", defaults={"name": "шт", "sort_order": 1})[0]
    category = Category.objects.create(name="Электрооборудование")
    goods = DomainType.objects.get(code="GENERAL_GOODS")
    services = DomainType.objects.get(code="SERVICES")
    in_stock = StockStatus.objects.get_or_create(code="IN_STOCK", defaults={"name": "В наличии"})[0]

    def product(name, **extra):
        return Product.objects.create(name=name, domain_type=extra.pop("domain_type", goods), uom=unit, **extra)

    cable = product("Кабель силовой ВВГнг 3×2,5", category=category, owner_company=own)
    relay = product("Реле защиты РЗ-1", owner_company=own)
    commissioning = product("Пусконаладочные работы", domain_type=services, fulfillment_policy="time")
    supplier = Company.objects.create(name="ООО Поставщик Север", inn="300000777", contact_person="Менеджер Север")
    today = timezone.localdate()

    def offer(prod, price, **extra):
        return SupplierOffer.objects.create(
            product=prod, supplier=supplier, base_price=Decimal(price), currency=usd, **extra
        )

    live = offer(
        cable,
        "12.50",
        stock_quantity=500,
        in_stock_lead_time_days=2,
        stock_status=in_stock,
        valid_until=today + timedelta(days=90),
    )
    soon = offer(relay, "310.00", stock_quantity=0, order_lead_time_days=21, valid_until=today + timedelta(days=5))
    gone = offer(commissioning, "1500.00", valid_until=today - timedelta(days=3))
    return {
        "own": own,
        "users": users,
        "clients": clients,
        "usd": usd,
        "uzs": uzs,
        "unit": unit,
        "category": category,
        "cable": cable,
        "relay": relay,
        "commissioning": commissioning,
        "supplier": supplier,
        "offers": {"live": live, "soon": soon, "gone": gone},
    }
