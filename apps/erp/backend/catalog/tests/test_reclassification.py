"""T2 — переклассификация: закрытый редакцией код порождает РАБОТУ, а не тихую порчу.

Паттерн SAP GTS: смена редакции номенклатуры создаёт worklist на переклассификацию. У нас
автосинк с tarif.customs.uz закрывает исчезнувшие коды `valid_until` — без T2 карточка с
закрытым кодом продолжала бы наследовать мёртвый код в каждое новое КП, и продавец узнал бы
об этом на границе.

Плюс провенанс (паттерн Avalara: у классификации есть источник): каждая смена кода оставляет
след в журнале — manual / quote_line / ai. «Кто так решил» перестаёт быть вопросом.
"""

import datetime

import pytest

from accounts.models import Company
from catalog.completeness import completeness
from catalog.hs_suggest import cards_with_retired_codes
from catalog.models import Product, ProductStatus
from catalog.services import log_hs_code_change
from crm.models import ActivityLog
from master_data.models import HSCode

pytestmark = pytest.mark.django_db

YESTERDAY = datetime.date.today() - datetime.timedelta(days=1)


@pytest.fixture
def world(db):
    for code, name in (("DRAFT", "Черновик"), ("PUBLISHED", "Опубликован"), ("ARCHIVED", "В архиве")):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    HSCode.objects.create(code="8482100000", name="Подшипники шариковые прочие", level=10)
    HSCode.objects.create(code="8607191000", name="Оси в сборе", level=10, valid_until=YESTERDAY)
    company = Company.objects.create(name="ООО Переклассификация", inn="9600000001")
    return {"company": company}


def _card(world, **kwargs):
    defaults = {"name": "Ось колёсной пары", "owner_company": world["company"]}
    defaults.update(kwargs)
    return Product.objects.create(**defaults)


def test_card_with_a_retired_code_enters_the_worklist(world):
    stale = _card(world, hs_code="8607191000")
    fresh = _card(world, name="Подшипник", hs_code="8482100000")

    worklist = list(cards_with_retired_codes(world["company"]))

    assert stale in worklist
    assert fresh not in worklist


def test_archived_cards_are_not_nagged(world):
    """Архивная карточка ничего не наследует в новые КП — переклассифицировать её незачем."""
    _card(world, hs_code="8607191000", status=ProductStatus.objects.get(code="ARCHIVED"))

    assert list(cards_with_retired_codes(world["company"])) == []


def test_retired_code_breaks_completeness_with_a_named_reason(world):
    """Карточка с мёртвым кодом перестаёт быть «полной» — и подсказка называет причину."""
    card = _card(world, hs_code="8607191000")

    report = completeness(card)

    assert report["is_publishable"] is False
    assert any(item["code"] == "hs_code" for item in report["missing"])


def test_current_code_still_satisfies_completeness(world):
    card = _card(world, hs_code="8482100000")

    assert not any(item["code"] == "hs_code" for item in completeness(card)["missing"])


def test_hs_code_change_leaves_a_provenance_trail(world):
    card = _card(world, hs_code="8482100000")
    card.hs_code = "8607191000"
    card.save(update_fields=["hs_code"])

    log_hs_code_change(card, "8482100000", None, origin="quote_line")

    entry = ActivityLog.objects.get(event_code="product.hs_code_changed")
    assert entry.event_params["from_code"] == "8482100000"
    assert entry.event_params["to_code"] == "8607191000"
    assert entry.event_params["origin"] == "quote_line"


def test_no_trail_when_the_code_did_not_change(world):
    card = _card(world, hs_code="8482100000")

    log_hs_code_change(card, "8482100000", None, origin="manual")

    assert not ActivityLog.objects.filter(event_code="product.hs_code_changed").exists()
