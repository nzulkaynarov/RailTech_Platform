"""Tests for Portal Tenant / Company Isolation.

Strict isolation: Accessing another company's resource MUST return 404 {"detail": "NOT_FOUND"},
never leaking existence via 403 or other codes.
"""

from decimal import Decimal

import pytest
from rest_framework import status

from crm.constants import ActStatusCode, ContractStatusCode, DealStageCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import (
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    Fulfillment,
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)


@pytest.fixture
def isolation_data(db, client_company, other_company, client_contact, other_contact):
    draft_stage, _ = DealStage.objects.get_or_create(code=DealStageCode.DRAFT, defaults={"name": "Черновик"})
    sent_quote_status, _ = QuoteStatus.objects.get_or_create(code=QuoteStatusCode.SENT, defaults={"name": "Отправлено"})
    sent_contract_status, _ = ContractStatus.objects.get_or_create(
        code=ContractStatusCode.PENDING_CLIENT, defaults={"name": "На подписи"}
    )
    issued_invoice_status, _ = InvoiceStatus.objects.get_or_create(
        code=InvoiceStatusCode.ISSUED, defaults={"name": "Выставлен"}
    )
    issued_act_status, _ = ActStatus.objects.get_or_create(code=ActStatusCode.ISSUED, defaults={"name": "Выставлен"})
    fulfillment_status, _ = FulfillmentStatus.objects.get_or_create(code="PENDING", defaults={"name": "Ожидает"})

    # 1. Объекты клиента А (client_company)
    deal_a = Deal.objects.create(
        company=client_company,
        contact=client_contact,
        title="Сделка Компании А",
        stage=draft_stage,
    )
    quote_a = Quote.objects.create(
        deal=deal_a,
        version=1,
        status=sent_quote_status,
        total_incl_vat=Decimal("1000000"),
    )
    contract_a = Contract.objects.create(
        deal=deal_a,
        quote=quote_a,
        number="CT-TEST-A-001",
        status=sent_contract_status,
        total_amount=Decimal("1000000"),
    )
    invoice_a = Invoice.objects.create(
        deal=deal_a,
        contract=contract_a,
        number="INV-TEST-A-001",
        status=issued_invoice_status,
        total_incl_vat=Decimal("1000000"),
    )
    act_a = Act.objects.create(
        deal=deal_a,
        contract=contract_a,
        invoice=invoice_a,
        number="ACT-TEST-A-001",
        status=issued_act_status,
        total_amount=Decimal("1000000"),
    )
    fulfillment_a = Fulfillment.objects.create(
        deal=deal_a,
        contract=contract_a,
        status=fulfillment_status,
    )

    # 2. Объекты клиента Б (other_company)
    deal_b = Deal.objects.create(
        company=other_company,
        contact=other_contact,
        title="Сделка Компании Б",
        stage=draft_stage,
    )
    quote_b = Quote.objects.create(
        deal=deal_b,
        version=1,
        status=sent_quote_status,
        total_incl_vat=Decimal("5000000"),
    )
    contract_b = Contract.objects.create(
        deal=deal_b,
        quote=quote_b,
        number="CT-TEST-B-001",
        status=sent_contract_status,
        total_amount=Decimal("5000000"),
    )
    invoice_b = Invoice.objects.create(
        deal=deal_b,
        contract=contract_b,
        number="INV-TEST-B-001",
        status=issued_invoice_status,
        total_incl_vat=Decimal("5000000"),
    )
    act_b = Act.objects.create(
        deal=deal_b,
        contract=contract_b,
        invoice=invoice_b,
        number="ACT-TEST-B-001",
        status=issued_act_status,
        total_amount=Decimal("5000000"),
    )
    fulfillment_b = Fulfillment.objects.create(
        deal=deal_b,
        contract=contract_b,
        status=fulfillment_status,
    )

    return {
        "deal_a": deal_a,
        "quote_a": quote_a,
        "contract_a": contract_a,
        "invoice_a": invoice_a,
        "act_a": act_a,
        "fulfillment_a": fulfillment_a,
        "deal_b": deal_b,
        "quote_b": quote_b,
        "contract_b": contract_b,
        "invoice_b": invoice_b,
        "act_b": act_b,
        "fulfillment_b": fulfillment_b,
    }


