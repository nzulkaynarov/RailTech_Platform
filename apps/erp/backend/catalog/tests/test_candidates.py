"""Строка КП без товара рождает кандидата в номенклатуру и отдаёт ему своё знание.

Наблюдение владельца 03-08: «продавец формирует КП из воздуха; после сделки товаров как не
было, так и нет; ТН ВЭД и сроки заполняются — куда пишутся, непонятно». Замер: 90 из 98 строк
КП (92%) шли мимо каталога, обратного потока «строка → карточка» не было ни одного.

Эталон — catalog enablement (Ariba/Coupa): позиция вне каталога не запрещается, а уходит в
очередь; из повторяющихся рождаются каталожные карточки. Odoo делает это одним действием из
строки заказа.
"""

from decimal import Decimal

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.candidates import capture_quote_lines, ensure_candidate_for_line, find_existing_card
from catalog.models import Product, ProductStatus
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteItem, QuoteStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(db):
    for code, name in (("DRAFT", "Черновик"), ("PUBLISHED", "Опубликован")):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "Открытый RFQ", "sort_order": 25})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})

    seller = Company.objects.create(name="ООО Продавец N", inn="9200000001")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    buyer = Company.objects.create(name="ООО Покупатель N", inn="9200000002")
    user = CustomUser.objects.create_user(email="s@nom.test", username="s@nom.test", password="pw")
    CompanyMember.objects.create(
        user=user, company=seller, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    deal = Deal.objects.create(title="Заявка N", company=buyer, stage=DealStage.objects.get(code="RFQ_OPEN"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        seller_company=seller,
        total_incl_vat=Decimal("100"),
    )
    return {"seller": seller, "deal": deal, "quote": quote, "user": user}


def _line(quote, **kwargs):
    defaults = {"quote": quote, "position": 1, "quantity": 1}
    defaults.update(kwargs)
    return QuoteItem.objects.create(**defaults)


def test_line_without_a_product_becomes_a_candidate(world):
    line = _line(world["quote"], imported_raw_name="Подшипник буксовый 30-232726Е2М")

    product, created = ensure_candidate_for_line(line, world["seller"], deal=world["deal"])

    assert created is True
    assert product.name == "Подшипник буксовый 30-232726Е2М"
    assert product.owner_company_id == world["seller"].pk
    assert product.status.code == "DRAFT", "кандидат рождается черновиком, а не в каталоге"
    assert product.source_deal_id == world["deal"].pk, "карточка помнит, из какой заявки пришла"
    assert product.demand_count == 1


def test_the_knowledge_the_seller_typed_lands_in_the_card(world):
    """Прямой ответ на вопрос «куда пишутся ТН ВЭД и сроки»: раньше — никуда."""
    line = _line(
        world["quote"],
        imported_raw_name="Подшипник буксовый",
        mpn="30-232726Е2М",
        gost_drawing="ГОСТ 520-2011",
        hs_code="8482100000",
    )

    product, _created = ensure_candidate_for_line(line, world["seller"], deal=world["deal"])

    assert product.manufacturer_part_number == "30-232726Е2М"
    assert product.gost_drawing == "ГОСТ 520-2011"
    assert product.hs_code == "8482100000"


def test_second_quote_with_the_same_position_raises_demand_instead_of_duplicating(world):
    """Очередь наполнения сортируется по спросу — значит спрос обязан считаться."""
    first = _line(world["quote"], imported_raw_name="Скрепление КБ-65")
    ensure_candidate_for_line(first, world["seller"], deal=world["deal"])
    second = _line(world["quote"], position=2, imported_raw_name="Скрепление КБ-65")

    product, created = ensure_candidate_for_line(second, world["seller"], deal=world["deal"])

    assert created is False, "вторая такая же позиция не плодит карточку"
    assert product.demand_count == 2
    assert Product.objects.filter(owner_company=world["seller"]).count() == 1


def test_identity_beats_the_name_when_deduplicating(world):
    """Одна деталь под разными именами — одна карточка: ключ промышленной запчасти это артикул."""
    first = _line(world["quote"], imported_raw_name="Подшипник буксовый", mpn="30-232726Е2М")
    card, _ = ensure_candidate_for_line(first, world["seller"], deal=world["deal"])
    renamed = _line(
        world["quote"], position=2, imported_raw_name="Подшипник 232726 (буксовый узел)", mpn="30-232726Е2М"
    )

    found = find_existing_card(renamed, world["seller"])

    assert found is not None and found.pk == card.pk


def test_a_competitors_card_is_never_reused(world):
    """Гибрид Grainger: у каждого продавца СВОЯ карточка; чужая не подхватывается."""
    stranger = Company.objects.create(name="ООО Конкурент", inn="9200000003")
    Product.objects.create(name="Скрепление КБ-65", owner_company=stranger)
    line = _line(world["quote"], imported_raw_name="Скрепление КБ-65")

    product, created = ensure_candidate_for_line(line, world["seller"], deal=world["deal"])

    assert created is True
    assert product.owner_company_id == world["seller"].pk


def test_lines_that_describe_nothing_are_skipped(world):
    """Раздел/примечание/пустая строка карточкой не становятся."""
    blank = _line(world["quote"], imported_raw_name="   ")

    product, created = ensure_candidate_for_line(blank, world["seller"], deal=world["deal"])

    assert product is None and created is False


def test_already_matched_line_is_left_alone(world):
    existing = Product.objects.create(name="Уже в каталоге", owner_company=world["seller"])
    line = _line(world["quote"], imported_raw_name="Уже в каталоге", product=existing)

    product, created = ensure_candidate_for_line(line, world["seller"], deal=world["deal"])

    assert product is None and created is False


def test_capture_over_the_whole_quote_is_idempotent(world):
    """Повторная отправка того же КП не должна плодить каталог — поймано живым прогоном."""
    _line(world["quote"], imported_raw_name="Подшипник буксовый 30-232726Е2М")
    _line(world["quote"], position=2, imported_raw_name="Скрепление КБ-65")

    first = capture_quote_lines(world["quote"])
    second = capture_quote_lines(world["quote"])

    assert first == {"created": 2, "matched": 0, "skipped": 0}
    assert second == {"created": 0, "matched": 2, "skipped": 0}
    assert Product.objects.filter(owner_company=world["seller"]).count() == 2


def test_capture_never_breaks_the_send(world, monkeypatch):
    """Наполнение каталога — побочный эффект отправки КП и не имеет права её ронять."""
    _line(world["quote"], imported_raw_name="Подшипник")
    monkeypatch.setattr(
        "catalog.candidates.ensure_candidate_for_line",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("боль")),
    )

    assert capture_quote_lines(world["quote"]) == {"created": 0, "matched": 0, "skipped": 0}
