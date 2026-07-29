"""W2 (spec-inbound-rfq, утв. 27-07): одна кнопка «Взять в работу и подготовить КП».

One-click-quotation (Odoo): claim + стадия CALCULATING + предзаполненный КП одной операцией —
вместо 4–6 ручных шагов на двух экранах. Оркестрация существующих сервисов (claim_deal,
transition_deal_stage FSM, общий builder копии строк). AI-режим (ai.draft) уходит в существующий
async job — здесь тестируется маршрутизация режимов и детерминированный путь.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import (
    Company,
    CompanyMember,
    CompanyRole,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    VerificationStatus,
    WorkspaceRole,
)
from catalog.models import Product, SupplierOffer
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services.draft_quote import prefill_created_quote, take_and_prepare_quote
from master_data.models import Currency


@pytest.fixture(autouse=True)
def _ai_off(settings):
    settings.ANTHROPIC_API_KEY = ""  # детерминированные тесты — LLM выключен


@pytest.fixture
def scene(db):
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
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
    routing = DealSellerRouting.objects.create(deal=deal, seller_company=seller)
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


def _grant_ai(seller):
    SupplierSubscription.objects.create(
        company=seller,
        plan="BASIC",
        status="ACTIVE",
        valid_from=timezone.now().date(),
        valid_until=(timezone.now() + timedelta(days=365)).date(),
    )


@pytest.mark.django_db
def test_one_click_claims_advances_stage_and_prefills_quote(scene):
    """Не-entitled продавец: claim + RFQ_OPEN→CALCULATING (один FSM-переход) + КП со строками."""
    result, err = take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    assert err is None
    assert result["mode"] == "quote"

    scene["routing"].refresh_from_db()
    assert scene["routing"].assigned_to_id == scene["seller_user"].id  # claim записан
    assert scene["routing"].assigned_at is not None  # SLA-якорь

    scene["deal"].refresh_from_db()
    assert scene["deal"].stage.code == "CALCULATING"  # стадия прогнана без Kanban-drag

    quote = result["quote"]
    assert quote.prepared_by_id == scene["seller_user"].id
    items = list(quote.items.all())
    assert len(items) == 2  # строки заявки скопированы — КП не пустой
    matched = next(i for i in items if i.product_id)
    assert matched.frozen_base_price == Decimal("120.00")  # цена из своего оффера, без AI


@pytest.mark.django_db
def test_one_click_is_idempotent(scene):
    first, _ = take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    second, err = take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    assert err is None
    assert second["quote"].id == first["quote"].id  # повторный клик не плодит КП v3
    assert Quote.objects.filter(deal=scene["deal"]).count() == 2  # заявка v1 + КП v2


@pytest.mark.django_db
def test_one_click_routes_entitled_seller_to_ai_mode(scene):
    _grant_ai(scene["seller"])
    result, err = take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    assert err is None
    assert result["mode"] == "ai" and result["quote"] is None  # КП создаст AI-job (view enqueues)
    scene["deal"].refresh_from_db()
    assert scene["deal"].stage.code == "CALCULATING"  # claim+стадия сделаны синхронно уже здесь


@pytest.mark.django_db
def test_one_click_refuses_when_teammate_owns_the_deal(scene):
    take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    result, err = take_and_prepare_quote(scene["deal"].id, scene["teammate"])
    assert result is None
    assert err == "DEAL_ALREADY_CLAIMED"  # чужую работу не перехватываем молча


@pytest.mark.django_db
def test_one_click_refuses_outside_pre_kp_stages(scene):
    scene["deal"].stage = DealStage.objects.get(code="QUOTE_SENT")
    scene["deal"].save()
    result, err = take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    assert result is None
    assert err == "DEAL_STAGE_NOT_TAKEABLE"  # после отправки КП короткой кнопке делать нечего


@pytest.mark.django_db
def test_manual_quote_create_prefills_request_lines(scene):
    """Разрыв №4: ручной «Сформировать КП» больше не создаёт ПУСТОЙ КП."""
    draft = QuoteStatus.objects.get(code="DRAFT")
    manual = Quote.objects.create(
        deal=scene["deal"],
        version=2,
        status=draft,
        prepared_by=scene["seller_user"],
        seller_company=scene["seller"],
    )
    copied = prefill_created_quote(manual)
    assert copied == 2
    assert manual.items.count() == 2
    # Идемпотентность: непустой КП никогда не дозаполняется повторно.
    assert prefill_created_quote(manual) == 0
    assert manual.items.count() == 2
