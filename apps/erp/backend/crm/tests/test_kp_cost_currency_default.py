"""Bug fix (владелец 27-07): «валюта себестоимости» не долетает до строк КП.

CompanySettings.default_cost_currency → Quote.cost_currency_default применялось (шапка КП),
но строки, которыми реально наполняется КП (автокопия строк заявки), брали frozen_currency из
оффера или молча UZS, игнорируя настройку. Фикс: строка БЕЗ своей валюты оффера наследует
cost_currency_default — как ручное добавление строки. Оффер со своей валютой не перекрывается.
"""

from decimal import Decimal

import pytest

from accounts.models import Company, CompanyMember, CompanyRole, CompanySettings, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product, SupplierOffer
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services.draft_quote import prefill_created_quote, take_and_prepare_quote
from crm.services.quotes.access import apply_company_quote_defaults
from master_data.models import Currency


@pytest.fixture(autouse=True)
def _ai_off(settings):
    settings.ANTHROPIC_API_KEY = ""


@pytest.fixture
def scene(db):
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$", "sort_order": 10})[0]
    uzs = Currency.objects.get_or_create(code="UZS", defaults={"name": "Sum", "symbol": "сум", "sort_order": 1})[0]
    for code, order in (("RFQ_OPEN", 10), ("SOURCING", 20), ("CALCULATING", 30)):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": order})
    draft = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]

    buyer = Company.objects.create(name="Buyer", inn="1110001001")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    seller = Company.objects.create(name="Seller", inn="2220001001")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    # Продавец настроил валюту себестоимости USD.
    CompanySettings.objects.update_or_create(company=seller, defaults={"default_cost_currency": usd})

    matched = Product.objects.create(name="Рельс Р65")
    SupplierOffer.objects.create(
        product=matched, supplier=seller, base_price=Decimal("100"), currency=uzs, in_stock_lead_time_days=7
    )

    deal = Deal.objects.create(title="RFQ", company=buyer, stage=DealStage.objects.get(code="RFQ_OPEN"))
    rq = Quote.objects.create(deal=deal, version=1, status=draft)
    QuoteItem.objects.create(quote=rq, product=matched, quantity=5)  # matched → оффер в UZS
    QuoteItem.objects.create(quote=rq, quantity=3, imported_raw_name="Втулка X")  # unmatched → без оффера

    role = CompanyRole.objects.create(company=seller, name="М", permissions=["quote.build", "quote.edit_pricing"])
    ws = WorkspaceRole.objects.get_or_create(code="SALES_MANAGER", defaults={"name": "SM", "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email="cc@s.uz", username="cc@s.uz", password="pw", is_active=True)
    CompanyMember.objects.create(
        user=user, company=seller, role=ws, company_roles=[role], is_active=True, is_primary=True, can_sell=True
    )
    return locals()


@pytest.mark.django_db
def test_prefill_line_without_offer_inherits_cost_currency_default(scene):
    result, err = take_and_prepare_quote(scene["deal"].id, scene["user"])
    assert err is None
    quote = result["quote"]
    assert quote.cost_currency_default.code == "USD"  # шапка КП взяла дефолт
    by_name = {(i.product.name if i.product_id else i.imported_raw_name): i for i in quote.items.all()}
    # Строка с оффером — своя валюта оффера (не перекрыта дефолтом).
    assert by_name["Рельс Р65"].frozen_currency.code == "UZS"
    # Строка без оффера — теперь наследует валюту себестоимости USD (была None → UZS).
    assert by_name["Втулка X"].frozen_currency.code == "USD"


@pytest.mark.django_db
def test_manual_created_quote_prefill_also_inherits_cost_currency(scene):
    draft = QuoteStatus.objects.get(code="DRAFT")
    manual = Quote.objects.create(
        deal=scene["deal"],
        version=2,
        status=draft,
        prepared_by=scene["user"],
        seller_company=scene["seller"],
    )
    apply_company_quote_defaults(manual, scene["seller"])  # как в perform_create
    prefill_created_quote(manual)
    by_name = {(i.product.name if i.product_id else i.imported_raw_name): i for i in manual.items.all()}
    assert by_name["Рельс Р65"].frozen_currency.code == "UZS"
    assert by_name["Втулка X"].frozen_currency.code == "USD"


@pytest.mark.django_db
def test_no_cost_currency_setting_leaves_line_currency_unset(scene):
    # Без настройки валюты себестоимости строка без оффера остаётся без валюты (→ UZS дальше).
    CompanySettings.objects.filter(company=scene["seller"]).update(default_cost_currency=None)
    result, err = take_and_prepare_quote(scene["deal"].id, scene["user"])
    assert err is None
    unmatched = next(i for i in result["quote"].items.all() if not i.product_id)
    assert unmatched.frozen_currency_id is None  # поведение как раньше, без регрессии
