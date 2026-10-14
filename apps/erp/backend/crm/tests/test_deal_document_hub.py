"""«Карточка сделки как хаб» — `GET /crm/deals/{id}/documents/` (F1).

Проверяем три вещи, в порядке важности:

1. **Граница видимости.** Хаб — новый способ добраться до биллинговых документов, поэтому он
   обязан сужать каждый набор ровно как «родной» список. Отдельный тест на то, что проигравший
   со-роутед продавец не видит документы победителя (регресс #463 через новый вход).
2. **Стороны считает сервер.** Компания, которая одновременно покупатель и продавец, должна
   получать обе стороны — клиентский `activeStatus` (= первый тип компании) этого не умел.
3. **Подсказка следующего шага** идёт по фактическому состоянию цепочки, а не по стадии сделки.
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
    WorkspaceRole,
)
from crm.models import (
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    Fulfillment,
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Payment,
    Quote,
    QuoteStatus,
)


def _hub_url(deal_id: int) -> str:
    return f"/api/v1/crm/deals/{deal_id}/documents/"


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code, name in (("CLIENT", "Client"), ("SUPPLIER", "Supplier")):
        CompanyType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    for code in ("USER", "ADMIN"):
        SystemRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "CONTRACT_SIGNED", "CLOSED_WON"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    for code in ("DRAFT", "PENDING_CLIENT", "PENDING_MANAGER", "SIGNED", "CANCELLED"):
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "OVERDUE", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "SIGNED", "CANCELLED"):
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("PENDING", "SHIPPED", "IN_TRANSIT", "DELIVERED", "ACCEPTED", "DISPUTED"):
        FulfillmentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _company(name, inn, *type_codes):
    company = Company.objects.create(name=name, inn=inn)
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


def _subscribe(company):
    SupplierSubscription.objects.create(
        company=company,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=30),
    )


def _api(user, ctx=None):
    client = APIClient()
    creds = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}
    if ctx:
        creds["HTTP_X_ACTIVE_CONTEXT"] = ctx
    client.credentials(**creds)
    return client


@pytest.fixture
def world(lookups):
    buyer_co = _company("Buyer Co", "B700", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@hub.test", can_buy=True)

    winner_co = _company("Winner Seller", "S700", "SUPPLIER")
    winner_user = _member(winner_co, "winner@hub.test", can_sell=True)
    _subscribe(winner_co)

    loser_co = _company("Loser Seller", "S701", "SUPPLIER")
    loser_user = _member(loser_co, "loser@hub.test", can_sell=True)
    _subscribe(loser_co)

    deal = Deal.objects.create(title="Hub deal", company=buyer_co, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))
    # Обоим продавцам разослана одна заявка — выигрывает один (скрытая конкуренция).
    DealSellerRouting.objects.create(deal=deal, seller_company=winner_co)
    DealSellerRouting.objects.create(deal=deal, seller_company=loser_co)

    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        seller_company=winner_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    return {
        "deal": deal,
        "quote": quote,
        "buyer_co": buyer_co,
        "buyer_user": buyer_user,
        "winner_co": winner_co,
        "winner_user": winner_user,
        "loser_user": loser_user,
    }


def _sign_contract(world, *, status_code="SIGNED"):
    signed = timezone.now() if status_code == "SIGNED" else None
    return Contract.objects.create(
        deal=world["deal"],
        quote=world["quote"],
        number=f"CT-HUB-{status_code}",
        status=ContractStatus.objects.get(code=status_code),
        total_amount=Decimal("112"),
        client_signer=world["buyer_user"] if signed else None,
        client_signed_at=signed,
        manager_signer=world["winner_user"] if signed else None,
        manager_signed_at=signed,
    )


def _invoice(world, contract, code="ISSUED", *, paid=Decimal("0")):
    return Invoice.objects.create(
        deal=world["deal"],
        contract=contract,
        number=f"INV-HUB-{code}",
        status=InvoiceStatus.objects.get(code=code),
        total_incl_vat=Decimal("112"),
        amount_paid=paid,
    )


# ── 1. Граница видимости ─────────────────────────────────────────────────────


def test_losing_co_routed_seller_sees_no_documents_of_the_winner(world):
    """Скрытая конкуренция (ADR-0003 §5) держится и через новый вход.

    Проигравший продавец заявку видит (она ему тоже была разослана), но цепочка документов
    победителя для него пуста.
    """
    contract = _sign_contract(world)
    _invoice(world, contract)
    Act.objects.create(
        deal=world["deal"],
        contract=contract,
        number="ACT-HUB-1",
        status=ActStatus.objects.get(code="ISSUED"),
        total_amount=Decimal("112"),
    )
    Fulfillment.objects.create(
        deal=world["deal"], contract=contract, status=FulfillmentStatus.objects.get(code="PENDING")
    )

    resp = _api(world["loser_user"], "SELLER").get(_hub_url(world["deal"].id))

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["contract"] is None, "договор победителя утёк проигравшему"
    assert body["invoices"] == [], "счёт победителя утёк проигравшему"
    assert body["acts"] == [], "акт победителя утёк проигравшему"
    assert body["fulfillment"] is None, "отгрузка победителя утекла проигравшему"


def test_winner_and_buyer_both_see_the_chain(world):
    """Контроль к предыдущему тесту: обе стороны сделки цепочку видят — иначе «пусто»
    в тесте выше ничего не доказывало бы."""
    contract = _sign_contract(world)
    _invoice(world, contract)

    for key in ("winner_user", "buyer_user"):
        body = _api(world[key], "BUYER").get(_hub_url(world["deal"].id)).json()
        assert body["contract"] is not None, f"{key} не видит договор"
        assert [inv["number"] for inv in body["invoices"]] == ["INV-HUB-ISSUED"], f"{key} не видит счёт"


def test_buyer_never_sees_a_sellers_draft_invoice(world):
    """Черновик счёта — рабочая копия продавца (канон Odoo). Правило переиспользовано из
    списка счетов, а не переписано."""
    contract = _sign_contract(world)
    _invoice(world, contract, "DRAFT")

    buyer_body = _api(world["buyer_user"]).get(_hub_url(world["deal"].id)).json()
    assert buyer_body["invoices"] == [], "покупатель увидел черновик счёта продавца"

    seller_body = _api(world["winner_user"]).get(_hub_url(world["deal"].id)).json()
    assert [inv["status"] for inv in seller_body["invoices"]] == ["DRAFT"]


# ── 2. Стороны считает сервер, а не страница ─────────────────────────────────


def test_dual_company_gets_both_sides_regardless_of_context_header(lookups):
    """Ловушка `activeStatus`: у компании с типами [CLIENT, SUPPLIER] клиент брал ПЕРВЫЙ тип
    и прятал продавцовские действия. Сервер обязан отдать обе стороны в любом контексте."""
    dual_co = _company("Dual Co", "D700", "CLIENT", "SUPPLIER")
    _subscribe(dual_co)
    dual_user = _member(dual_co, "dual@hub.test", can_sell=True, can_buy=True)

    deal = Deal.objects.create(title="Dual deal", company=dual_co, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))
    DealSellerRouting.objects.create(deal=deal, seller_company=dual_co)

    for ctx in ("BUYER", "SELLER", None):
        viewer = _api(dual_user, ctx).get(_hub_url(deal.id)).json()["viewer"]
        assert viewer["is_buyer_side"] is True, f"потеряна покупательская сторона при ctx={ctx}"
        assert viewer["is_seller_side"] is True, f"потеряна продавцовская сторона при ctx={ctx}"


def test_buyer_is_not_marked_as_seller_side(world):
    viewer = _api(world["buyer_user"]).get(_hub_url(world["deal"].id)).json()["viewer"]
    assert viewer["is_buyer_side"] is True
    assert viewer["is_seller_side"] is False


# ── 3. Подсказка следующего шага ─────────────────────────────────────────────


def test_next_step_is_sign_contract_while_unsigned_and_addressed_to_the_signer(world):
    _sign_contract(world, status_code="PENDING_CLIENT")

    buyer_step = _api(world["buyer_user"]).get(_hub_url(world["deal"].id)).json()["next_step"]
    assert buyer_step["code"] == "SIGN_CONTRACT"
    assert buyer_step["for_viewer"] is True, "покупателю, который и подписывает, шаг адресован"
    assert buyer_step["page"] == "contracts"


def test_next_step_walks_the_chain_invoice_then_act(world):
    """Шаг определяется состоянием цепочки, а не стадией сделки."""
    contract = _sign_contract(world)
    seller = _api(world["winner_user"])

    draft = _invoice(world, contract, "DRAFT")
    step = seller.get(_hub_url(world["deal"].id)).json()["next_step"]
    assert step["code"] == "ISSUE_INVOICE" and step["object_id"] == draft.id

    draft.status = InvoiceStatus.objects.get(code="ISSUED")
    draft.save(update_fields=["status"])
    step = seller.get(_hub_url(world["deal"].id)).json()["next_step"]
    assert step["code"] == "PAY_INVOICE"
    assert step["for_viewer"] is False, "продавцу шаг «оплатить» не адресован — он ждёт оплату"

    buyer_step = _api(world["buyer_user"]).get(_hub_url(world["deal"].id)).json()["next_step"]
    assert buyer_step["for_viewer"] is True, "покупателю шаг «оплатить» адресован"

    draft.status = InvoiceStatus.objects.get(code="PAID")
    draft.amount_paid = Decimal("112")
    draft.save(update_fields=["status", "amount_paid"])
    Fulfillment.objects.create(
        deal=world["deal"], contract=contract, status=FulfillmentStatus.objects.get(code="PENDING")
    )
    step = seller.get(_hub_url(world["deal"].id)).json()["next_step"]
    # G1: оплата больше НЕ триггер закрывающего документа — после денег цепочка ведёт к
    # отгрузке, а акт предлагается по факту поставки (см. test_act_trigger_and_due_date.py).
    assert step["code"] == "SHIP"


def test_next_step_accept_delivery_is_addressed_to_the_buyer(world):
    contract = _sign_contract(world)
    invoice = _invoice(world, contract, "PAID", paid=Decimal("112"))
    Act.objects.create(
        deal=world["deal"],
        contract=contract,
        invoice=invoice,
        number="ACT-HUB-SIGNED",
        status=ActStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
        signed_at=timezone.now(),
    )
    Fulfillment.objects.create(
        deal=world["deal"], contract=contract, status=FulfillmentStatus.objects.get(code="DELIVERED")
    )

    buyer_step = _api(world["buyer_user"]).get(_hub_url(world["deal"].id)).json()["next_step"]
    assert buyer_step["code"] == "ACCEPT_DELIVERY"
    assert buyer_step["for_viewer"] is True

    seller_step = _api(world["winner_user"]).get(_hub_url(world["deal"].id)).json()["next_step"]
    assert seller_step["code"] == "ACCEPT_DELIVERY"
    assert seller_step["for_viewer"] is False


def test_cancelled_documents_are_excluded_from_the_chain(world):
    """Отменённый договор не должен изображать живую цепочку."""
    cancelled = _sign_contract(world, status_code="CANCELLED")
    assert cancelled.status_code == "CANCELLED"

    body = _api(world["buyer_user"]).get(_hub_url(world["deal"].id)).json()
    # Отменённый договор остаётся в ответе как история, но цепочка по нему не строится.
    assert body["contract"]["status"] == "CANCELLED"
    assert body["next_step"]["code"] == "SIGN_CONTRACT", "отменённый договор не подписан — шаг честен"


def test_payments_total_sums_only_visible_payments(world):
    contract = _sign_contract(world)
    invoice = _invoice(world, contract, "PARTIAL", paid=Decimal("50"))
    Payment.objects.create(invoice=invoice, amount=Decimal("50"), paid_at=timezone.localdate())

    body = _api(world["buyer_user"]).get(_hub_url(world["deal"].id)).json()
    assert body["payments_count"] == 1
    assert Decimal(body["payments_total"]) == Decimal("50")

    loser_body = _api(world["loser_user"], "SELLER").get(_hub_url(world["deal"].id)).json()
    assert loser_body["payments_count"] == 0, "платёж победителя виден проигравшему"
