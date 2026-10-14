"""Волна R5a: прайс-лист научился приносить ТАКСОНОМИЮ, а отчёт — говорить цену наполнения.

До волны загрузка физически не могла заполнить категорию, код ТН ВЭД и направление — ровно то,
чего требует порог публикации. Три тысячи строк превращались в три тысячи черновиков, и отчёт
бодро рапортовал «Создано: 3000», не сказав, что опубликовать нельзя ни одну.

Тесты держат четыре обещания волны:
  1. новые колонки не отняли колонок у старых полей (разбор шапки — подстрочный и жадный);
  2. чужое слово в категории/направлении — честная ошибка строки, а расхождение кода ТН ВЭД со
     справочником — ПРЕДУПРЕЖДЕНИЕ (новых блокировок волна не добавляет, PRODUCT RULE 2);
  3. отчёт считает непубликуемые карточки теми же правилами, что и кнопка «Опубликовать», и
     цена этого счёта не растёт со строками файла;
  4. молчаливые потери (обрезка по лимиту строк, безымянное ROW_FAILED) обрели имя.
"""

import datetime
from io import BytesIO

import pandas as pd
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from sourcing.catalog_import import ImportResult, _hs_digits, _resolve_columns, run_catalog_import

SERVICES = "SERVICES"
LIVE_HS = "8482100000"
RETIRED_HS = "8607191000"


def _xlsx(records, columns=None):
    buffer = BytesIO()
    pd.DataFrame(records, columns=columns).to_excel(buffer, index=False)
    return buffer.getvalue()


@pytest.fixture
def world(db):
    """Живые справочники: без них порог публикации меряет пустоту, а не правила."""
    from catalog.models import Category, DomainType, ProductStatus, StockStatus
    from master_data.models import Currency, UnitOfMeasure

    Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "symbol": "сўм"})
    StockStatus.objects.get_or_create(code="IN_STOCK", defaults={"name": "В наличии"})
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик"})
    ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Опубликован"})
    unit, _ = UnitOfMeasure.objects.get_or_create(code="PCS", defaults={"name": "шт"})
    services, _ = DomainType.objects.get_or_create(code=SERVICES, defaults={"name": "Услуги"})
    goods, _ = DomainType.objects.get_or_create(code="GENERAL_GOODS", defaults={"name": "Общие товары"})
    category, _ = Category.objects.get_or_create(name="Тормозное оборудование")
    return {"unit": unit, "services": services, "goods": goods, "category": category}


@pytest.fixture
def seller(company_factory):
    return company_factory(name="Seller", inn="111111111")


# ── 1. Разбор шапки: новые алиасы ничего не отняли ───────────────────────────────────────


def test_full_template_header_maps_every_field_to_its_own_column():
    """Шапка эталонного шаблона разбирается однозначно — включая три новые колонки."""
    from sourcing.views_imports import CATALOG_TEMPLATE_HEADERS

    resolved = _resolve_columns([header.lower().strip() for header in CATALOG_TEMPLATE_HEADERS])

    assert resolved["name"] == "наименование"
    assert resolved["category"] == "категория"
    assert resolved["hs_code"] == "код тн вэд"
    assert resolved["domain_type"] == "направление"
    # Старые поля остались при своих колонках.
    assert resolved["mpn"] == "артикул производителя"
    assert resolved["supplier_sku"] == "артикул поставщика"
    assert resolved["brand"] == "бренд"
    assert resolved["gost"] == "гост / чертёж"
    assert resolved["uom"] == "ед. изм."
    assert resolved["price"] == "цена"
    assert resolved["lead"] == "срок поставки"
    assert resolved["moq"] == "мин. заказ"
    assert len({column for column in resolved.values() if column}) == len(
        [column for column in resolved.values() if column]
    ), "одна колонка не может достаться двум полям"


def test_new_aliases_do_not_steal_columns_of_old_fields():
    """«Направление» не похоже на «Наименование», «Код ТН ВЭД» — не «Артикул»."""
    resolved = _resolve_columns(["наименование", "артикул поставщика", "код тн вэд", "направление", "цена"])

    assert resolved["name"] == "наименование"
    assert resolved["supplier_sku"] == "артикул поставщика"
    assert resolved["hs_code"] == "код тн вэд"
    assert resolved["domain_type"] == "направление"


