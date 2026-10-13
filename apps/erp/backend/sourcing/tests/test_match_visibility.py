"""Матчинг подставляет только то, что зритель имеет право видеть.

До волны A `smart_match_product` работал по `Product.objects.all()` — без фильтра владельца и
БЕЗ фильтра статуса. Пока каталог был пуст, это не проявлялось; как только очередь кандидатов
наполнилась (волна A), чужой ЧЕРНОВИК стал законным кандидатом на подстановку в КП. Это
одновременно мусор в подборе и утечка: в модели «скрытой конкуренции» (ADR-0003 §5) продавец
не должен узнавать, что заводит сосед.

Правило: опубликованное видно всем, неопубликованное — только своей компании.
"""

import pytest

from accounts.models import Company
from catalog.models import Product, ProductStatus
from sourcing.services import smart_match_candidates, smart_match_product

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog(db):
    for code, name in (("DRAFT", "Черновик"), ("PUBLISHED", "Опубликован")):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    mine = Company.objects.create(name="ООО Моя", inn="9400000001")
    rival = Company.objects.create(name="ООО Конкурент", inn="9400000002")
    draft = ProductStatus.objects.get(code="DRAFT")
    published = ProductStatus.objects.get(code="PUBLISHED")
    return {
        "mine": mine,
        "rival": rival,
        "my_draft": Product.objects.create(name="Клапан концевой 4300", owner_company=mine, status=draft),
        "rival_draft": Product.objects.create(name="Кран разобщительный 4200", owner_company=rival, status=draft),
        "published": Product.objects.create(name="Тормозная колодка 25610Н", owner_company=rival, status=published),
    }


def test_published_card_is_visible_to_everyone(catalog):
    assert smart_match_product("Тормозная колодка 25610Н", owner_company=catalog["mine"]) is not None


def test_a_rivals_draft_is_never_matched(catalog):
    """Главное правило волны: черновик соседа не подставляется и не подсказывается."""
    assert smart_match_product("Кран разобщительный 4200", owner_company=catalog["mine"]) is None

    names = [c.get("name") for c in smart_match_candidates("Кран разобщительный 4200", owner_company=catalog["mine"])]
    assert "Кран разобщительный 4200" not in names


def test_my_own_draft_is_matched_for_me(catalog):
    """Свои кандидаты подставляться обязаны — иначе наполнение каталога не окупается."""
    found = smart_match_product("Клапан концевой 4300", owner_company=catalog["mine"])

    assert found is not None and found.owner_company_id == catalog["mine"].pk


def test_without_a_viewer_only_published_is_matched(catalog):
    """Безымянный вызов (фон, импорт) не должен видеть ничьи черновики."""
    assert smart_match_product("Клапан концевой 4300") is None
    assert smart_match_product("Тормозная колодка 25610Н") is not None
