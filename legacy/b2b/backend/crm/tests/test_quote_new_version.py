"""«Create new version» на сделке, где КП уже есть (v1 есть у любой сделки).

Прогон глазами 2026-08-17: продавец после отказа клиента жал «Create new version» →
POST /crm/quotes/ отвечал 400 (авто-UniqueTogetherValidator DRF по (deal, version)
с дефолтом version=1 срабатывал ДО perform_create, где сервер назначает max+1).
Тест закрепляет: второй и третий POST на ту же сделку → 201, версии растут,
а присланная клиентом version игнорируется (её назначает сервер).
"""

import pytest
from rest_framework.test import APIClient

from crm.tests.test_ms_routing import lookups, world  # noqa: F401 — фикстуры мира с роутингом


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_second_quote_on_same_deal_gets_next_version(world):  # noqa: F811
    from crm.models import Deal, DealSellerRouting, DealStage

    deal = Deal.objects.create(
        title="Re-quote after rejection", company=world["buyer_co"], stage=DealStage.objects.get(code="DRAFT")
    )
    DealSellerRouting.objects.create(deal=deal, seller_company=world["sa_co"])
    api = _api(world["sa_user"])

    first = api.post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json")
    assert first.status_code == 201, first.content
    second = api.post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json")
    assert second.status_code == 201, second.content
    third = api.post("/api/v1/crm/quotes/", {"deal": deal.id, "version": 1}, format="json")
    assert third.status_code == 201, third.content

    versions = [first.json()["version"], second.json()["version"], third.json()["version"]]
    assert versions == [1, 2, 3], versions
