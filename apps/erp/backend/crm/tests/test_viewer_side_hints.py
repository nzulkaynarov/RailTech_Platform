"""Сторону зрителя считает сервер, а не страница (F1, ролевая ловушка `activeStatus`).

SPA выводила роль из `activeStatus` — это ПЕРВЫЙ тип компании. У компании, которая и покупает,
и продаёт, с порядком типов [CLIENT, SUPPLIER] кнопка «Сформировать акт» пряталась за
`!isBuyer` и не показывалась никогда, хотя бэкенд действие разрешал. Образец правильного
решения уже был рядом — `viewer_can_sign_client/manager` у договора.

С M1-ERP-02 волна 3 сторона продавца — это сотрудник своей компании (продавец один), заголовка
контекста SPA больше нет. Покупательской стороны в ERP нет (FIX-13), её подсказки и тесты ушли.

Здесь проверяется, что подсказки не стоят по запросу на строку (N+1 на реестре).
"""

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import (
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)

INVOICES_URL = "/api/v1/crm/invoices/"


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code, name in (("CLIENT", "Client"), ("SUPPLIER", "Supplier")):
        CompanyType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
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
        name=name,
        inn=inn,
        # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
        bank_account="20208000900001234567",
        mfo="00443",
    )
    for code in type_codes:
        company.types.add(CompanyType.objects.get(code=code))
    return company


def _member(company, email, *, can_sell=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
    )
    return user


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _rows(resp):
    data = resp.json()
    return data["results"] if isinstance(data, dict) and "results" in data else data


def _make_chain(buyer_co, seller_co, *, invoice_status="ISSUED", title="Deal"):
    """Сделка покупателя buyer_co с КП продавца seller_co, подписанным договором и счётом."""
    deal = Deal.objects.create(title=title, company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON"))
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


def test_side_hints_do_not_add_a_query_per_row(lookups):
    """Подсказки считаются один раз на запрос: реестр из пяти счетов не должен стоить
    дороже реестра из одного (иначе это N+1, Performance Conventions)."""
    buyer_co = _company("Buyer NPlus", "B904", "CLIENT")
    buyer_user = _member(buyer_co, "nplus@sides.test")
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
