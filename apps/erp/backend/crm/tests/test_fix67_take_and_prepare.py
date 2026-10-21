"""FIX-67: «Взять в работу и подготовить КП» — строки заявки клиента и атомарность.

Дефект прода: из заявки нельзя сделать КП. Две причины на стороне бэкенда:

* строки заявки из Cabinet и из передачи CRM лежат в `PortalRequestLine`, а сервис читал только позиции
  «КП заявки» (`prepared_by=None`), которого после M1-ERP-02 никто не создаёт, — на любой настоящей заявке
  `NO_REQUEST_LINES`;
* при этом отказе сделка уже была назначена и переведена в CALCULATING: `claim_deal` и `transition_deal_stage`
  фиксировались до проверки строк.

Тесты не ходят к ИИ (`settings.AI_IMPORT_ENABLED = False` из conftest).
"""

from decimal import Decimal

import pytest
from portal.models import PortalRequestLine, PortalRequestSummary
from rest_framework.test import APIClient

from crm.models import ActivityLog, Deal, DealStage, Quote
from crm.services.draft_quote import take_and_prepare_quote


def _snapshot(deal: Deal) -> dict:
    deal = Deal.objects.get(pk=deal.pk)
    return {
        "assigned_to": deal.assigned_to_id,
        "assigned_at": deal.assigned_at,
        "stage": deal.stage.code,
        "journal": ActivityLog.objects.filter(deal=deal).count(),
        "quotes": Quote.objects.filter(deal=deal).count(),
    }


@pytest.fixture
def portal_deal(scene):
    """Заявка, как её заводит Cabinet / передача CRM: строки в `PortalRequestLine`, КП заявки нет."""
    deal = Deal.objects.create(
        title="Запрос из Cabinet", company=scene["buyer"], stage=DealStage.objects.get(code="RFQ_OPEN")
    )
    PortalRequestLine.objects.create(deal=deal, text="Рельс Р65", quantity=Decimal("12.000"), unit="т", sort_order=1)
    PortalRequestLine.objects.create(deal=deal, text="Накладка 4-дырная", quantity=None, sort_order=2)
    return deal


@pytest.fixture
def words_deal(scene):
    """Заявка словами: передача CRM без перечня позиций — только текст `notes`."""
    return Deal.objects.create(
        title="Заявка: Buyer",
        company=scene["buyer"],
        stage=DealStage.objects.get(code="RFQ_OPEN"),
        notes="Нужны рельсы Р65, 500 тонн, и накладки к ним",
    )


@pytest.fixture
def seller_api(scene):
    client = APIClient()
    client.force_authenticate(scene["seller_user"])
    return client


@pytest.mark.django_db
def test_portal_request_lines_become_the_quote_lines(scene, portal_deal):
    """Строки заявки из Cabinet попадают в КП: имя, единица, количество (пусто → 1, дробное → вверх)."""
    result, err = take_and_prepare_quote(portal_deal.id, scene["seller_user"])

    assert err is None
    assert result["mode"] == "quote"
    items = list(result["quote"].items.order_by("position"))
    assert [item.imported_raw_name for item in items] == ["Рельс Р65", "Накладка 4-дырная"]
    assert [item.quantity for item in items] == [12, 1]
    assert items[0].unit == "т"
    portal_deal.refresh_from_db()
    assert portal_deal.assigned_to_id == scene["seller_user"].id
    assert portal_deal.stage.code == "CALCULATING"


@pytest.mark.django_db
def test_manual_quote_create_copies_portal_lines(scene, portal_deal, seller_api):
    """Ручное «Создать КП» тоже не пустое: строки заявки из Cabinet копируются (разрыв №4 W2)."""
    response = seller_api.post("/api/v1/crm/quotes/", {"deal": portal_deal.id}, format="json")

    assert response.status_code == 201, response.content
    quote = Quote.objects.get(pk=response.json()["id"])
    assert [item.imported_raw_name for item in quote.items.order_by("position")] == [
        "Рельс Р65",
        "Накладка 4-дырная",
    ]


@pytest.mark.django_db
def test_refusal_without_lines_changes_nothing(scene, words_deal):
    """Заявка словами: `NO_REQUEST_LINES`, а исполнитель, стадия, журнал и КП — прежние."""
    before = _snapshot(words_deal)

    result, err = take_and_prepare_quote(words_deal.id, scene["seller_user"])

    assert result is None
    assert err == "NO_REQUEST_LINES"
    assert before["assigned_to"] is None and before["stage"] == "RFQ_OPEN"
    assert _snapshot(words_deal) == before


@pytest.mark.django_db
def test_refusal_over_http_changes_nothing(scene, words_deal, seller_api):
    before = _snapshot(words_deal)

    response = seller_api.post(f"/api/v1/crm/deals/{words_deal.id}/take-and-prepare/", {}, format="json")

    assert response.status_code == 400
    assert response.json()["detail"] == "NO_REQUEST_LINES"
    assert _snapshot(words_deal) == before


@pytest.mark.django_db
def test_failed_stage_transition_rolls_back_the_claim(scene, portal_deal, monkeypatch):
    """Отказ на ЛЮБОМ шаге откатывает предыдущие: перевод стадии не удался — заявка не назначена."""
    import crm.services.deals as deals_service

    monkeypatch.setattr(deals_service, "transition_deal_stage", lambda deal, stage, actor: (None, "FSM_REFUSED"))
    before = _snapshot(portal_deal)

    result, err = take_and_prepare_quote(portal_deal.id, scene["seller_user"])

    assert (result, err) == (None, "FSM_REFUSED")
    assert before["assigned_to"] is None
    assert _snapshot(portal_deal) == before


@pytest.mark.django_db
def test_refusal_by_teammate_ownership_changes_nothing(scene, portal_deal):
    take_and_prepare_quote(portal_deal.id, scene["seller_user"])
    before = _snapshot(portal_deal)

    result, err = take_and_prepare_quote(portal_deal.id, scene["teammate"])

    assert (result, err) == (None, "DEAL_ALREADY_CLAIMED")
    assert _snapshot(portal_deal) == before


@pytest.mark.django_db
def test_deal_detail_tells_the_ui_about_lines_and_request_text(scene, portal_deal, words_deal, seller_api):
    """Фронтенд показывает «Взять в работу и подготовить» только при строках — число строк считает сервер."""
    PortalRequestSummary.objects.create(deal=portal_deal, text="Полный текст запроса клиента")

    with_lines = seller_api.get(f"/api/v1/crm/deals/{portal_deal.id}/").json()
    words = seller_api.get(f"/api/v1/crm/deals/{words_deal.id}/").json()
    legacy = seller_api.get(f"/api/v1/crm/deals/{scene['deal'].id}/").json()

    assert with_lines["request_lines_count"] == 2
    assert with_lines["request_text"] == "Полный текст запроса клиента"
    assert words["request_lines_count"] == 0
    assert words["request_text"] == "Нужны рельсы Р65, 500 тонн, и накладки к ним"  # нет сути — берём notes
    assert legacy["request_lines_count"] == 2  # прежние «позиции КП заявки» тоже строки заявки
