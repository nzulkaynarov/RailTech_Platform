"""Акт по РУЧНОМУ счёту утекал проигравшему со-роутед продавцу (F1, класс дефекта #463).

Владелец биллингового документа выводится через цепочку КП. У счёта эта цепочка двойная
(`_invoice_seller_side_q`): договор → КП, а для G2-счёта БЕЗ договора — позиции → исходное КП.
У акта же владелец резолвился ровно одним путём — `invoice__contract__quote__seller_company`.

`create_manual_invoice` создаёт счёт с `contract=None`, а `generate_act` копирует договор из
счёта, то есть у акта по ручному счёту NULL и в `contract`, и в `invoice__contract`. Владелец
не резолвится → срабатывает legacy-фолбэк «видно любому ПРОРОУТЕННОМУ продавцу», и акт
победителя оказывается в списке актов конкурента, проигравшего ту же заявку.

Это ровно то допущение, которое комментарий к фолбэку объявляет невозможным («the winner's
docs ARE owner-anchored»), — как и в #463 у отгрузки, оно не выполняется для одной модели.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
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
    Deal,
    DealSellerRouting,
    DealStage,
    Invoice,
    InvoiceItem,
    InvoiceStatus,
    Quote,
    QuoteItem,
    QuoteStatus,
)
from crm.services.billing import generate_act

ACTS_URL = "/api/v1/crm/acts/"


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
    for code in ("DRAFT", "ISSUED", "PAID", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    from crm.models import ActStatus

    for code in ("DRAFT", "ISSUED", "SIGNED", "CANCELLED"):
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(
        name=name, inn=inn, verification_status=VerificationStatus.objects.get(code="L2_VERIFIED")
    )
    company.types.add(CompanyType.objects.get(code=type_code))
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


def _subscribe(company):
    SupplierSubscription.objects.create(
        company=company,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=30),
    )


def _api(user, ctx="SELLER"):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ACTIVE_CONTEXT=ctx,
    )
    return client


@pytest.fixture
def act_on_manual_invoice(lookups):
    """Победитель выставляет РУЧНОЙ счёт (без договора) по своему КП и выпускает акт.
    Второй продавец разослан на ту же заявку и проиграл."""
    buyer_co = _company("Buyer Co", "B800", "CLIENT")
    _member(buyer_co, "buyer@act.test", can_buy=True)

    winner_co = _company("Winner", "S800", "SUPPLIER")
    winner_user = _member(winner_co, "winner@act.test", can_sell=True)
    _subscribe(winner_co)

    loser_co = _company("Loser", "S801", "SUPPLIER")
    loser_user = _member(loser_co, "loser@act.test", can_sell=True)
    _subscribe(loser_co)

    deal = Deal.objects.create(
        title="Manual act deal", company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON")
    )
    DealSellerRouting.objects.create(deal=deal, seller_company=winner_co)
    DealSellerRouting.objects.create(deal=deal, seller_company=loser_co)

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
    return {"act": act, "invoice": invoice, "winner_user": winner_user, "loser_user": loser_user, "deal": deal}


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


def test_losing_seller_does_not_see_the_winners_manual_act_in_the_list(act_on_manual_invoice):
    """Дыра в БОЕВОМ списке актов, а не только в сводке документов сделки."""
    resp = _api(act_on_manual_invoice["loser_user"]).get(ACTS_URL)
    assert resp.status_code == 200
    assert act_on_manual_invoice["act"].id not in _ids(resp), "акт победителя виден проигравшему конкуренту"


def test_winner_still_sees_its_own_manual_act(act_on_manual_invoice):
    """Контроль: сузив видимость, нельзя отнять акт у его законного владельца."""
    resp = _api(act_on_manual_invoice["winner_user"]).get(ACTS_URL)
    assert resp.status_code == 200
    assert act_on_manual_invoice["act"].id in _ids(resp), "владелец потерял собственный акт"


def test_buyer_still_sees_the_act(act_on_manual_invoice):
    """Покупатель — вторая законная сторона — акт видит по-прежнему."""
    buyer = CustomUser.objects.get(email="buyer@act.test")
    resp = _api(buyer, ctx="BUYER").get(ACTS_URL)
    assert resp.status_code == 200
    assert act_on_manual_invoice["act"].id in _ids(resp)