def test_category_claims_its_column_before_the_name_field_takes_it():
    """«Категория товара» уходит категории: алиас `name` («товар») иначе назвал бы карточки категориями."""
    resolved = _resolve_columns(["категория товара", "наименование", "цена"])

    assert resolved["category"] == "категория товара"
    assert resolved["name"] == "наименование"


def test_domain_column_does_not_swallow_the_delivery_lead_column():
    """«Направление поставки» — это срок/логистика: домен ставится ПОСЛЕ старых полей и не спорит."""
    resolved = _resolve_columns(["наименование", "направление поставки"])

    assert resolved["lead"] == "направление поставки"
    assert resolved["domain_type"] is None


# ── 2. Категория: читаем справочник, но никогда его не пишем ─────────────────────────────


@pytest.mark.parametrize("written", ["Тормозное оборудование", "тормозное ОБОРУДОВАНИЕ"])
@pytest.mark.django_db
def test_category_is_resolved_case_insensitively(world, seller, written):
    from catalog.models import Product

    result = run_catalog_import(
        _xlsx([{"Наименование": "Колодка", "Артикул производителя": "K-1", "Бренд": "KB", "Категория": written}]),
        supplier_company_id=seller.id,
    )

    assert result["skipped"] == 0
    assert Product.objects.get(manufacturer_part_number="K-1").category_id == world["category"].id


@pytest.mark.django_db
def test_unknown_category_is_a_row_error_and_never_creates_taxonomy(world, seller):
    """Таксономия платформенная: продавец её ВЫБИРАЕТ, а не заводит загрузкой файла."""
    from catalog.models import Category, Product

    before = Category.objects.count()
    result = run_catalog_import(
        _xlsx([{"Наименование": "Колодка", "Цена": "10", "Валюта": "UZS", "Категория": "Придуманная ветка"}]),
        supplier_company_id=seller.id,
    )

    assert result["created"] == 0
    assert result["skipped"] == 1
    assert result["errors"][0]["message"] == "UNKNOWN_CATEGORY:Придуманная ветка"
    assert Category.objects.count() == before, "категория не создаётся импортом"
    assert Product.objects.count() == 0, "строка откатана целиком, как и при чужой валюте"


@pytest.mark.django_db
def test_category_is_applied_to_an_existing_card_on_reimport(world, seller):
    """Смысл волны: повторная загрузка ДОЗАПОЛНЯЕТ карточку, а не только цену."""
    from catalog.models import Manufacturer, Product

    brand = Manufacturer.objects.create(name="KB")
    product = Product.objects.create(name="Колодка", brand=brand, manufacturer_part_number="K-9")

    run_catalog_import(
        _xlsx(
            [
                {
                    "Наименование": "Колодка",
                    "Бренд": "KB",
                    "Артикул производителя": "K-9",
                    "Категория": "Тормозное оборудование",
                }
            ]
        ),
        supplier_company_id=seller.id,
    )

    product.refresh_from_db()
    assert product.category_id == world["category"].id


# ── 3. Направление: явное значение сильнее догадки по ключевым словам ────────────────────


@pytest.mark.django_db
def test_explicit_domain_beats_the_keyword_guess(world, seller):
    """Догадка смотрит только на наименование; продавец сказал прямо — прямое и записываем."""
    from catalog.models import Product

    run_catalog_import(
        _xlsx(
            [
                {
                    "Наименование": "Колодка",
                    "Бренд": "B",
                    "Артикул производителя": "D-1",
                    "Направление": world["goods"].name,
                }
            ]
        ),
        supplier_company_id=seller.id,
    )

    assert Product.objects.get(manufacturer_part_number="D-1").domain_type.code == "GENERAL_GOODS"


