"""Акт по РУЧНОМУ счёту (без договора) — видимость в боевом списке актов (F1, класс дефекта #463).

У счёта G2 без договора владелец выводится через позиции → исходное КП, а `generate_act` копирует
договор из счёта, поэтому у такого акта NULL и в `contract`, и в `invoice__contract`. Раньше это
давало утечку акта со-роутед продавцу; с M1-ERP-02 волна 3 продавец один — компания-владелец, и
инвариант звучит так: акт видят сотрудники своей компании и покупатель сделки, а посторонний
(участник другой компании, даже с флагом can_sell) — нет.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import Deal, DealStage, Invoice, InvoiceItem, InvoiceStatus, Quote, QuoteItem, QuoteStatus
from crm.services.billing import generate_act

ACTS_URL = "/api/v1/crm/acts/"


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code, name in (("CLIENT", "Client"), ("SUPPLIER", "Supplier")):
        CompanyType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    for code in ("USER", "ADMIN"):
        SystemRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    DealStage.objects.get_or_create(code="CLOSED_WON", defaults={"name": "Won", "sort_order": 80})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Sent", "sort_order": 50})
    for code in ("DRAFT", "ISSUED", "PAID", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    from crm.models import ActStatus

    for code in ("DRAFT", "ISSUED", "SIGNED", "CANCELLED"):
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code=type_code))
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


@pytest.fixture
def act_on_manual_invoice(lookups):
    """Сотрудник своей компании выставляет РУЧНОЙ счёт (без договора) по КП и выпускает акт.
    Посторонний — участник другой компании-клиента."""
    buyer_co = _company("Buyer Co", "B800", "CLIENT")
    _member(buyer_co, "buyer@act.test")

    winner_co = _company("Own Co", "S800", "SUPPLIER")
    winner_user = _member(winner_co, "winner@act.test", can_sell=True)

    loser_co = _company("Other Client", "S801", "CLIENT")
    loser_user = _member(loser_co, "outsider@act.test", can_sell=True)

    deal = Deal.objects.create(
        title="Manual act deal", company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON")
    )

    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        seller_company=winner_co,
        prepared_by=winner_user,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    quote_item = QuoteItem.objects.create(
        quote=quote, imported_raw_name="Рельс Р65", quantity=1, unit="шт", frozen_base_price=Decimal("100")
    )

    # G2 ручной счёт: договора нет, владелец резолвится через исходное КП позиции.
    invoice = Invoice.objects.create(
        deal=deal,
        contract=None,
        number="INV-MANUAL-ACT",
        status=InvoiceStatus.objects.get(code="PAID"),
        total_incl_vat=Decimal("112"),
        amount_paid=Decimal("112"),
    )
    InvoiceItem.objects.create(
        invoice=invoice,
        description="Рельс Р65",
        quantity=Decimal("1"),
        unit_price_excl_vat=Decimal("100"),
        line_total_excl_vat=Decimal("100"),
        source_quote_item=quote_item,
    )

    act, error = generate_act(invoice.id, actor=winner_user)
    assert error is None, f"акт не выпустился: {error}"
    return {"act": act, "invoice": invoice, "staff_user": winner_user, "outsider_user": loser_user, "deal": deal}


def _ids(resp):
    data = resp.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    return {row["id"] for row in rows}


def test_manual_invoice_act_has_no_contract_chain(act_on_manual_invoice):
    """Предпосылка дефекта, зафиксированная явно: у такого акта обе договорные ссылки пусты,
    поэтому прежний единственный путь резолва владельца ничего не находил."""
    act = act_on_manual_invoice["act"]
    assert act.contract_id is None
    assert act.invoice.contract_id is None


def test_outsider_does_not_see_the_manual_act_in_the_list(act_on_manual_invoice):
    """Граница — в БОЕВОМ списке актов, а не только в сводке документов сделки."""
    resp = _api(act_on_manual_invoice["outsider_user"]).get(ACTS_URL)
    assert resp.status_code == 200
    assert act_on_manual_invoice["act"].id not in _ids(resp), "акт виден постороннему"


def test_staff_sees_the_manual_act(act_on_manual_invoice):
    """Контроль: сотрудник своей компании (выпустивший акт) его видит."""
    resp = _api(act_on_manual_invoice["staff_user"]).get(ACTS_URL)
    assert resp.status_code == 200
    assert act_on_manual_invoice["act"].id in _ids(resp), "сотрудник потерял собственный акт"


def test_buyer_still_sees_the_act(act_on_manual_invoice):
    """Покупатель — вторая законная сторона — акт видит по-прежнему."""
    buyer = CustomUser.objects.get(email="buyer@act.test")
    resp = _api(buyer).get(ACTS_URL)
    assert resp.status_code == 200
    assert act_on_manual_invoice["act"].id in _ids(resp)
