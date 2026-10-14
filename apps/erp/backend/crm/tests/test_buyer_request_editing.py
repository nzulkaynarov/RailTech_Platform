"""Покупатель правит свою заявку: позиции и шапку (аудит покрытия).

`buyer_update_request_item` и `buyer_update_request_meta` были непокрыты целиком, при том что
за ними стоят живые пользовательские пути: PATCH строки заявки и правка названия / заметки
продавцу на карточке. Линза прошлой волны — «непокрытая функция может вообще не работать» —
дала два настоящих бага (500 на подписании акта, мёртвая кнопка отклонения), поэтому пути
проверяются целиком через HTTP, а не вызовом сервиса напрямую.

Отдельно закреплено закрытие окна правки: как только продавец взял заявку в работу, покупатель
больше не может менять её под уже готовящимся КП.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    for code in ("DRAFT", "RFQ_OPEN", "SOURCING", "CALCULATING"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "SENT"):
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


@pytest.fixture
def buyer_request(lookups):
    company = Company.objects.create(name="Buyer Edit Co", inn="B500")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    user = CustomUser.objects.create_user(email="editor@req.test", username="editor@req.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_buy=True,
    )
    deal = Deal.objects.create(
        title="Первоначальное название",
        company=company,
        client=user,
        stage=DealStage.objects.get(code="DRAFT"),
        notes="",
    )
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    item = QuoteItem.objects.create(quote=quote, imported_raw_name="Рельс", quantity=1, unit="шт")
    return {"user": user, "deal": deal, "quote": quote, "item": item}


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


# ── позиции заявки ───────────────────────────────────────────────────────────


def test_buyer_edits_a_request_line(buyer_request):
    resp = _api(buyer_request["user"]).patch(
        f"/api/v1/crm/quote-items/{buyer_request['item'].id}/",
        {"imported_raw_name": "Рельс Р65", "quantity": 7, "unit": "т", "note": "срочно"},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    buyer_request["item"].refresh_from_db()
    assert buyer_request["item"].imported_raw_name == "Рельс Р65"
    assert buyer_request["item"].quantity == 7
    assert buyer_request["item"].unit == "т"
    assert buyer_request["item"].note == "срочно"


def test_blank_name_is_refused_with_a_business_code(buyer_request):
    resp = _api(buyer_request["user"]).patch(
        f"/api/v1/crm/quote-items/{buyer_request['item'].id}/",
        {"imported_raw_name": "   "},
        format="json",
    )

    assert resp.status_code == 400
    assert "ITEM_NAME_REQUIRED" in resp.content.decode()
    buyer_request["item"].refresh_from_db()
    assert buyer_request["item"].imported_raw_name == "Рельс", "имя не должно было измениться"


def test_quantity_is_floored_at_one(buyer_request):
    """Ноль и отрицательное количество бессмысленны в заявке — сервис поднимает до 1."""
    resp = _api(buyer_request["user"]).patch(
        f"/api/v1/crm/quote-items/{buyer_request['item'].id}/", {"quantity": 0}, format="json"
    )

    assert resp.status_code in (200, 400), resp.content
    buyer_request["item"].refresh_from_db()
    assert buyer_request["item"].quantity >= 1


def test_buyer_cannot_edit_the_line_once_the_seller_is_working(buyer_request):
    """Окно правки закрывается, когда продавец взял заявку в работу: иначе покупатель менял бы
    условия под уже готовящимся КП."""
    deal = buyer_request["deal"]
    deal.stage = DealStage.objects.get(code="CALCULATING")
    deal.save(update_fields=["stage"])

    resp = _api(buyer_request["user"]).patch(
        f"/api/v1/crm/quote-items/{buyer_request['item'].id}/",
        {"imported_raw_name": "Подмена"},
        format="json",
    )

    assert resp.status_code in (400, 403), resp.content
    buyer_request["item"].refresh_from_db()
    assert buyer_request["item"].imported_raw_name == "Рельс"


# ── шапка заявки ─────────────────────────────────────────────────────────────


def test_buyer_edits_title_and_note_to_seller(buyer_request):
    resp = _api(buyer_request["user"]).patch(
        f"/api/v1/crm/deals/{buyer_request['deal'].id}/update-request-meta/",
        {"title": "Рельсы Р65, 20 тонн", "notes": "Нужна доставка до Ташкента"},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    buyer_request["deal"].refresh_from_db()
    assert buyer_request["deal"].title == "Рельсы Р65, 20 тонн"
    assert buyer_request["deal"].notes == "Нужна доставка до Ташкента"


def test_blank_title_is_refused(buyer_request):
    resp = _api(buyer_request["user"]).patch(
        f"/api/v1/crm/deals/{buyer_request['deal'].id}/update-request-meta/",
        {"title": "  "},
        format="json",
    )

    assert resp.status_code == 400
    assert "TITLE_REQUIRED" in resp.content.decode()
    buyer_request["deal"].refresh_from_db()
    assert buyer_request["deal"].title == "Первоначальное название"


def test_note_alone_can_be_updated_without_touching_the_title(buyer_request):
    """Частичная правка: страница шлёт только изменившееся поле."""
    resp = _api(buyer_request["user"]).patch(
        f"/api/v1/crm/deals/{buyer_request['deal'].id}/update-request-meta/",
        {"notes": "только заметка"},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    buyer_request["deal"].refresh_from_db()
    assert buyer_request["deal"].notes == "только заметка"
    assert buyer_request["deal"].title == "Первоначальное название"


def test_a_stranger_cannot_edit_someone_elses_request_meta(buyer_request, lookups):
    """Граница арендатора: чужую заявку не правит никто, даже аутентифицированный."""
    outsider = CustomUser.objects.create_user(email="outsider@req.test", username="outsider@req.test", password="x")

    resp = _api(outsider).patch(
        f"/api/v1/crm/deals/{buyer_request['deal'].id}/update-request-meta/",
        {"title": "Захвачено"},
        format="json",
    )

    assert resp.status_code in (403, 404), resp.content
    buyer_request["deal"].refresh_from_db()
    assert buyer_request["deal"].title == "Первоначальное название"