@pytest.mark.parametrize("written", [SERVICES, "services", "name", "NAME"])
@pytest.mark.django_db
def test_domain_accepts_both_the_code_and_the_human_name(world, seller, written):
    """Продавец пишет в файле или код, или человеческое название направления — регистр не важен."""
    from catalog.models import Product

    services_name = world["services"].name
    value = {"name": services_name, "NAME": services_name.upper()}.get(written, written)
    result = run_catalog_import(
        _xlsx([{"Наименование": "Ось", "Бренд": "B", "Артикул производителя": "D-2", "Направление": value}]),
        supplier_company_id=seller.id,
    )

    assert result["skipped"] == 0
    assert Product.objects.get(manufacturer_part_number="D-2").domain_type.code == SERVICES


@pytest.mark.django_db
def test_unknown_domain_is_a_row_error(world, seller):
    result = run_catalog_import(
        _xlsx([{"Наименование": "Ось", "Цена": "5", "Валюта": "UZS", "Направление": "Металлопрокат"}]),
        supplier_company_id=seller.id,
    )

    assert result["skipped"] == 1
    assert result["errors"][0]["message"] == "UNKNOWN_DOMAIN:Металлопрокат"


@pytest.mark.django_db
def test_explicit_domain_corrects_an_existing_card_but_a_guess_never_does(world, seller):
    """Явное направление правит карточку; ДОГАДКА остаётся правом только новой карточки."""
    from catalog.models import Manufacturer, Product

    brand = Manufacturer.objects.create(name="B")
    guessed = Product.objects.create(
        name="Ось", brand=brand, manufacturer_part_number="D-3", domain_type=world["goods"]
    )
    corrected = Product.objects.create(
        name="Ось", brand=brand, manufacturer_part_number="D-4", domain_type=world["goods"]
    )

    run_catalog_import(
        _xlsx(
            [
                {"Наименование": "Ось", "Бренд": "B", "Артикул производителя": "D-3", "Направление": ""},
                {
                    "Наименование": "Ось",
                    "Бренд": "B",
                    "Артикул производителя": "D-4",
                    "Направление": world["goods"].name,
                },
            ]
        ),
        supplier_company_id=seller.id,
    )

    guessed.refresh_from_db()
    corrected.refresh_from_db()
    assert guessed.domain_type.code == "GENERAL_GOODS", "догадка не переклассифицирует готовую карточку"
    assert corrected.domain_type.code == "GENERAL_GOODS"


# ── 4. Код ТН ВЭД: мягкая проверка, предупреждение вместо блока ──────────────────────────


def test_hs_digits_drops_the_float_tail_excel_adds():
    """Числовая ячейка приезжает как 8482100000.0 — хвост не часть кода (иначе 10 цифр → 11)."""
    assert _hs_digits("8482100000.0") == LIVE_HS
    assert _hs_digits("8482 10 0000") == LIVE_HS
    assert _hs_digits("") == ""


@pytest.mark.django_db
def test_hs_code_is_written_and_unknown_code_only_warns(world, seller):
    from catalog.models import Product
    from master_data.models import HSCode

    HSCode.objects.create(code=LIVE_HS, name="Подшипники шариковые", level=10)

    result = run_catalog_import(
        _xlsx(
            [
                {"Наименование": "Подшипник", "Бренд": "B", "Артикул производителя": "H-1", "Код ТН ВЭД": LIVE_HS},
                {"Наименование": "Втулка", "Бренд": "B", "Артикул производителя": "H-2", "Код ТН ВЭД": "9999999999"},
            ]
        ),
        supplier_company_id=seller.id,
    )

    assert result["created"] == 2, "предупреждение не отменяет строку"
    assert result["skipped"] == 0, "и не попадает в пропущенные"
    assert result["warning_count"] == 1
    assert result["warnings"][0]["message"] == "HS_CODE_NOT_IN_CLASSIFIER:9999999999"
    assert Product.objects.get(manufacturer_part_number="H-2").hs_code == "9999999999", "код продавца записан"


@pytest.mark.django_db
def test_retired_hs_code_warns_with_its_own_code(world, seller):
    from master_data.models import HSCode

    HSCode.objects.create(code=RETIRED_HS, name="Оси в сборе", level=10, valid_until=datetime.date(2025, 1, 1))

    result = run_catalog_import(
        _xlsx([{"Наименование": "Ось", "Бренд": "B", "Артикул производителя": "H-3", "Код ТН ВЭД": RETIRED_HS}]),
        supplier_company_id=seller.id,
    )

    assert result["skipped"] == 0
    assert result["warnings"][0]["message"] == f"HS_CODE_RETIRED:{RETIRED_HS}"


