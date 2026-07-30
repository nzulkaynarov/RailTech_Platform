"""Сторону зрителя считает сервер, а не страница (F1, ролевая ловушка `activeStatus`).

SPA выводила роль из `activeStatus` — это ПЕРВЫЙ тип компании. У компании, которая и покупает,
и продаёт, с порядком типов [CLIENT, SUPPLIER] кнопка «Сформировать акт» пряталась за
`!isBuyer` и не показывалась никогда, хотя бэкенд действие разрешал. Образец правильного
решения уже был рядом — `viewer_can_sign_client/manager` у договора.

Здесь проверяется, что подсказки:
  * приходят по КАЖДОЙ стороне независимо (dual-компания получает обе);
  * не зависят от заголовка активного контекста SPA;
  * учитывают статус документа (по оплаченному счёту платить не предлагают);
  * не стоят по запросу на строку (N+1 на реестре).
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from crm.models import (
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    Fulfillment,
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)

INVOICES_URL = "/api/v1/crm/invoices/"
FULFILLMENTS_URL = "/api/v1/crm/fulfillments/"


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code, name in (("CLIENT", "Client"), ("SUPPLIER", "Supplier")):
        CompanyType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    for code in ("USER", "ADMIN"):
        SystemRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    DealStage.objects.get_or_create(code="CLOSED_WON", defaults={"name": "Won", "sort_order": 80})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Sent", "sort_order": 50})
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 40})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("PENDING", "DELIVERED", "ACCEPTED"):
        FulfillmentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _company(name, inn, *type_codes):
    company = Company.objects.create(
        name=name, inn=inn, verification_status=VerificationStatus.objects.get(code="L2_VERIFIED")
    )
    for code in type_codes:
        company.types.add(CompanyType.objects.get(code=code))
    return company


def _member(company, email, *, can_sell=False, can_buy=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )
    return user


def _api(user, ctx=None):
    client = APIClient()
    creds = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}
    if ctx:
        creds["HTTP_X_ACTIVE_CONTEXT"] = ctx
    client.credentials(**creds)
    return client


def _rows(resp):
    data = resp.json()
    return data["results"] if isinstance(data, dict) and "results" in data else data


def _make_chain(buyer_co, seller_co, *, invoice_status="ISSUED", title="Deal"):
    """Сделка покупателя buyer_co, разосланная seller_co, с подписанным договором и счётом."""
    deal = Deal.objects.create(title=title, company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_co)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        seller_company=seller_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number=f"CT-SIDE-{deal.id}",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    invoice = Invoice.objects.create(
        deal=deal,
        contract=contract,
        number=f"INV-SIDE-{deal.id}",
        status=InvoiceStatus.objects.get(code=invoice_status),
        total_incl_vat=Decimal("112"),
        amount_paid=Decimal("112") if invoice_status == "PAID" else Decimal("0"),
    )
    return {"deal": deal, "contract": contract, "invoice": invoice}


@pytest.fixture
def dual_company_world(lookups):
    """Компания-посредник: САМА закупает у поставщика и САМА продаёт клиенту.

    Типы идут в порядке [CLIENT, SUPPLIER] — именно тот случай, когда `activeStatus`
    (первый тип) прятал продавцовскую половину интерфейса.
    """
    dual_co = _company("Dual Trading", "D900", "CLIENT", "SUPPLIER")
    SupplierSubscription.objects.create(
        company=dual_co, plan="PREMIUM", status="ACTIVE", valid_until=timezone.now().date() + timedelta(days=30)
    )
    dual_user = _member(dual_co, "dual@sides.test", can_sell=True, can_buy=True)

    # Сделка, где dual-компания ПОКУПАЕТ (владелец сделки) и сама же разослана как продавец.
    chain = _make_chain(dual_co, dual_co, title="Dual own deal")
    return {"user": dual_user, "company": dual_co, **chain}


def test_dual_company_gets_both_sides_on_an_invoice(dual_company_world):
    """Главный случай ловушки: обе половины интерфейса должны быть доступны одновременно."""
    resp = _api(dual_company_world["user"]).get(INVOICES_URL)
    assert resp.status_code == 200
    row = next(r for r in _rows(resp) if r["id"] == dual_company_world["invoice"].id)

    assert row["viewer_can_manage"] is True, "продавцовская половина потеряна — это и был баг"
    assert row["viewer_can_pay"] is True, "покупательская половина потеряна"


@pytest.mark.parametrize("ctx", ["BUYER", "SELLER", None])
def test_side_hints_ignore_the_active_context_header(dual_company_world, ctx):
    """Подсказка описывает отношение к сделке, а не то, на какой вкладке пользователь."""
    resp = _api(dual_company_world["user"], ctx).get(INVOICES_URL)
    row = next(r for r in _rows(resp) if r["id"] == dual_company_world["invoice"].id)
    assert row["viewer_can_manage"] is True, f"ctx={ctx} повлиял на сторону"
    assert row["viewer_can_pay"] is True, f"ctx={ctx} повлиял на сторону"


def test_pure_buyer_is_not_offered_seller_actions(lookups):
    buyer_co = _company("Pure Buyer", "B901", "CLIENT")
    buyer_user = _member(buyer_co, "purebuyer@sides.test", can_buy=True)
    seller_co = _company("Seller", "S901", "SUPPLIER")
    chain = _make_chain(buyer_co, seller_co)

    row = next(r for r in _rows(_api(buyer_user).get(INVOICES_URL)) if r["id"] == chain["invoice"].id)
    assert row["viewer_can_pay"] is True
    assert row["viewer_can_manage"] is False, "покупателю предложили продавцовское действие"


def test_paid_invoice_is_not_offered_for_payment(lookups):
    """Статус документа тоже учитывается — иначе кнопка ведёт в гарантированный отказ."""
    buyer_co = _company("Buyer Paid", "B902", "CLIENT")
    buyer_user = _member(buyer_co, "paid@sides.test", can_buy=True)
    seller_co = _company("Seller Paid", "S902", "SUPPLIER")
    chain = _make_chain(buyer_co, seller_co, invoice_status="PAID")

    row = next(r for r in _rows(_api(buyer_user).get(INVOICES_URL)) if r["id"] == chain["invoice"].id)
    assert row["viewer_can_pay"] is False


def test_fulfillment_sides_split_ship_and_accept(lookups):
    """Отгружает продавец, принимает покупатель — ровно как делит стороны сервис."""
    buyer_co = _company("Buyer Ship", "B903", "CLIENT")
    buyer_user = _member(buyer_co, "buyership@sides.test", can_buy=True)
    seller_co = _company("Seller Ship", "S903", "SUPPLIER")
    seller_user = _member(seller_co, "sellership@sides.test", can_sell=True)
    chain = _make_chain(buyer_co, seller_co)
    Fulfillment.objects.create(
        deal=chain["deal"], contract=chain["contract"], status=FulfillmentStatus.objects.get(code="DELIVERED")
    )

    seller_row = _rows(_api(seller_user, "SELLER").get(FULFILLMENTS_URL))[0]
    assert seller_row["viewer_can_ship"] is True
    assert seller_row["viewer_can_accept"] is False

    buyer_row = _rows(_api(buyer_user).get(FULFILLMENTS_URL))[0]
    assert buyer_row["viewer_can_accept"] is True
    assert buyer_row["viewer_can_ship"] is False


def test_side_hints_do_not_add_a_query_per_row(lookups):
    """Подсказки считаются один раз на запрос: реестр из пяти счетов не должен стоить
    дороже реестра из одного (иначе это N+1, Performance Conventions)."""
    buyer_co = _company("Buyer NPlus", "B904", "CLIENT")
    buyer_user = _member(buyer_co, "nplus@sides.test", can_buy=True)
    seller_co = _company("Seller NPlus", "S904", "SUPPLIER")

    _make_chain(buyer_co, seller_co, title="Only deal")
    client = _api(buyer_user)
    client.get(INVOICES_URL)  # прогрев: ленивые импорты и кэш схемы не должны попасть в замер

    with CaptureQueriesContext(connection) as one_row:
        client.get(INVOICES_URL)

    for index in range(4):
        _make_chain(buyer_co, seller_co, title=f"Extra deal {index}")

    with CaptureQueriesContext(connection) as five_rows:
        resp = client.get(INVOICES_URL)
    assert len(_rows(resp)) == 5, "фикстура должна отдать пять счетов, иначе замер бессмыслен"

    assert len(five_rows) <= len(
        one_row
    ), f"число запросов выросло с {len(one_row)} до {len(five_rows)} при росте списка — подсказки дают N+1"
