"""Общие помощники тестов склада и закупок (D2-2): своя компания, роли как в каталоге Платформы, заявка с расчётом.

Роли — те ERP-права, что даёт каталог `platform-rbac.yaml`: снабженец (`erp.calc.goods` + `erp.stock` полный +
`cost_margin`), гл. инженер (`erp.calc.services` + `erp.stock` полный — без цен поставщиков), бухгалтер и менеджер
(`erp.stock` только чтение — ни одного кода ERP).
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from catalog.models import DomainType, Product
from crm.constants import DealStageCode, QuoteStatusCode
from crm.models import CalcLine, Deal, DealStage, Quote, QuoteItem, QuoteStatus
from master_data.models import Country, Currency

SUPPLY = [
    "quote.build",
    "quote.edit_pricing",
    "quote.view_cost_margin",
    "quote.visa_goods",
    "deal.manage",
    "catalog.manage",
    "catalog.publish",
    "supply.manage",
    "fulfillment.manage",
]
ENGINEER = [
    "quote.build",
    "quote.visa_services",
    "deal.manage",
    "catalog.manage",
    "catalog.publish",
    "supply.manage",
    "fulfillment.manage",
]
SHIPPER = ["fulfillment.manage"]  # только отгрузки, без снабжения
NO_RIGHTS: list[str] = []  # erp.stock: read — ERP кода не даёт


def user(email: str) -> CustomUser:
    return CustomUser.objects.create_user(
        email=email, username=email, password="pw", is_active=True, first_name=email.split("@")[0].title()
    )


def staff(seller: Company, email: str, permissions: list[str]) -> CustomUser:
    role = CompanyRole.objects.create(company=seller, name=f"Роль {email}", permissions=list(permissions))
    account = user(email)
    CompanyMember.objects.create(
        user=account,
        company=seller,
        role=WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "MEMBER", "sort_order": 10})[0],
        company_roles=[role],
        is_primary=True,
        is_active=True,
        can_sell=False,
    )
    return account


def api(account: CustomUser) -> APIClient:
    client = APIClient()
    client.force_authenticate(account)
    return client


def make_world() -> dict:
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})
    Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "sort_order": 10})
    supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})[
        0
    ]
    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})[0]
    seller = Company.objects.create(name="ООО Демо Рейл", inn="7700000301")
    seller.types.add(supplier_type)
    vendor = Company.objects.create(
        name="ООО Вымышленный Поставщик", inn="7700000302", email="sales@vendor.example", language="ru"
    )
    vendor.types.add(supplier_type)
    silent = Company.objects.create(name="ООО Без Почты", inn="7700000303")
    silent.types.add(supplier_type)
    world = {
        "seller": seller,
        "vendor": vendor,
        "silent": silent,
        "supply": staff(seller, "supply@demo.test", SUPPLY),
        "engineer": staff(seller, "engineer@demo.test", ENGINEER),
        "shipper": staff(seller, "shipper@demo.test", SHIPPER),
        "reader": staff(seller, "reader@demo.test", NO_RIGHTS),
        "outsider": user("buyer@client.test"),
    }
    client = Company.objects.create(name="ООО Пример Логистик", inn="6600000301")
    client.types.add(client_type)
    world["client"] = client
    services = DomainType.objects.get_or_create(code="SERVICES", defaults={"name": "Услуги", "sort_order": 20})[0]
    world["rail"] = Product.objects.create(name="Перевод стрелочный Р65 1/11", manufacturer_part_number="СП-Р65-11")
    world["bolt"] = Product.objects.create(name="Болт путевой М22", manufacturer_part_number="БП-М22")
    world["mounting"] = Product.objects.create(name="Монтаж стрелочного перевода", domain_type=services)
    return world


def make_deal(world: dict, goods: list[tuple[Product, int]], *, approved: bool = False, signed: bool = False):
    """Заявка с КП расчёта: строки-товары `goods` (товар, количество). `approved` — КП одобрено; `signed` — договор подписан
    (стадия и исполнение сделки есть: отгрузка возможна)."""
    stage = DealStageCode.CONTRACT_SIGNED if signed else DealStageCode.CALCULATING
    deal = Deal.objects.create(
        title="Стрелочные переводы", company=world["client"], stage=DealStage.objects.get(code=stage)
    )
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        prepared_by=world["supply"],
        status=QuoteStatus.objects.get(code=QuoteStatusCode.APPROVED if approved else QuoteStatusCode.DRAFT),
        seller_company=world["seller"],
    )
    items = []
    for position, (product, quantity) in enumerate(goods, start=1):
        item = QuoteItem(
            quote=quote,
            position=position,
            product=product,
            imported_raw_name=product.name,
            quantity=quantity,
            unit="шт.",
            frozen_base_price=Decimal("1000.00"),
        )
        item.save(skip_recalculate=True)
        CalcLine.objects.create(item=item)
        items.append(item)
    if signed:
        from crm.services.fulfillment import ensure_fulfillment

        ensure_fulfillment(deal)
    return deal, quote, items
