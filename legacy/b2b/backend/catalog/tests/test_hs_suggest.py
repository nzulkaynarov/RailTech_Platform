"""Код ТН ВЭД ВЫБИРАЕТСЯ из справочника, а не сочиняется.

Придуманный код ТН ВЭД хуже отсутствующего: десять цифр выглядят одинаково убедительно и когда
верны, и когда выдуманы, а узнает продавец об ошибке на границе. Поэтому подсказка — это
retrieval по классификатору `master_data.HSCode`, и языковая модель сюда не входит: когда
справочник наполнится, она сможет ВЫБИРАТЬ из этих кандидатов, но не генерировать цифры.

Система обязана работать и с ПУСТЫМ справочником — тогда код вводится вручную, как раньше.
"""

import pytest

from catalog.hs_suggest import is_known_code, suggest_hs_codes
from master_data.models import HSCode

pytestmark = pytest.mark.django_db


@pytest.fixture
def classifier(db):
    rows = [
        ("86", "Железнодорожные локомотивы, подвижной состав и их части", 2),
        ("8607", "Части железнодорожных локомотивов либо подвижного состава", 4),
        ("860721", "Тормоза пневматические и их части", 6),
        ("8607211000", "Тормоза пневматические из чугунного или стального литья", 10),
        ("8482", "Подшипники шариковые или роликовые", 4),
        ("848210", "Подшипники шариковые", 6),
        ("8482100000", "Подшипники шариковые прочие", 10),
    ]
    for code, name, level in rows:
        HSCode.objects.create(code=code, name=name, level=level)
    return rows


def test_suggests_by_product_name(classifier):
    candidates = suggest_hs_codes("Тормоза пневматические", limit=3)

    assert candidates, "по прямому названию позиции кандидаты обязаны находиться"
    assert candidates[0]["code"].startswith("8607")


def test_digits_are_treated_as_an_exact_code_lookup(classifier):
    candidates = suggest_hs_codes("8482", limit=5)

    codes = [c["code"] for c in candidates]
    assert "8482" in codes
    assert all(code.startswith("8482") for code in codes), "цифры — это поиск кода, а не текста"


def test_too_general_groups_are_not_offered(classifier):
    """Группа «86 — локомотивы и подвижной состав» в карточке бесполезна."""
    codes = [c["code"] for c in suggest_hs_codes("подшипники", limit=8)]

    assert "86" not in codes
    assert all(len(code) >= 6 for code in codes)


def test_empty_classifier_returns_nothing_and_does_not_block(db):
    """Справочник ещё не загружен — подсказок нет, но работа не останавливается."""
    assert suggest_hs_codes("Подшипник буксовый") == []
    # Валидация при пустом справочнике пропускает ЛЮБОЙ код: иначе система стала бы
    # неработоспособной до загрузки классификатора (новых гейтов не вводим, PRODUCT RULE 2).
    assert is_known_code("8482100000") is True


def test_known_code_is_distinguished_from_an_invented_one(classifier):
    assert is_known_code("8482100000") is True
    assert is_known_code("8482 10 0000") is True, "разделители внутри кода не должны мешать"
    assert is_known_code("9999999999") is False
    assert is_known_code("") is False


def test_import_command_builds_the_hierarchy(db, tmp_path):
    """Иерархия выводится из самих кодов — отдельного столбца «родитель» в выгрузках не бывает."""
    from django.core.management import call_command

    csv_file = tmp_path / "hs.csv"
    csv_file.write_text(
        "code,name\n8482,Подшипники\n848210,Подшипники шариковые\n8482 10 0000,Подшипники шариковые прочие\n",
        encoding="utf-8",
    )

    call_command("import_hs_codes", str(csv_file), source="тест")

    ten = HSCode.objects.get(code="8482100000")
    assert ten.level == 10, "разделители вычищаются, уровень = число цифр"
    assert ten.parent.code == "848210"
    assert ten.parent.parent.code == "8482"


def test_reimport_updates_names_without_duplicating(db, tmp_path):
    """Новую редакцию классификатора накатывают поверх старой."""
    from django.core.management import call_command

    first = tmp_path / "a.csv"
    first.write_text("code,name\n8482,Старое наименование\n", encoding="utf-8")
    second = tmp_path / "b.csv"
    second.write_text("code,name\n8482,Новое наименование\n", encoding="utf-8")

    call_command("import_hs_codes", str(first))
    call_command("import_hs_codes", str(second))

    assert HSCode.objects.filter(code="8482").count() == 1
    assert HSCode.objects.get(code="8482").name == "Новое наименование"


def test_short_query_finds_a_long_tree_path_name(db):
    """Имена ГТК — длинные пути по дереву; пословное сходство обязано до них дотягиваться.

    До правки «тормозная колодка» не находила НИЧЕГО (сходство целых строк ≈ 0 против
    длинного имени), хотя правильная позиция 6813 81 в базе была.
    """
    HSCode.objects.create(
        code="6813810009",
        name=(
            "Фрикционные материалы и изделия из них (например, листы, рулоны, ленты, "
            "сегменты, диски, шайбы, прокладки), несмонтированные, для тормозов: "
            "не содержащие асбест: тормозные накладки и колодки: прочие"
        ),
        level=10,
    )

    candidates = suggest_hs_codes("тормозная колодка", limit=3)

    assert candidates, "короткий запрос обязан находить длинное имя-путь"
    assert candidates[0]["code"] == "6813810009"


def test_retired_codes_are_not_suggested_for_new_cards(db):
    """Автосинк закрывает исчезнувшие коды датой — предлагать их в новую карточку нельзя."""
    import datetime

    HSCode.objects.create(code="8482100000", name="Подшипники шариковые прочие", level=10)
    HSCode.objects.create(
        code="8482109008",
        name="Подшипники шариковые устаревшие",
        level=10,
        valid_until=datetime.date(2025, 1, 1),
    )

    codes = [c["code"] for c in suggest_hs_codes("подшипники шариковые", limit=5)]

    assert "8482100000" in codes
    assert "8482109008" not in codes, "закрытый код не подсказывается"
    # …но старый документ с ним по-прежнему валиден.
    assert is_known_code("8482109008") is True
