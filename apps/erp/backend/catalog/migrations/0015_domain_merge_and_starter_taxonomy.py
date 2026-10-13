"""N1 (spec-nomenclature-audit-2026-08-04): данные, из-за которых «Номенклатура» была тупиком.

1) Слияние доменов-двойников. Миграция `core/0002` сеяла домен `GENERAL`, dev-команда
   `core_seed` — `GENERAL_GOODS`; оба жили активными, пользователь видел в селекте «Общие
   товары» И «Общие промышленные товары», а `completeness.py` знал только `GENERAL_GOODS`.
   Канон — `GENERAL_GOODS` (по нему считается полнота). FK переезжают, `GENERAL`
   деактивируется, но НЕ удаляется: на него могут смотреть исторические строки чужих баз.

2) Стартовая таксономия. Категория обязательна для публикации ЛЮБОЙ карточки, группа
   оборудования — для ж/д, а обе таблицы на проде были ПУСТЫ, и писать в них может только
   платформа: продавец упирался в обязательное поле с «Нет данных» внутри. Паттерн Amazon
   browse tree / Odoo: таксономия платформенная — значит, платформа и поставляет её
   заполненной с первого дня. Дерево групп — из докстринга модели EquipmentGroup (эскиз
   задумки), категории — по трём доменам. Оператор дальше расширяет через #admin-categories.

Идемпотентно (get_or_create по имени), reverse — no-op (Rule 1).
"""

from django.db import migrations

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

# (имя, родитель или None) — порядок важен: родители раньше детей.
EQUIPMENT_GROUPS = [
    ("Подвижной состав", None),
    ("Локомотивы", "Подвижной состав"),
    ("Тепловозы", "Локомотивы"),
    ("Электровозы", "Локомотивы"),
    ("Вагоны", "Подвижной состав"),
    ("Грузовые вагоны", "Вагоны"),
    ("Пассажирские вагоны", "Вагоны"),
    ("Путевая техника", None),
    ("Дефектоскопы", "Путевая техника"),
    ("Шпалоподбивочные машины", "Путевая техника"),
    ("Инфраструктура", None),
    ("Стрелочные переводы", "Инфраструктура"),
    ("Контактная сеть", "Инфраструктура"),
    ("СЦБ и связь", "Инфраструктура"),
]


def merge_general_domains(apps, schema_editor):
    DomainType = apps.get_model("catalog", "DomainType")
    Product = apps.get_model("catalog", "Product")
    Category = apps.get_model("catalog", "Category")

    general = DomainType.objects.filter(code="GENERAL").first()
    canonical, _created = DomainType.objects.get_or_create(
        code="GENERAL_GOODS",
        defaults={"name": "Общие промышленные товары", "sku_prefix": "ОТ", "sort_order": 20},
    )
    if general is None:
        return
    Product.objects.filter(domain_type=general).update(domain_type=canonical)
    Category.objects.filter(domain_type=general).update(domain_type=canonical)
    general.is_active = False
    general.save(update_fields=["is_active"])


def seed_starter_taxonomy(apps, schema_editor):
    DomainType = apps.get_model("catalog", "DomainType")
    Category = apps.get_model("catalog", "Category")
    EquipmentGroup = apps.get_model("catalog", "EquipmentGroup")

    for domain_code, names in CATEGORIES.items():
        domain = DomainType.objects.filter(code=domain_code).first()
        if domain is None:  # домен создают более ранние сиды; без него категории бессмысленны
            continue
        for index, name in enumerate(names):
            Category.objects.get_or_create(
                name=name, domain_type=domain, parent=None, defaults={"sort_order": (index + 1) * 10}
            )

    # Историческая модель не имеет кастомного save() — cached_path проставляем руками.
    created_groups = {}
    for index, (name, parent_name) in enumerate(EQUIPMENT_GROUPS):
        parent = created_groups.get(parent_name)
        group, _created = EquipmentGroup.objects.get_or_create(
            name=name,
            parent=parent,
            defaults={
                "sort_order": (index + 1) * 10,
                "cached_path": f"{parent.cached_path} / {name}" if parent else name,
            },
        )
        created_groups[name] = group


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0014_backfill_product_status"),
        # Домены сеет core/0002 — без этой зависимости на свежей базе таксономия
        # выполнилась бы раньше доменов и молча не посеяла бы ничего.
        ("core", "0002_seed_enterprise_lookups"),
    ]

    operations = [
        migrations.RunPython(merge_general_domains, migrations.RunPython.noop),
        migrations.RunPython(seed_starter_taxonomy, migrations.RunPython.noop),
    ]
