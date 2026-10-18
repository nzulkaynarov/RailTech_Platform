"""Tests for Portal Permissions (can_act guard and unauthenticated 401)."""

from decimal import Decimal

import pytest
from rest_framework import status

from crm.constants import ActStatusCode, ContractStatusCode, DealStageCode, QuoteStatusCode
from crm.models import Act, ActStatus, Contract, ContractStatus, Deal, DealStage, Quote, QuoteStatus


@pytest.fixture
def client_resources(db, client_company, client_contact):
    draft_stage, _ = DealStage.objects.get_or_create(code=DealStageCode.DRAFT, defaults={"name": "Черновик"})
    sent_quote_status, _ = QuoteStatus.objects.get_or_create(code=QuoteStatusCode.SENT, defaults={"name": "Отправлено"})
    sent_contract_status, _ = ContractStatus.objects.get_or_create(
        code=ContractStatusCode.PENDING_CLIENT, defaults={"name": "На подписи"}
    )
    issued_act_status, _ = ActStatus.objects.get_or_create(code=ActStatusCode.ISSUED, defaults={"name": "Выставлен"})

    deal = Deal.objects.create(
        company=client_company,
        contact=client_contact,
        title="Сделка для проверки прав",
        stage=draft_stage,
    )
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=sent_quote_status,
        total_incl_vat=Decimal("1000000"),
    )
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-PERM-001",
        status=sent_contract_status,
        total_amount=Decimal("1000000"),
    )
    act = Act.objects.create(
        deal=deal,
        contract=contract,
        number="ACT-PERM-001",
        status=issued_act_status,
        total_amount=Decimal("1000000"),
    )
    return {"deal": deal, "quote": quote, "contract": contract, "act": act}


@pytest.mark.django_db
class TestCanActPermission:
    def test_readonly_user_can_read_all_surfaces(self, readonly_portal_client, client_resources):
        deal = client_resources["deal"]
        quote = client_resources["quote"]

        read_endpoints = [
            "/api/portal/v1/me",
            "/api/portal/v1/requests",
            f"/api/portal/v1/requests/{deal.id}",
            "/api/portal/v1/quotes",
            f"/api/portal/v1/quotes/{quote.id}",
            "/api/portal/v1/contracts",
            "/api/portal/v1/invoices",
            "/api/portal/v1/acts",
            "/api/portal/v1/deliveries",
            "/api/portal/v1/documents",
            "/api/portal/v1/catalog",
            "/api/portal/v1/catalog/categories",
            "/api/portal/v1/company",
            "/api/portal/v1/team",
        ]
        for url in read_endpoints:
            res = readonly_portal_client.get(url)
            assert res.status_code == status.HTTP_200_OK, f"Failed on {url}: {res.status_code}"

    def test_readonly_user_denied_mutations(self, readonly_portal_client, client_resources):
        quote = client_resources["quote"]
        contract = client_resources["contract"]
        act = client_resources["act"]

        mutations = [
            ("POST", "/api/portal/v1/requests", {"summary": "Запрос", "lines": []}),
            ("POST", f"/api/portal/v1/quotes/{quote.id}/accept", {"code": "4821"}),
            ("POST", f"/api/portal/v1/quotes/{quote.id}/reject", {"reason": "Дорого"}),
            ("POST", f"/api/portal/v1/contracts/{contract.id}/sign", {}),
            ("POST", f"/api/portal/v1/acts/{act.id}/accept", {}),
            ("POST", f"/api/portal/v1/acts/{act.id}/return", {"reason": "Брак"}),
            ("PUT", "/api/portal/v1/company", {"bank_details": "новые реквизиты"}),
            ("POST", "/api/portal/v1/team/invite", {"name": "Новый", "email": "new@ex.uz", "can_act": True}),
        ]

        for method, url, body in mutations:
            func = getattr(readonly_portal_client, method.lower())
            res = func(url, body, format="json")
            assert (
                res.status_code == status.HTTP_403_FORBIDDEN
            ), f"Expected 403 on {method} {url}, got {res.status_code}"
            assert res.data["detail"] == "FORBIDDEN"


@pytest.mark.django_db
class TestUnauthenticatedAccess:
    def test_anonymous_gets_401_on_protected_endpoints(self, anon_portal_client):
        protected = [
            ("GET", "/api/portal/v1/me"),
            ("GET", "/api/portal/v1/requests"),
            ("POST", "/api/portal/v1/requests"),
            ("GET", "/api/portal/v1/quotes"),
            ("GET", "/api/portal/v1/contracts"),
            ("GET", "/api/portal/v1/invoices"),
            ("GET", "/api/portal/v1/acts"),
            ("GET", "/api/portal/v1/deliveries"),
            ("GET", "/api/portal/v1/documents"),
            ("GET", "/api/portal/v1/catalog"),
            ("GET", "/api/portal/v1/company"),
            ("PUT", "/api/portal/v1/company"),
            ("GET", "/api/portal/v1/team"),
            ("POST", "/api/portal/v1/team/invite"),
        ]

        for method, url in protected:
            func = getattr(anon_portal_client, method.lower())
            res = func(url)
            assert (
                res.status_code == status.HTTP_401_UNAUTHORIZED
            ), f"Expected 401 on {method} {url}, got {res.status_code}"
            assert res.data["detail"] == "UNAUTHORIZED"
