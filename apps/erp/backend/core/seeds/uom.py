"""UN/ECE Recommendation 20 units of measure seed."""

UOM_CODES = [
    ("H87", "шт.", 10),  # piece
    ("SET", "компл.", 20),  # set
    ("PR", "пара", 30),  # pair
    ("MTR", "м", 40),  # metre
    ("KMT", "км", 50),  # kilometre
    ("CMT", "см", 60),  # centimetre
    ("MMT", "мм", 70),  # millimetre
    ("MTK", "м²", 80),  # square metre
    ("MTQ", "м³", 90),  # cubic metre
    ("KGM", "кг", 100),  # kilogram
    ("GRM", "г", 110),  # gram
    ("TNE", "т", 120),  # tonne (metric ton)
    ("LTR", "л", 130),  # litre
    ("MLT", "мл", 140),  # millilitre
    ("XPK", "упак.", 150),  # package
    ("HUR", "час", 160),  # hour
    ("DAY", "сутки", 170),  # day
]


def seed_uom(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        UnitOfMeasure = apps.get_model("core", "UnitOfMeasure")
    except LookupError:
        UnitOfMeasure = apps.get_model("master_data", "UnitOfMeasure")

    for code, name, sort_order in UOM_CODES:
        UnitOfMeasure.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )
