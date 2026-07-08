"""Multi-seller billing confidentiality (review HIGH, 2026-07-09).

On a hidden-competition deal fanned out to several sellers (DealSellerRouting), only the WINNING
seller's Contract/Invoice/Act/Payment materialize — on the SHARED deal. A LOSING co-routed seller
must NOT see them (its routing row is never pruned). Billing visibility scopes the seller side to
the document's OWN seller_company (via quote.seller_company), not to every routed deal."""

from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from accounts.services.permissions import seller_company_ids
from crm.models import (
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    Invoice,
    InvoiceStatus,
    Payment,
    Quote,
    QuoteStatus,
)
from crm.views.billing import _billing_visibility_q

pytestmark = pytest.mark.django_db


def _seller(name, inn):
    co = Company.objects.create(name=name, inn=inn)
    co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=f"{inn}@s.test", username=f"{inn}@s.test", password="pw")
    CompanyMember.objects.create(
        user=user, company=co, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, can_sell=True
    )
    return co, user


@pytest.fixture
def scenario(db):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    DealStage.objects.get_or_create(code="CONTRACT_SIGNED", defaults={"name": "CS", "sort_order": 60})
    QuoteStatus.objects.get_or_create(code="APPROVED", defaults={"name": "Approved", "sort_order": 50})
    c_status = ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 10})[0]
    i_status = InvoiceStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Issued", "sort_order": 10})[0]
    a_status = ActStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Issued", "sort_order": 10})[0]

    winner, winner_user = _seller("Seller A (winner)", "3000000001")
    loser, loser_user = _seller("Seller C (loser)", "3000000003")

    buyer = Company.objects.create(name="Buyer LLC", inn="6600000001")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    buyer_user = CustomUser.objects.create_user(email="buyer@b.test", username="buyer@b.test", password="pw")
    CompanyMember.objects.create(
        user=buyer_user, company=buyer, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, can_buy=True
    )

    deal = Deal.objects.create(title="Fanned-out", company=buyer, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))
    # Hidden competition: BOTH sellers routed to the SAME deal; the loser's row is never pruned.
    DealSellerRouting.objects.create(deal=deal, seller_company=winner)
    DealSellerRouting.objects.create(deal=deal, seller_company=loser)

    # Winner's КП wins → billing materializes on the shared deal, owned by the winner.
    quote = Quote.objects.create(
        deal=deal, version=1, status=QuoteStatus.objects.get(code="APPROVED"), seller_company=winner,
        subtotal_excl_vat=Decimal("1000000"), vat_amount=Decimal("120000"), total_incl_vat=Decimal("1120000"),
    )
    contract = Contract.objects.create(
        deal=deal, quote=quote, number="CT-1", total_amount=Decimal("1120000"), status=c_status
    )
    invoice = Invoice.objects.create(
        deal=deal, contract=contract, number="INV-1", total_incl_vat=Decimal("1120000"), status=i_status
    )
    act = Act.objects.create(
        deal=deal, contract=contract, invoice=invoice, number="ACT-1", total_amount=Decimal("1120000"), status=a_status
    )
    payment = Payment.objects.create(invoice=invoice, amount=Decimal("1120000"), paid_at=timezone.now())
    return {
        "winner_user": winner_user, "loser_user": loser_user, "buyer_user": buyer_user,
        "contract": contract, "invoice": invoice, "act": act, "payment": payment,
    }


def _visible(model, user, *, deal_path, seller_path):
    return set(
        model.objects.filter(_billing_visibility_q(user, None, deal_path=deal_path, seller_path=seller_path))
        .values_list("pk", flat=True)
    )


def test_losing_seller_cannot_see_winners_contract(scenario):
    loser = scenario["loser_user"]
    assert seller_company_ids(loser)  # loser IS a seller (routed), just not the winner
    ids = _visible(Contract, loser, deal_path="deal", seller_path="quote__seller_company_id")
    assert scenario["contract"].pk not in ids


def test_losing_seller_cannot_see_winners_invoice_act_payment(scenario):
    loser = scenario["loser_user"]
    assert scenario["invoice"].pk not in _visible(
        Invoice, loser, deal_path="deal", seller_path="contract__quote__seller_company_id"
    )
    assert scenario["act"].pk not in _visible(
        Act, loser, deal_path="deal", seller_path="invoice__contract__quote__seller_company_id"
    )
    assert scenario["payment"].pk not in _visible(
        Payment, loser, deal_path="invoice__deal", seller_path="invoice__contract__quote__seller_company_id"
    )


def test_winning_seller_sees_its_own_billing(scenario):
    winner = scenario["winner_user"]
    assert scenario["contract"].pk in _visible(
        Contract, winner, deal_path="deal", seller_path="quote__seller_company_id"
    )
    assert scenario["invoice"].pk in _visible(
        Invoice, winner, deal_path="deal", seller_path="contract__quote__seller_company_id"
    )


def test_buyer_sees_the_deal_billing(scenario):
    buyer = scenario["buyer_user"]
    assert scenario["contract"].pk in _visible(
        Contract, buyer, deal_path="deal", seller_path="quote__seller_company_id"
    )
    assert scenario["payment"].pk in _visible(
        Payment, buyer, deal_path="invoice__deal", seller_path="invoice__contract__quote__seller_company_id"
    )
