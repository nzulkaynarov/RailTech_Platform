"""Шаблон каталожного импорта: канонические заголовки + endpoint выгрузки .xlsx.

Вынесено из views_imports.py в волну R5b — тот перерос предел в 500 строк. Прежние точки
импорта живы: views_imports.py и фасад sourcing/views.py ре-экспортируют всё отсюда.
"""

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

# Exact headers the import engine recognizes (see sourcing/catalog_import.py).
# «Категория», «Код ТН ВЭД» и «Направление» — не украшение шапки: без них порог публикации
# (catalog/completeness.py) не пропускает НИ ОДНУ загруженную карточку, и прайс-лист на 3000
# строк превращался в 3000 черновиков, каждый из которых надо было дозаполнять руками.
CATALOG_TEMPLATE_HEADERS = [
    "Наименование",
    "Бренд",
    "Артикул производителя",
    "ГОСТ / Чертёж",
    "Артикул поставщика",
    "Описание",
    "Категория",
    "Код ТН ВЭД",
    "Направление",
    "Ед. изм.",
    "Цена",
    "Валюта",
    "Наличие",
    "Срок поставки",
    "Мин. заказ",
]
#: Пример строки. Категория / направление / код ТН ВЭД оставлены ПУСТЫМИ намеренно: подставить
#: сюда придуманные значения значит выдать пример, который сам же не импортируется (категория
#: и направление сверяются со справочником). Реальные значения подставляет `_template_example`
#: из живой базы — как и коды валют/наличия на листе справочников.
CATALOG_TEMPLATE_EXAMPLE = [
    "Тормозная колодка",
    "Knorr-Bremse",
    "KB-100",
    "ГОСТ 1234-89",
    "SUP-55",
    "Композитная тормозная колодка",
    "",
    "",
    "",
    "шт",
    "150.50",
    "UZS",
    "IN_STOCK",
    "14-21 дн.",
    "5",
]


def _template_example(categories, domains) -> list:
    """Пример строки с ЖИВЫМИ значениями справочников — чтобы его можно было импортировать as-is.

    Код ТН ВЭД берётся ПОДСКАЗКОЙ по наименованию примера: так в шаблоне оказывается настоящий
    код из редакции ГТК, а не десять правдоподобных цифр (`catalog/hs_suggest.py`: придуманный
    код ТН ВЭД хуже отсутствующего). Классификатор не загружен — ячейка остаётся пустой.
    """
    from catalog.hs_suggest import suggest_hs_codes

    example = list(CATALOG_TEMPLATE_EXAMPLE)
    example_name = example[CATALOG_TEMPLATE_HEADERS.index("Наименование")]
    goods = next((domain for domain in domains if domain.code in ("GENERAL_GOODS", "GOODS")), None)
    domain = goods or (domains[0] if domains else None)
    suggestions = suggest_hs_codes(example_name, limit=1)

    example[CATALOG_TEMPLATE_HEADERS.index("Категория")] = categories[0].name if categories else ""
    example[CATALOG_TEMPLATE_HEADERS.index("Направление")] = domain.name if domain else ""
    example[CATALOG_TEMPLATE_HEADERS.index("Код ТН ВЭД")] = suggestions[0]["code"] if suggestions else ""
    return example


@extend_schema(
    summary="Download catalog import template",
    description=(
        "Returns an .xlsx with the exact headers the importer recognizes, one "
        "example row, and a reference sheet of allowed currency / stock / unit "
        "codes (read live from the database)."
    ),
    responses={200: OpenApiResponse(description="XLSX template")},
    tags=["Sourcing"],
)
class CatalogTemplateView(APIView):
    """Seller-facing catalog import template (true-PIM headers + allowed codes)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from openpyxl import Workbook

        from catalog.models import Category, DomainType, StockStatus
        from master_data.models import Currency, UnitOfMeasure

        categories = list(Category.objects.filter(is_active=True).order_by("sort_order", "name"))
        domains = list(DomainType.objects.all().order_by("sort_order", "code"))

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Товары"
        sheet.append(CATALOG_TEMPLATE_HEADERS)
        sheet.append(_template_example(categories, domains))

        reference = workbook.create_sheet("Справочники (коды)")
        reference.append(["Тип", "Код", "Название"])
        for currency in Currency.objects.all().order_by("code"):
            reference.append(["Валюта", currency.code, currency.name])
        for stock in StockStatus.objects.all().order_by("code"):
            reference.append(["Наличие", stock.code, stock.name])
        for unit in UnitOfMeasure.objects.all().order_by("code"):
            reference.append(["Ед. изм.", unit.code, unit.name])
        # Категория и направление сверяются со справочником построчно: продавец должен видеть
        # ДОПУСТИМЫЕ значения здесь же, иначе первая же загрузка вернёт UNKNOWN_CATEGORY.
        for domain in domains:
            reference.append(["Направление", domain.code, domain.name])
        for category in categories:
            reference.append(["Категория", "", category.name])

        response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="catalog_template.xlsx"'
        workbook.save(response)
        return response
