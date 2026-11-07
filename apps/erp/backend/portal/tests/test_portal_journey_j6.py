"""Тесты для Wave J6 (Поиск и повтор заказа) и B-CABFIX-2 (Исход закрытого запроса)."""

from __future__ import annotations

import pytest
from parties.models import Company, CompanyType, Contact
from portal.services.requests import create_client_request
from portal.tests.conftest import PortalAPIClient, make_portal_session

from crm.constants import DealStageCode
from crm.models import DealStage

pytestmark = pytest.mark.django_db

PREFIX = "/api/portal/v1"


@pytest.fixture
def j6_setup():
    client_type, _ = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})
    company = Company.objects.create(name="J6 Logistics LLC", inn="770011223")
    company.types.add(client_type)
    contact = Contact.objects.create(company=company, name="J6 Contact", email="contact@j6.test", can_act=True)
    session = make_portal_session(contact, company, "magic_link")

    client = PortalAPIClient()
    client.cookies["portal_session"] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)

    return {"company": company, "contact": contact, "client": client}


def test_requests_filter_by_status_and_search(j6_setup):
    client = j6_setup["client"]
    company = j6_setup["company"]
    contact = j6_setup["contact"]

    # 1. Создаем первый запрос (новинка)
    deal1 = create_client_request(
        company,
        contact,
        summary="Рельсы Р65 новые с завода",
        lines=[{"text": "Рельс Р65 ГОСТ Р 51685", "quantity": "100", "unit": "т"}],
        attachments=[],
    )

    # 2. Создаем второй запрос (будет закрыт won)
    deal2 = create_client_request(
        company,
        contact,
        summary="Накладки 1Р-65",
        lines=[{"text": "Накладка стыковая 1Р-65", "quantity": "200", "unit": "шт"}],
        attachments=[],
    )
    stage_won, _ = DealStage.objects.get_or_create(code=DealStageCode.CLOSED_WON, defaults={"name": "Выиграна"})
    deal2.stage = stage_won
    deal2.save()

    # 3. Создаем третий запрос (будет закрыт lost)
    deal3 = create_client_request(
        company,
        contact,
        summary="Стрелочный перевод",
        lines=[{"text": "Перевод стрелочный типа Р65", "quantity": "2", "unit": "компл"}],
        attachments=[],
    )
    stage_lost, _ = DealStage.objects.get_or_create(code=DealStageCode.CLOSED_LOST, defaults={"name": "Проиграна"})
    deal3.stage = stage_lost
    deal3.save()

    # Проверка получения всех запросов
    res = client.get(f"{PREFIX}/requests")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 3

    # Проверка исходов (B-CABFIX-2)
    items_by_id = {item["id"]: item for item in data}
    assert items_by_id[deal1.pk]["status"] == "new"
    assert items_by_id[deal1.pk]["outcome"] is None
    assert items_by_id[deal2.pk]["status"] == "closed"
    assert items_by_id[deal2.pk]["outcome"] == "won"
    assert items_by_id[deal3.pk]["status"] == "closed"
    assert items_by_id[deal3.pk]["outcome"] == "cancelled"

    # Фильтрация по статусу status=closed
    res_closed = client.get(f"{PREFIX}/requests?status=closed")
    assert res_closed.status_code == 200
    assert len(res_closed.json()) == 2

    # Фильтрация по статусу status=new
    res_new = client.get(f"{PREFIX}/requests?status=new")
    assert res_new.status_code == 200
    assert len(res_new.json()) == 1
    assert res_new.json()[0]["id"] == deal1.pk

    # Невалидный статус -> 422
    res_bad = client.get(f"{PREFIX}/requests?status=invalid_status")
    assert res_bad.status_code == 422

    # Поиск по q
    res_q1 = client.get(f"{PREFIX}/requests?q=Рельсы")
    assert res_q1.status_code == 200
    assert len(res_q1.json()) == 1
    assert res_q1.json()[0]["id"] == deal1.pk

    # Поиск по тексту строки позиции
    res_q_line = client.get(f"{PREFIX}/requests?q=стрелочный")
    assert res_q_line.status_code == 200
    assert len(res_q_line.json()) == 1
    assert res_q_line.json()[0]["id"] == deal3.pk

    # Поиск с 0 совпадений
    res_q_empty = client.get(f"{PREFIX}/requests?q=несуществующий_товар")
    assert res_q_empty.status_code == 200
    assert len(res_q_empty.json()) == 0


def test_request_reorder(j6_setup):
    client = j6_setup["client"]
    company = j6_setup["company"]
    contact = j6_setup["contact"]

    original_deal = create_client_request(
        company,
        contact,
        summary="Заказ крепежа ЖД",
        lines=[
            {"text": "Болт стыковой М27х160", "quantity": "500", "unit": "шт"},
            {"text": "Гайка М27", "quantity": "500", "unit": "шт"},
        ],
        attachments=[],
    )

    # Выполняем повтор запроса POST /requests/{id}/reorder
    res = client.post(f"{PREFIX}/requests/{original_deal.pk}/reorder")
    assert res.status_code == 201
    new_request_data = res.json()
    assert new_request_data["id"] != original_deal.pk
    assert "Повтор запроса" in new_request_data["summary"]
    assert len(new_request_data["lines"]) == 2
    assert new_request_data["lines"][0]["text"] == "Болт стыковой М27х160"
    assert new_request_data["lines"][0]["quantity"] == "500"

    # Повтор чужого или несуществующего запроса -> 404
    res_404 = client.post(f"{PREFIX}/requests/999999/reorder")
    assert res_404.status_code == 404


def test_documents_search_and_date_filter(j6_setup):
    client = j6_setup["client"]

    # Проверяем фильтрацию дат и поиска на /documents
    res = client.get(f"{PREFIX}/documents?q=КП&date_from=2026-01-01&date_to=2026-12-31")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # Невалидная дата -> 422
    res_bad_date = client.get(f"{PREFIX}/documents?date_from=bad-date")
    assert res_bad_date.status_code == 422
