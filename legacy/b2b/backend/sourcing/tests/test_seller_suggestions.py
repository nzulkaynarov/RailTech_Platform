"""R1 (spec-freetext-rfq-routing, утв. 27-07): авто-подбор продавцов для free-text заявки.

Category-matched routing (Ariba Discovery / Alibaba RFQ): позиции заявки → каталожные товары
(trigram по free-text) → owner_company, со счётом совпавших позиций. Детерминированно, без AI.
Изолированная БД (только товары теста) — счёт совпадений точный.
"""

import pytest

from accounts.models import Company, CompanyType, VerificationStatus
from catalog.models import Product
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from sourcing.services import suggest_sellers_for_deal


@pytest.fixture
def world(db):
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    published = Product._meta.get_field("status").related_model.objects.get_or_create(
        code="PUBLISHED", defaults={"name": "Published", "sort_order": 1}
    )[0]
    draft_status = Product._meta.get_field("status").related_model.objects.get_or_create(
        code="DRAFT", defaults={"name": "Draft", "sort_order": 2}
    )[0]

    verified = VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})[
        0
    ]

    def _seller(name, inn, verification=verified):
        """A routable seller: SUPPLIER + KYC-verified. Unverified sellers are deliberately
        excluded from suggestions — the picker can't show them (see _owner_ids_for_products)."""
        company = Company.objects.create(name=name, inn=inn, verification_status=verification)
        company.types.add(CompanyType.objects.get(code="SUPPLIER"))
        return company

    rails = _seller("ООО Рельсы", "3400000001")
    fasteners = _seller("ООО Крепёж", "3400000002")
    # Рельсы продаёт рельс + накладку; Крепёж — скрепление.
    Product.objects.create(name="Рельс Р65 ГОСТ Р 51685", owner_company=rails, status=published)
    Product.objects.create(name="Накладка двухголовая Р65", owner_company=rails, status=published)
    Product.objects.create(name="Скрепление КБ-65 в сборе", owner_company=fasteners, status=published)
    # Товар в DRAFT-статусе НЕ должен подсказывать продавца.
    hidden = _seller("ООО Черновик", "3400000003")
    Product.objects.create(name="Подкладка КБ-65", owner_company=hidden, status=draft_status)

    buyer = Company.objects.create(name="ООО Покупатель", inn="7700000009")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    return locals()


def _freetext_deal(world, *names):
    deal = Deal.objects.create(title="RFQ", company=world["buyer"], stage=DealStage.objects.get(code="DRAFT"))
    rq = Quote.objects.create(deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"))
    for name in names:
        QuoteItem.objects.create(quote=rq, quantity=1, imported_raw_name=name)
    return deal


@pytest.mark.django_db
def test_freetext_request_suggests_the_right_sellers_with_counts(world):
    deal = _freetext_deal(world, "рельс р65", "накладка двухголовая р65", "скрепление кб-65")
    result = suggest_sellers_for_deal(deal)
    by_name = {row["name"]: row for row in result}
    assert "ООО Рельсы" in by_name and "ООО Крепёж" in by_name
    # Рельсы закрывает 2 позиции из 3, Крепёж — 1 (наш аналог confidence).
    assert by_name["ООО Рельсы"]["matched_lines"] == 2
    assert by_name["ООО Крепёж"]["matched_lines"] == 1
    assert all(row["total_lines"] == 3 for row in result)
    # Результат отсортирован по убыванию совпадений.
    assert result[0]["name"] == "ООО Рельсы"


@pytest.mark.django_db
def test_draft_status_product_never_suggests_its_seller(world):
    deal = _freetext_deal(world, "подкладка кб-65")  # совпадёт только с DRAFT-товаром
    result = suggest_sellers_for_deal(deal)
    assert all(row["name"] != "ООО Черновик" for row in result)


@pytest.mark.django_db
def test_catalog_picked_line_uses_its_own_owner(world):
    # Позиция взята из каталога (есть product_id) — продавец берётся из owner_company напрямую.
    deal = Deal.objects.create(title="RFQ", company=world["buyer"], stage=DealStage.objects.get(code="DRAFT"))
    rq = Quote.objects.create(deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"))
    rail = Product.objects.get(name="Рельс Р65 ГОСТ Р 51685")
    QuoteItem.objects.create(quote=rq, quantity=10, product=rail)
    result = suggest_sellers_for_deal(deal)
    assert result and result[0]["name"] == "ООО Рельсы" and result[0]["matched_lines"] == 1


@pytest.mark.django_db
def test_no_catalog_hit_returns_empty_not_error(world):
    deal = _freetext_deal(world, "нечто чего нет в каталоге zzzzz")
    assert suggest_sellers_for_deal(deal) == []  # UI оставит ручной выбор, без тупика
