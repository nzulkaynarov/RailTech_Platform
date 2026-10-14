"""Catalog lookups and starter taxonomy seed."""

PRODUCT_STATUSES = [
    ("DRAFT", "Черновик", 10),
    ("PUBLISHED", "Опубликован", 20),
    ("ARCHIVED", "Архивирован", 30),
]

STOCK_STATUSES = [
    ("IN_STOCK", "В наличии", 10),
    ("EXPECTED", "Ожидается", 20),
    ("ON_ORDER", "Под заказ", 30),
    ("OUT_OF_STOCK", "Нет в наличии", 40),
]

DOMAIN_TYPES = [
    ("GENERAL_GOODS", "Общие промышленные товары", "ОТ", 10),
    ("RAILWAY_MACHINERY", "Железнодорожная техника", "RW", 20),
    ("SERVICES", "Услуги (логистика, ремонт)", "УС", 30),
]

CATEGORIES = {
    "RAILWAY_MACHINERY": [
        "Подвижной состав и части",
        "Верхнее строение пути",
        "Скрепления и крепёж",
        "Колёсные пары и буксы",
        "Тормозное оборудование",
        "Электрооборудование и СЦБ",
        "Дизельные и силовые агрегаты",
        "Гидравлика и пневматика",
        "Подшипники",
        "Инструмент и оснастка",
    ],
    "GENERAL_GOODS": [
        "Металлопрокат",
        "Метизы и крепёж",
        "Электротехника",
        "Инструмент",
        "Спецодежда и СИЗ",
        "Строительные материалы",
        "ГСМ и техническая химия",
    ],
    "SERVICES": [
        "Логистика и перевозка",
        "Ремонт и обслуживание",
        "Монтаж и пусконаладка",
        "Экспертиза и сертификация",
    ],
}


def seed_catalog_lookups(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    ProductStatus = apps.get_model("catalog", "ProductStatus")
    StockStatus = apps.get_model("catalog", "StockStatus")
    DomainType = apps.get_model("catalog", "DomainType")
    Category = apps.get_model("catalog", "Category")

    for code, name, sort_order in PRODUCT_STATUSES:
        ProductStatus.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )

    for code, name, sort_order in STOCK_STATUSES:
        StockStatus.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )

    for code, name, prefix, sort_order in DOMAIN_TYPES:
        domain, _ = DomainType.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "sku_prefix": prefix,
                "sort_order": sort_order,
                "is_active": True,
            },
        )
        for index, cat_name in enumerate(CATEGORIES.get(code, [])):
            Category.objects.get_or_create(
                name=cat_name,
                domain_type=domain,
                parent=None,
                defaults={"sort_order": (index + 1) * 10, "is_active": True},
            )
