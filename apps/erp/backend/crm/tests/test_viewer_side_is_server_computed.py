"""Сторону зрителя считает СЕРВЕР и отдаёт на каждой сделке.

Одна и та же компания в одной сделке продавец, в другой покупатель — сторона есть свойство
ЗАПИСИ, а не сессии. Фронт выводил её из `activeStatus` (= ПЕРВЫЙ тип компании), и у компании
с типами CLIENT+SUPPLIER продавец открывал СВОЮ ЖЕ заявку и видел покупательский экран: ни
«Взять в работу и подготовить КП», ни «Сформировать КП». Единственной работающей кнопкой была
та, право на которую и так считал сервер (`viewer_can_release`) — проход глазами 03-08.

Бенчмарк: GitHub отдаёт `viewerCanUpdate`/`viewerDidAuthor` на каждом объекте, Salesforce —
`UserRecordAccess`, Odoo Portal сверяет партнёра на сервере. Клиент роль ЧИТАЕТ.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import Deal, DealSellerRouting, DealStage

pytestmark = pytest.mark.django_db


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    for code, name in (("CLIENT", "Клиент"), ("SUPPLIER", "Поставщик")):
        CompanyType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "Открытый RFQ", "sort_order": 25})


def _member(user, company):
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_buy=True,
        can_sell=True,
    )


@pytest.fixture
def dual_world(lookups):
    """Компания, которая И ПОКУПАЕТ, И ПРОДАЁТ — именно на ней ломался вывод стороны."""
    dual = Company.objects.create(name="ООО Двусторонняя", inn="8000000001")
    # Порядок типов важен: CLIENT первым — из него фронт и делал `activeStatus = BUYER`.
    dual.types.add(CompanyType.objects.get(code="CLIENT"))
    dual.types.add(CompanyType.objects.get(code="SUPPLIER"))
    buyer_co = Company.objects.create(name="ООО Покупатель", inn="8000000002")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))

    user = CustomUser.objects.create_user(email="dual@side.test", username="dual@side.test", password="pw")
    _member(user, dual)

    stage = DealStage.objects.get(code="RFQ_OPEN")
    # Сделка, где наша компания — ПРОДАВЕЦ (заявка чужого покупателя отроутена ей).
    as_seller = Deal.objects.create(title="Чужая заявка", company=buyer_co, stage=stage)
    DealSellerRouting.objects.create(deal=as_seller, seller_company=dual)
    # Сделка, где та же компания — ПОКУПАТЕЛЬ.
    as_buyer = Deal.objects.create(title="Своя закупка", company=dual, stage=stage)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return {"client": client, "as_seller": as_seller, "as_buyer": as_buyer}


def _detail(client, deal_id):
    response = client.get(f"/api/v1/crm/deals/{deal_id}/")
    assert response.status_code == 200, response.content
    return response.json()


def test_same_user_is_seller_on_one_deal_and_buyer_on_another(dual_world):
    """Ровно то, что не мог выразить один глобальный `activeStatus`."""
    seller_side = _detail(dual_world["client"], dual_world["as_seller"].pk)
    buyer_side = _detail(dual_world["client"], dual_world["as_buyer"].pk)

    assert seller_side["viewer_is_seller"] is True
    assert seller_side["viewer_is_buyer"] is False

    assert buyer_side["viewer_is_buyer"] is True
    assert buyer_side["viewer_is_seller"] is False


def test_stranger_is_neither_side(lookups, dual_world):
    """Посторонний не получает ни одной стороны — поле не заменяет проверку доступа."""
    stranger = CustomUser.objects.create_user(email="x@side.test", username="x@side.test", password="pw")
    other = Company.objects.create(name="ООО Посторонняя", inn="8000000003")
    other.types.add(CompanyType.objects.get(code="CLIENT"))
    _member(stranger, other)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(stranger).access_token}")

    response = client.get(f'/api/v1/crm/deals/{dual_world["as_seller"].pk}/')

    # Либо не отдаём сделку вовсе, либо отдаём — но без обеих сторон.
    if response.status_code == 200:
        body = response.json()
        assert body["viewer_is_seller"] is False
        assert body["viewer_is_buyer"] is False
    else:
        assert response.status_code in (403, 404)


def _sides_in_list(client, context):
    response = client.get("/api/v1/crm/deals/", HTTP_X_ACTIVE_CONTEXT=context)
    assert response.status_code == 200, response.content
    rows = response.json().get("results", response.json())
    return {row["id"]: (row["viewer_is_seller"], row["viewer_is_buyer"]) for row in rows}


def test_list_carries_the_side_too(dual_world):
    """Список тоже несёт сторону: канбан и реестр рисуют действия по ней.

    Заголовок `X-Active-Context` СУЖАЕТ выборку (ADR-0005 Phase C) — это по-прежнему его роль.
    Но у каждой попавшей в ответ строки сторона своя и посчитана сервером, а не выведена из
    того же заголовка: именно поэтому в одном ответе могут ужиться обе роли одной компании.
    """
    as_seller = dual_world["as_seller"].pk
    as_buyer = dual_world["as_buyer"].pk

    seller_scope = _sides_in_list(dual_world["client"], "SELLER")
    buyer_scope = _sides_in_list(dual_world["client"], "BUYER")

    assert seller_scope[as_seller] == (True, False)
    assert buyer_scope[as_buyer] == (False, True)


def test_side_does_not_follow_the_context_header(dual_world):
    """Сторона — свойство ЗАПИСИ: она не меняется от того, каким контекстом спросили.

    Это и есть суть дефекта: `activeStatus` был один на всё приложение, и «сторона» ездила
    вместе с ним.
    """
    deal_id = dual_world["as_seller"].pk

    with_seller = dual_world["client"].get(f"/api/v1/crm/deals/{deal_id}/", HTTP_X_ACTIVE_CONTEXT="SELLER").json()
    with_buyer = dual_world["client"].get(f"/api/v1/crm/deals/{deal_id}/", HTTP_X_ACTIVE_CONTEXT="BUYER")

    assert with_seller["viewer_is_seller"] is True
    # В покупательском контексте сделка может быть не видна вовсе — но если видна, сторона та же.
    if with_buyer.status_code == 200:
        assert with_buyer.json()["viewer_is_seller"] is True