@pytest.mark.django_db
def test_empty_classifier_is_silent(world, seller):
    """Справочник не загружен → любой код действующий: работа без данных не блокируется."""
    result = run_catalog_import(
        _xlsx([{"Наименование": "Ось", "Бренд": "B", "Артикул производителя": "H-4", "Код ТН ВЭД": "1234567890"}]),
        supplier_company_id=seller.id,
    )

    assert result["warning_count"] == 0
    assert result["created"] == 1


@pytest.mark.django_db
def test_overlong_hs_code_warns_instead_of_failing_the_row(world, seller):
    """Код длиннее поля карточки не записать — но ронять из-за этого прайс-лист не за что."""
    from catalog.models import Product

    result = run_catalog_import(
        _xlsx([{"Наименование": "Ось", "Бренд": "B", "Артикул производителя": "H-5", "Код ТН ВЭД": "1" * 20}]),
        supplier_company_id=seller.id,
    )

    assert result["created"] == 1
    assert result["skipped"] == 0
    assert result["warnings"][0]["message"] == "HS_CODE_TOO_LONG:" + "1" * 20
    assert Product.objects.get(manufacturer_part_number="H-5").hs_code == ""


@pytest.mark.django_db
def test_batch_hs_verdict_agrees_with_the_single_code_one(db):
    """Пакетная проверка обязана давать ТОТ ЖЕ вердикт — иначе импорт и форма разойдутся."""
    from catalog.hs_suggest import validate_hs_code, validate_hs_codes
    from master_data.models import HSCode

    HSCode.objects.create(code=LIVE_HS, name="Подшипники шариковые", level=10)
    HSCode.objects.create(code=RETIRED_HS, name="Оси в сборе", level=10, valid_until=datetime.date(2025, 1, 1))

    batch = validate_hs_codes([LIVE_HS, RETIRED_HS, "9999999999", "", "не код"])

    assert set(batch) == {LIVE_HS, RETIRED_HS, "9999999999"}
    for code, verdict in batch.items():
        assert verdict == validate_hs_code(code)


# ── 5. Отчёт называет цену наполнения ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_report_counts_unpublishable_cards_and_names_what_is_missing(world, seller):
    """Главный ответ волны продавцу: сколько карточек порог не пройдут и чего им не хватает."""
    goods = world["goods"].name
    result = run_catalog_import(
        _xlsx(
            [
                {
                    "Наименование": "Полная",
                    "Бренд": "B",
                    "Артикул производителя": "P-1",
                    "Ед. изм.": "pcs",
                    "Категория": "Тормозное оборудование",
                    "Код ТН ВЭД": LIVE_HS,
                    "Направление": goods,
                    "Описание": "Описание для клиента",
                },
                {"Наименование": "Пустая", "Бренд": "B", "Артикул производителя": "P-2", "Направление": goods},
            ]
        ),
        supplier_company_id=seller.id,
    )

    assert result["created"] == 2
    assert result["unpublishable"] == 1, "полностью заполненная карточка публикуема"
    missing = {item["code"]: item for item in result["missing_breakdown"]}
    assert set(missing) == {"uom", "category", "hs_code", "content"}
    assert missing["category"]["count"] == 1
    assert missing["category"]["label"] == "Категория", "подпись берётся из completeness.py, а не заводится заново"


