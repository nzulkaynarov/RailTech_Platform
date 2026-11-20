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
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus

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

    assert first == {"linked": 2, "skipped": 0}
    assert second == {"linked": 0, "skipped": 0}
    assert Product.objects.filter(owner_company=world["seller"]).count() == 2
    assert not world["quote"].items.filter(product__isnull=True).exists()


def test_capture_never_breaks_the_send(world, monkeypatch):
    """Наполнение каталога — побочный эффект отправки КП и не имеет права её ронять."""
    _line(world["quote"], imported_raw_name="Подшипник")
    monkeypatch.setattr(
        "catalog.candidates.ensure_candidate_for_line",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("боль")),
    )

    assert capture_quote_lines(world["quote"]) == {"linked": 0, "skipped": 0}


# ── СЦ-10: та же позиция, записанная иначе, не заводит вторую карточку ─────────────────────────────


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("Рельс  P65, ГОСТ  Р-51685.", "рельс р65 гост р-51685", True),
        ("Болт М12х1,5", "болт м12х1.5", True),
        ("Ёлка", "елка", True),
        ("«Шпала ЖБ»", "шпала жб", True),
        ("Болт М12х1.5", "Болт М12х15", False),
        ("Болт М22", "Болт М24", False),
        ("Р-65", "Р65", False),
        ("Кабель -40", "Кабель +40", False),
    ],
)
def test_name_key(a, b, same):
    from catalog.naming import name_key

    assert (name_key(a) == name_key(b)) is same


def test_name_written_otherwise_reuses_the_card(world):
    card = Product.objects.create(name="Болт М12", owner_company=world["seller"])
    line = _line(world["quote"], imported_raw_name="болт  m12.")

    product, created = ensure_candidate_for_line(line, world["seller"], deal=world["deal"])

    assert (product, created) == (card, False)
    product.refresh_from_db()
    assert product.demand_count == (card.demand_count or 0) + 1


def test_archived_card_does_not_take_the_line(world):
    ProductStatus.objects.get_or_create(code="ARCHIVED", defaults={"name": "Архив", "sort_order": 30})
    Product.objects.create(
        name="Шпала", owner_company=world["seller"], status=ProductStatus.objects.get(code="ARCHIVED")
    )
    line = _line(world["quote"], imported_raw_name="Шпала")

    _product, created = ensure_candidate_for_line(line, world["seller"], deal=world["deal"])

    assert created is True


def test_published_card_wins_over_an_older_draft(world):
    draft = Product.objects.create(name="Накладка стыковая Р65", owner_company=world["seller"])
    published = Product.objects.create(
        name="Накладка стыковая P65",
        owner_company=world["seller"],
        status=ProductStatus.objects.get(code="PUBLISHED"),
    )
    assert draft.pk < published.pk
    line = _line(world["quote"], imported_raw_name="накладка стыковая р65")

    assert find_existing_card(line, world["seller"]) == published


def test_long_title_finds_its_own_draft(world):
    title = "Рельс " + "очень длинное наименование " * 12
    first, created = ensure_candidate_for_line(
        _line(world["quote"], imported_raw_name=title), world["seller"], deal=world["deal"]
    )
    again, created_again = ensure_candidate_for_line(
        _line(world["quote"], imported_raw_name=title, position=2), world["seller"], deal=world["deal"]
    )

    assert created is True and created_again is False and again == first


def test_name_key_follows_a_rename_with_update_fields(world):
    card = Product.objects.create(name="Старое", owner_company=world["seller"])
    card.name = "Новое  Имя"
    card.save(update_fields=["name"])
    card.refresh_from_db()

    assert card.name_key == "новое имя"


def test_found_card_gives_its_unit_to_a_line_without_one(world):
    from catalog.candidates import link_line
    from core.models import UnitOfMeasure
    from core.seeds.uom import seed_uom

    seed_uom()
    Product.objects.create(name="Болт М22", owner_company=world["seller"], uom=UnitOfMeasure.objects.get(code="KGM"))
    bare = _line(world["quote"], imported_raw_name="Болт М22")
    written = _line(world["quote"], imported_raw_name="болт м22", unit="т", position=2)

    assert link_line(bare, world["seller"]) and link_line(written, world["seller"])

    bare.refresh_from_db()
    written.refresh_from_db()
    assert (bare.unit_code, bare.unit) == ("KGM", "кг")
    assert (written.unit_code, written.unit) == ("", "т")
