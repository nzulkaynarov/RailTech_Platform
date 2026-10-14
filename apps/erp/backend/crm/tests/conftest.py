"""Общие фикстуры тестов CRM.

`scene` описывает сцену входа клина — покупатель, продавец, заявка, каталожный оффер — и
нужна БОЛЕЕ ЧЕМ одному файлу (W2 «одна кнопка» и скоупинг позиций КП). Импортировать
фикстуру из соседнего теста нельзя: pytest её так и находит, но flake8 видит неиспользуемое
имя и переопределение, а сам приём ломает изоляцию файлов. Место общей фикстуры — conftest.
"""

from decimal import Decimal

import pytest

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product, SupplierOffer
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from master_data.models import Currency


@pytest.fixture(autouse=True)
def _ai_off(settings):
    settings.AI_IMPORT_ENABLED = False  # детерминированные тесты — ИИ выключен


@pytest.fixture
def scene(db):
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$", "sort_order": 10})[0]
    for code, order in (("RFQ_OPEN", 10), ("SOURCING", 20), ("CALCULATING", 30), ("QUOTE_SENT", 40)):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": order})
    draft = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]

    buyer = Company.objects.create(name="Buyer", inn="1110000009")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    seller = Company.objects.create(name="Seller", inn="2220000009")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))

    product = Product.objects.create(name="Автосцепка СА-3")
    SupplierOffer.objects.create(
        product=product, supplier=seller, base_price=Decimal("120.00"), currency=usd, in_stock_lead_time_days=10
    )

    deal = Deal.objects.create(title="RFQ", company=buyer, stage=DealStage.objects.get(code="RFQ_OPEN"))
    request_quote = Quote.objects.create(deal=deal, version=1, status=draft)
    QuoteItem.objects.create(quote=request_quote, product=product, quantity=5)
    QuoteItem.objects.create(quote=request_quote, quantity=2, imported_raw_name="Тормозная колодка")

    role = CompanyRole.objects.create(company=seller, name="Менеджер", permissions=["quote.edit_pricing"])
    ws = WorkspaceRole.objects.get_or_create(code="SALES_MANAGER", defaults={"name": "SM", "sort_order": 10})[0]

    def _member(email):
        user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
        CompanyMember.objects.create(
            user=user, company=seller, role=ws, company_role=role, is_active=True, is_primary=True, can_sell=True
        )
        return user

    seller_user = _member("s1@s.uz")
    teammate = _member("s2@s.uz")
    return locals()
