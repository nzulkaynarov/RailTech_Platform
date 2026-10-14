"""Сторону зрителя считает СЕРВЕР и отдаёт на каждой сделке.

Фронт выводил сторону из `activeStatus` (= ПЕРВЫЙ тип компании), и у компании с типами
CLIENT+SUPPLIER продавец открывал заявку и видел покупательский экран: ни «Взять в работу и
подготовить КП», ни «Сформировать КП» (проход глазами 03-08).

С M1-ERP-02 волна 3 продавец любой сделки — своя компания (BUSINESS §3.3): сотрудник своей
компании — сторона продавца на КАЖДОЙ сделке, участник компании-клиента — сторона покупателя на
сделках своей компании (покупательские аккаунты — до M2-ERP-01), посторонний — ни одна.

Бенчмарк: GitHub отдаёт `viewerCanUpdate`/`viewerDidAuthor` на каждом объекте, Salesforce —
`UserRecordAccess`, Odoo Portal сверяет партнёра на сервере. Клиент роль ЧИТАЕТ.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import Deal, DealStage

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


def _client_for(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def world(lookups):
    """Своя компания (с типами CLIENT+SUPPLIER — именно на таком порядке типов ломался вывод
    стороны), два клиента и их заявки."""
    own = Company.objects.create(name="ООО Своя", inn="8000000001")
    # Порядок типов важен: CLIENT первым — из него фронт и делал `activeStatus = BUYER`.
    own.types.add(CompanyType.objects.get(code="CLIENT"))
    own.types.add(CompanyType.objects.get(code="SUPPLIER"))
    buyer_co = Company.objects.create(name="ООО Покупатель", inn="8000000002")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    other_co = Company.objects.create(name="ООО Другой клиент", inn="8000000003")
    other_co.types.add(CompanyType.objects.get(code="CLIENT"))

    staff = CustomUser.objects.create_user(email="staff@side.test", username="staff@side.test", password="pw")
    _member(staff, own)
    buyer = CustomUser.objects.create_user(email="buyer@side.test", username="buyer@side.test", password="pw")
    _member(buyer, buyer_co)

    stage = DealStage.objects.get(code="RFQ_OPEN")
    return {
        "staff": _client_for(staff),
        "buyer": _client_for(buyer),
        "buyer_deal": Deal.objects.create(title="Заявка покупателя", company=buyer_co, stage=stage),
        "other_deal": Deal.objects.create(title="Заявка другого клиента", company=other_co, stage=stage),
    }


def _detail(client, deal_id):
    response = client.get(f"/api/v1/crm/deals/{deal_id}/")
    assert response.status_code == 200, response.content
    return response.json()


def test_staff_is_seller_side_on_every_deal(world):
    """Сотрудник своей компании — продавец любой сделки, даже если типы компании начинаются с CLIENT."""
    for key in ("buyer_deal", "other_deal"):
        body = _detail(world["staff"], world[key].pk)
        assert body["viewer_is_seller"] is True
        assert body["viewer_is_buyer"] is False


def test_buyer_is_buyer_side_on_own_deal(world):
    body = _detail(world["buyer"], world["buyer_deal"].pk)
    assert body["viewer_is_buyer"] is True
    assert body["viewer_is_seller"] is False


def test_stranger_is_neither_side(lookups, world):
    """Посторонний не получает ни одной стороны — поле не заменяет проверку доступа."""
    stranger = CustomUser.objects.create_user(email="x@side.test", username="x@side.test", password="pw")
    other = Company.objects.create(name="ООО Посторонняя", inn="8000000004")
    other.types.add(CompanyType.objects.get(code="CLIENT"))
    _member(stranger, other)

    response = _client_for(stranger).get(f'/api/v1/crm/deals/{world["buyer_deal"].pk}/')

    # Либо не отдаём сделку вовсе, либо отдаём — но без обеих сторон.
    if response.status_code == 200:
        body = response.json()
        assert body["viewer_is_seller"] is False
        assert body["viewer_is_buyer"] is False
    else:
        assert response.status_code in (403, 404)


def _sides_in_list(client):
    response = client.get("/api/v1/crm/deals/")
    assert response.status_code == 200, response.content
    rows = response.json().get("results", response.json())
    return {row["id"]: (row["viewer_is_seller"], row["viewer_is_buyer"]) for row in rows}


def test_list_carries_the_side_too(world):
    """Список тоже несёт сторону: канбан и реестр рисуют действия по ней, каждая строка — своя."""
    staff_rows = _sides_in_list(world["staff"])
    assert staff_rows[world["buyer_deal"].pk] == (True, False)
    assert staff_rows[world["other_deal"].pk] == (True, False)

    buyer_rows = _sides_in_list(world["buyer"])
    assert buyer_rows == {world["buyer_deal"].pk: (False, True)}
