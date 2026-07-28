"""R3 — AI-усиление подбора продавцов (надстройка над детерминированным R1).

Контракт, который здесь закрепляется (клиент Anthropic всегда застаблен — платных/
недетерминированных вызовов в тестах нет):
- ИИ спрашивают ТОЛЬКО про free-text позиции, которые триграм не закрыл (не жжём деньги
  на уже решённых строках);
- распознанная ИИ позиция добавляет продавца в тот же shape, что и R1;
- фильтр PUBLISHED действует и на AI-кандидатов — черновой товар не подсказывает продавца
  в обход модерации (ИИ не должен быть дырой в правиле видимости);
- при выключенном ИИ / пустом ответе результат ДЕГРАДИРУЕТ ровно к R1, а не падает;
- эндпоинт: 503 при выключенном ИИ, и подбирать может только покупатель-владелец заявки.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from sourcing.services import suggest_sellers_for_deal, suggest_sellers_for_deal_ai


@pytest.fixture
def world(db):
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    status_model = Product._meta.get_field("status").related_model
    published = status_model.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 1})[0]
    draft_status = status_model.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 2})[0]

    def _seller(name, inn):
        company = Company.objects.create(name=name, inn=inn)
        company.types.add(CompanyType.objects.get(code="SUPPLIER"))
        return company

    rails = _seller("ООО Рельсы", "3500000001")
    fasteners = _seller("ООО Крепёж", "3500000002")
    rail_product = Product.objects.create(name="Рельс Р65 ГОСТ Р 51685", owner_company=rails, status=published)
    fastener_product = Product.objects.create(
        name="Скрепление КБ-65 в сборе", owner_company=fasteners, status=published
    )
    # Черновой товар — его продавец не должен всплыть ни через триграм, ни через ИИ.
    hidden = _seller("ООО Черновик", "3500000003")
    hidden_product = Product.objects.create(name="Подкладка КБ-65", owner_company=hidden, status=draft_status)

    buyer_company = Company.objects.create(name="ООО Покупатель", inn="7700000019")
    buyer_company.types.add(CompanyType.objects.get(code="CLIENT"))
    buyer_user = CustomUser.objects.create_user(
        email="r3-buyer@x.test", username="r3-buyer@x.test", password="pw", is_active=True
    )
    CompanyMember.objects.create(
        user=buyer_user,
        company=buyer_company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        can_buy=True,
    )
    return locals()


def _freetext_deal(world, *names):
    deal = Deal.objects.create(title="RFQ", company=world["buyer_company"], stage=DealStage.objects.get(code="DRAFT"))
    request_quote = Quote.objects.create(deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"))
    for name in names:
        QuoteItem.objects.create(quote=request_quote, quantity=1, imported_raw_name=name)
    return deal


def _stub_ai(monkeypatch, *, product_ids, spy=None):
    """Подменяем один платный вызов: возвращаем по одному матчу на каждую переданную строку."""

    def _fake(lines, domain_code=None, top_k=3):
        if spy is not None:
            spy.extend(lines)
        return [
            {"line_index": index, "candidates": [{"product_id": pid, "confidence": 0.8} for pid in product_ids]}
            for index, _line in enumerate(lines)
        ]

    monkeypatch.setattr("sourcing.services_ai.match_lines_to_catalog", _fake)


# ── ИИ добирает то, что триграм не нашёл ──────────────────────────────────────


@pytest.mark.django_db
def test_ai_adds_seller_the_trigram_missed(world, monkeypatch):
    """Латиница/опечатка: триграм молчит, ИИ узнаёт товар — продавец появляется."""
    deal = _freetext_deal(world, "relsy R65 zzz")
    assert suggest_sellers_for_deal(deal) == []  # детерминированный проход пуст — есть что добирать

    _stub_ai(monkeypatch, product_ids=[world["rail_product"].id])
    result = suggest_sellers_for_deal_ai(deal)

    assert [row["name"] for row in result] == ["ООО Рельсы"]
    assert result[0]["matched_lines"] == 1 and result[0]["total_lines"] == 1


@pytest.mark.django_db
def test_ai_is_asked_only_about_trigram_misses(world, monkeypatch):
    """Деньги не жжём: строка, которую триграм уже закрыл, в модель не уходит."""
    deal = _freetext_deal(world, "рельс р65", "relsy R65 zzz")
    sent_to_ai = []
    _stub_ai(monkeypatch, product_ids=[world["fastener_product"].id], spy=sent_to_ai)

    result = suggest_sellers_for_deal_ai(deal)

    assert [line["name"] for line in sent_to_ai] == ["relsy R65 zzz"]  # только промах
    by_name = {row["name"]: row for row in result}
    assert by_name["ООО Рельсы"]["matched_lines"] == 1  # найден триграмом
    assert by_name["ООО Крепёж"]["matched_lines"] == 1  # добавлен ИИ
    assert all(row["total_lines"] == 2 for row in result)


# ── ИИ не обходит правила видимости ───────────────────────────────────────────


@pytest.mark.django_db
def test_ai_candidate_on_draft_product_never_suggests_its_seller(world, monkeypatch):
    """AI-кандидат на черновой товар не должен протаскивать продавца мимо модерации."""
    deal = _freetext_deal(world, "podkladka kb65 zzz")
    _stub_ai(monkeypatch, product_ids=[world["hidden_product"].id])

    assert suggest_sellers_for_deal_ai(deal) == []


# ── деградация: без ИИ результат равен R1 ─────────────────────────────────────


@pytest.mark.django_db
def test_empty_ai_result_degrades_to_deterministic(world, monkeypatch):
    """Модель ничего не дала — отдаём ровно детерминированный результат, без ошибок."""
    deal = _freetext_deal(world, "рельс р65", "нечто чего нет в каталоге zzzzz")
    monkeypatch.setattr("sourcing.services_ai.match_lines_to_catalog", lambda lines, domain_code=None, top_k=3: [])

    assert suggest_sellers_for_deal_ai(deal) == suggest_sellers_for_deal(deal)


@pytest.mark.django_db
def test_ai_off_degrades_to_deterministic(world, settings):
    """AI_IMPORT_ENABLED=false: реальный match_lines_to_catalog сам вернёт [] — не падаем.

    Во второй позиции намеренно промах триграма, иначе до AI-ветки дело бы не дошло
    и тест ничего бы не проверял."""
    settings.AI_IMPORT_ENABLED = False
    deal = _freetext_deal(world, "рельс р65", "relsy R65 zzz")

    assert suggest_sellers_for_deal_ai(deal) == suggest_sellers_for_deal(deal)


# ── эндпоинт: гейты ───────────────────────────────────────────────────────────


def _client(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.mark.django_db
def test_endpoint_returns_503_when_ai_disabled(world, settings):
    settings.AI_IMPORT_ENABLED = False
    deal = _freetext_deal(world, "рельс р65")

    response = _client(world["buyer_user"]).post(f"/api/v1/crm/deals/{deal.id}/suggest-sellers-ai/")

    assert response.status_code == 503
    assert response.data == {"detail": "AI_DISABLED"}


def _seller_user(world, email, company):
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        can_sell=True,
    )
    return user


@pytest.mark.django_db
def test_endpoint_rejects_a_seller_who_can_see_the_deal(world, settings):
    """Ключевой гейт: маршрутизированный продавец сделку ВИДИТ, но подбирать получателей
    (и жечь ИИ на чужой заявке) не вправе — это решение покупателя."""
    from crm.models import DealSellerRouting

    settings.AI_IMPORT_ENABLED = True
    deal = _freetext_deal(world, "рельс р65")
    seller = _seller_user(world, "r3-routed-seller@x.test", world["rails"])
    DealSellerRouting.objects.create(deal=deal, seller_company=world["rails"])

    response = _client(seller).post(f"/api/v1/crm/deals/{deal.id}/suggest-sellers-ai/")

    assert response.status_code == 403
    assert response.data == {"detail": "ONLY_BUYER_CAN_ROUTE"}


@pytest.mark.django_db
def test_endpoint_hides_a_foreign_deal(world, settings):
    """Посторонний продавец без маршрутизации не должен даже узнать о существовании заявки."""
    settings.AI_IMPORT_ENABLED = True
    deal = _freetext_deal(world, "рельс р65")
    stranger = _seller_user(world, "r3-stranger@x.test", world["fasteners"])

    response = _client(stranger).post(f"/api/v1/crm/deals/{deal.id}/suggest-sellers-ai/")

    assert response.status_code == 404  # скоуп queryset, а не гейт — утечки факта заявки нет