@pytest.mark.django_db
def test_dry_run_reports_publishability_and_still_persists_nothing(world, seller):
    """Предпросмотр обязан сказать цену наполнения ДО записи — ради него волна и затевалась."""
    from catalog.models import Product

    result = run_catalog_import(
        _xlsx(
            [{"Наименование": "Черновик", "Бренд": "B", "Артикул производителя": "P-3", "Цена": "10", "Валюта": "UZS"}]
        ),
        supplier_company_id=seller.id,
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["created"] == 1
    assert result["unpublishable"] == 1
    assert {item["code"] for item in result["missing_breakdown"]} == {"uom", "category", "hs_code", "content"}
    assert Product.objects.count() == 0, "откат предпросмотра не тронут"


@pytest.mark.django_db
def test_publishability_summary_costs_the_same_for_three_and_thirty_cards(world, django_assert_num_queries):
    """Тот же инвариант, что у списков (R1): сводка не платит запросами ЗА СТРОКУ.

    Справочники здесь наполнены намеренно — на пустых дорогая ветка полноты просто не работает.
    """
    from catalog.completeness import summarize_completeness
    from catalog.models import Product
    from master_data.models import HSCode

    HSCode.objects.create(code=LIVE_HS, name="Подшипники шариковые", level=10)

    def make(count, offset):
        return [
            Product.objects.create(
                name=f"Карточка {index:03d}",
                manufacturer_part_number=f"Q-{index}",
                domain_type=world["goods"],
                uom=world["unit"],
                category=world["category"],
                hs_code="",
                description="Описание для клиента",
            )
            for index in range(offset, offset + count)
        ]

    # Прогрев — на ОТДЕЛЬНОЙ пачке: `prefetch_related_objects` не трогает объекты с уже
    # прогретым кэшем, и прогрев на измеряемой пачке занизил бы базу на один запрос.
    summarize_completeness(make(2, 900))
    small, large = make(3, 0), make(30, 100)

    with CaptureQueriesContext(connection) as captured:
        summarize_completeness(small)
    baseline = len(captured.captured_queries)

    with django_assert_num_queries(baseline):
        summary = summarize_completeness(large)

    assert summary["unpublishable"] == 30
    assert summary["missing_breakdown"][0]["code"] == "hs_code"
    assert baseline <= 5, f"сводка обязана стоить единицы запросов, а не {baseline}"


# ── 6. Молчаливые потери обрели имя ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_rows_beyond_the_limit_are_reported_not_silently_dropped(world, seller, monkeypatch):
    """`nrows=MAX_EXCEL_ROWS` резал хвост молча: продавец не узнавал, что часть прайса не читали."""
    monkeypatch.setattr("sourcing.catalog_import.MAX_EXCEL_ROWS", 2)
    rows = [
        {"Наименование": f"Строка {index}", "Бренд": "B", "Артикул производителя": f"T-{index}"} for index in range(5)
    ]

    result = run_catalog_import(_xlsx(rows), supplier_company_id=seller.id)

    assert result["created"] == 2
    assert result["rows_truncated"] == 3


@pytest.mark.django_db
def test_no_truncation_reported_for_a_file_within_the_limit(world, seller):
    result = run_catalog_import(
        _xlsx([{"Наименование": "Одна", "Бренд": "B", "Артикул производителя": "T-9"}]),
        supplier_company_id=seller.id,
    )

    assert result["rows_truncated"] == 0


def test_counters_outlive_the_reported_lists():
    """«Показаны первые 200 из N» возможно уже сегодня: списки усечены, счётчики — нет."""
    result = ImportResult()
    for row_number in range(250):
        result.add_error(row_number, "PRICE_NOT_A_NUMBER")
        result.add_warning(row_number, "HS_CODE_RETIRED:1")

    payload = result.as_dict()
    assert payload["error_count"] == 250 and len(payload["errors"]) == 200
    assert payload["warning_count"] == 250 and len(payload["warnings"]) == 200


@pytest.mark.django_db
def test_result_payload_carries_every_promised_key(world, seller):
    """Контракт с интерфейсом: набор ключей фиксирован, страница на него опирается."""
    result = run_catalog_import(
        _xlsx([{"Наименование": "Одна", "Бренд": "B", "Артикул производителя": "K-77"}]),
        supplier_company_id=seller.id,
    )

    assert set(result) == {
        "status",
        "dry_run",
        "created",
        "updated",
        "offers_upserted",
        "skipped",
        "error_count",
        "errors",
        "warning_count",
        "warnings",
        "rows_truncated",
        "unpublishable",
        "missing_breakdown",
        "items_processed",
    }


@pytest.mark.django_db
def test_template_carries_the_new_columns_and_real_reference_values(world, user_factory):
    """Шаблон — единственная инструкция продавца: новые колонки и допустимые значения в нём."""
    from openpyxl import load_workbook
    from rest_framework.test import APIClient

    from catalog.models import Category

    client = APIClient()
    client.force_authenticate(user=user_factory(email="seller-r5a@example.com", username="seller-r5a"))

    response = client.get("/api/v1/sourcing/catalog-template/")
    workbook = load_workbook(BytesIO(response.content))
    header = [cell.value for cell in workbook["Товары"][1]]
    example = dict(zip(header, [cell.value for cell in workbook["Товары"][2]]))
    reference = {(row[0].value, row[2].value) for row in workbook["Справочники (коды)"].iter_rows(min_row=2)}

    first_category = Category.objects.filter(is_active=True).order_by("sort_order", "name").first()
    assert {"Категория", "Код ТН ВЭД", "Направление"} <= set(header)
    assert example["Категория"] == first_category.name, "пример берётся из живой таксономии"
    assert example["Направление"] == world["goods"].name
    assert ("Категория", world["category"].name) in reference
    assert ("Направление", world["goods"].name) in reference


# ── 6. Ведущий ноль в коде ТН ВЭД ────────────────────────────────────────────────────────
#
# Найдено ПРОХОДОМ ГЛАЗАМИ, а не тестом: файл разбирался «успешно», просто у кода пропадала
# первая цифра. `pd.read_excel` без `dtype` выводит тип колонки сам, и колонка кодов из
# текстовой становилась числовой — `0101210000` приезжало как `101210000`. Продавец получал
# замечание «кода нет в справочнике» на ВЕРНЫЙ код, а в карточку писался испорченный, из-за
# чего она ещё и объявлялась неопубликуемой. Нулём начинаются целые группы классификатора
# (01–09), так что случай не экзотический.

ZERO_HS = "0101210000"


@pytest.mark.django_db
def test_leading_zero_in_hs_code_survives_the_import(world, seller):
    from catalog.models import Product
    from master_data.models import HSCode

    HSCode.objects.create(code=ZERO_HS, name="Лошади племенные", level=10)

    result = run_catalog_import(
        _xlsx(
            [
                {
                    "Наименование": "Позиция с нулевым кодом",
                    "Артикул производителя": "Z-1",
                    "Бренд": "NN",
                    "Код ТН ВЭД": ZERO_HS,
                }
            ]
        ),
        supplier_company_id=seller.id,
    )

    assert result["warning_count"] == 0, "верный код не должен давать замечание"
    assert Product.objects.get(manufacturer_part_number="Z-1").hs_code == ZERO_HS


@pytest.mark.django_db
def test_leading_zero_code_does_not_make_the_card_unpublishable(world, seller):
    from master_data.models import HSCode

    HSCode.objects.create(code=ZERO_HS, name="Лошади племенные", level=10)

    result = run_catalog_import(
        _xlsx(
            [
                {
                    "Наименование": "Полная карточка",
                    "Артикул производителя": "Z-2",
                    "Бренд": "NN",
                    "Категория": "Тормозное оборудование",
                    "Код ТН ВЭД": ZERO_HS,
                    "Ед. изм.": "PCS",
                    "Направление": "GENERAL_GOODS",
                    "Описание": "Описание для клиента",
                }
            ]
        ),
        supplier_company_id=seller.id,
    )

    assert result["unpublishable"] == 0, "испорченный код делал карточку непубликуемой"


@pytest.mark.django_db
def test_numeric_cells_still_parse_after_reading_the_sheet_as_text(world, seller):
    """Читаем лист текстом — значит числовые ячейки обязаны разбираться нашими парсерами."""
    from catalog.models import SupplierOffer

    result = run_catalog_import(
        _xlsx(
            [
                {
                    "Наименование": "Позиция с ценой",
                    "Артикул производителя": "P-1",
                    "Бренд": "NN",
                    "Цена": 1250.5,
                    "Валюта": "UZS",
                    "Наличие": "IN_STOCK",
                    "Мин. заказ": 12,
                }
            ]
        ),
        supplier_company_id=seller.id,
    )

    assert result["skipped"] == 0
    offer = SupplierOffer.objects.get(product__manufacturer_part_number="P-1")
    assert str(offer.base_price) == "1250.50"
    assert offer.min_order_qty == 12