@pytest.mark.django_db
class TestPortalIsolation:
    def test_cannot_access_other_company_request(self, portal_client, isolation_data):
        deal_b = isolation_data["deal_b"]
        response = portal_client.get(f"/api/portal/v1/requests/{deal_b.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data["detail"] == "NOT_FOUND"

    def test_cannot_access_other_company_quote(self, portal_client, isolation_data):
        quote_b = isolation_data["quote_b"]
        response = portal_client.get(f"/api/portal/v1/quotes/{quote_b.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data["detail"] == "NOT_FOUND"

    def test_cannot_mutate_other_company_quote(self, portal_client, isolation_data):
        quote_b = isolation_data["quote_b"]
        # Accept
        resp_acc = portal_client.post(f"/api/portal/v1/quotes/{quote_b.id}/accept", {"code": "2468"}, format="json")
        assert resp_acc.status_code == status.HTTP_404_NOT_FOUND
        assert resp_acc.data["detail"] == "NOT_FOUND"

        # Reject
        resp_rej = portal_client.post(
            f"/api/portal/v1/quotes/{quote_b.id}/reject", {"reason": "Test reason"}, format="json"
        )
        assert resp_rej.status_code == status.HTTP_404_NOT_FOUND
        assert resp_rej.data["detail"] == "NOT_FOUND"

    def test_cannot_sign_other_company_contract(self, portal_client, isolation_data):
        contract_b = isolation_data["contract_b"]
        response = portal_client.post(f"/api/portal/v1/contracts/{contract_b.id}/sign", format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data["detail"] == "NOT_FOUND"

    def test_cannot_act_on_other_company_act(self, portal_client, isolation_data):
        act_b = isolation_data["act_b"]
        # Accept
        resp_acc = portal_client.post(f"/api/portal/v1/acts/{act_b.id}/accept", format="json")
        assert resp_acc.status_code == status.HTTP_404_NOT_FOUND
        assert resp_acc.data["detail"] == "NOT_FOUND"

        # Return
        resp_ret = portal_client.post(
            f"/api/portal/v1/acts/{act_b.id}/return", {"reason": "Несоответствие объемов"}, format="json"
        )
        assert resp_ret.status_code == status.HTTP_404_NOT_FOUND
        assert resp_ret.data["detail"] == "NOT_FOUND"

    def test_lists_return_only_own_records(self, portal_client, isolation_data):
        # Requests
        r_resp = portal_client.get("/api/portal/v1/requests")
        assert r_resp.status_code == status.HTTP_200_OK
        ids = [x["id"] for x in r_resp.data]
        assert isolation_data["deal_a"].id in ids
        assert isolation_data["deal_b"].id not in ids

        # Quotes
        q_resp = portal_client.get("/api/portal/v1/quotes")
        assert q_resp.status_code == status.HTTP_200_OK
        q_ids = [x["id"] for x in q_resp.data]
        assert isolation_data["quote_a"].id in q_ids
        assert isolation_data["quote_b"].id not in q_ids

        # Contracts
        c_resp = portal_client.get("/api/portal/v1/contracts")
        assert c_resp.status_code == status.HTTP_200_OK
        c_ids = [x["id"] for x in c_resp.data]
        assert isolation_data["contract_a"].id in c_ids
        assert isolation_data["contract_b"].id not in c_ids

        # Invoices
        i_resp = portal_client.get("/api/portal/v1/invoices")
        assert i_resp.status_code == status.HTTP_200_OK
        i_ids = [x["id"] for x in i_resp.data]
        assert isolation_data["invoice_a"].id in i_ids
        assert isolation_data["invoice_b"].id not in i_ids

        # Acts
        a_resp = portal_client.get("/api/portal/v1/acts")
        assert a_resp.status_code == status.HTTP_200_OK
        a_ids = [x["id"] for x in a_resp.data]
        assert isolation_data["act_a"].id in a_ids
        assert isolation_data["act_b"].id not in a_ids

        # Deliveries
        d_resp = portal_client.get("/api/portal/v1/deliveries")
        assert d_resp.status_code == status.HTTP_200_OK
        d_ids = [x["id"] for x in d_resp.data]
        assert isolation_data["fulfillment_a"].id in d_ids
        assert isolation_data["fulfillment_b"].id not in d_ids
