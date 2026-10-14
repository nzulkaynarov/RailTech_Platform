"""«Create new version» на сделке, где КП уже есть (v1 есть у любой сделки).

Прогон глазами 2026-08-17: продавец после отказа клиента жал «Create new version» →
POST /crm/quotes/ отвечал 400 (авто-UniqueTogetherValidator DRF по (deal, version)
с дефолтом version=1 срабатывал ДО perform_create, где сервер назначает max+1).
Тест закрепляет: второй и третий POST на ту же сделку → 201, версии растут,
а присланная клиентом version игнорируется (её назначает сервер).
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage, QuoteStatus


@pytest.fixture
def world(db, grant):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    own = Company.objects.create(name="Own Co", inn="A100")
    own.types.add(CompanyType.objects.get(code="SUPPLIER"))
    staff = CustomUser.objects.create_user(email="sa@t.test", username="sa@t.test", password="x")
    CompanyMember.objects.create(
        user=staff, company=own, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    grant(staff, "quote.build", "quote.edit_pricing")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    return {"staff": staff, "buyer_co": buyer_co}


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_second_quote_on_same_deal_gets_next_version(world):
    deal = Deal.objects.create(
        title="Re-quote after rejection", company=world["buyer_co"], stage=DealStage.objects.get(code="DRAFT")
    )
    api = _api(world["staff"])

    first = api.post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json")
    assert first.status_code == 201, first.content
    second = api.post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json")
    assert second.status_code == 201, second.content
    third = api.post("/api/v1/crm/quotes/", {"deal": deal.id, "version": 1}, format="json")
    assert third.status_code == 201, third.content

    versions = [first.json()["version"], second.json()["version"], third.json()["version"]]
    assert versions == [1, 2, 3], versions
