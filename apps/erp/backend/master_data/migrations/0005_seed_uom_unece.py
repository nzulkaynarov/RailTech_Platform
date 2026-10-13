"""Seed UnitOfMeasure with UN/ECE Recommendation 20 codes — idempotent data migration.

UN/ECE Rec 20 is the international standard for units of measure in trade (the same
code list UBL/Peppol use in Quantity@unitCode). This is the source of truth for unit
codes; the AI заявка extractor maps any client text («шт./дона/pcs», «т/тн/тонн») to
ONE of these codes, and code validates the AI's output against this table.

Rule 1 (CLAUDE.md): business lookups = data migrations, not hardcoded Python dicts.
Reverse: no-op (never cascade-delete seeded lookups). The table is admin-editable —
add more UN/ECE codes via the admin or a new migration as needed.
"""
from django.db import migrations

# (code = UN/ECE Rec 20, display name, sort). Only codes verified against the
# standard. Extend via admin / a follow-up migration when new units appear.
UOM_CODES = [
    ("H87", "шт.", 10),     # piece
    ("SET", "компл.", 20),  # set
    ("PR", "пара", 30),     # pair
    ("MTR", "м", 40),       # metre
    ("KMT", "км", 50),      # kilometre
    ("CMT", "см", 60),      # centimetre
    ("MMT", "мм", 70),      # millimetre
    ("MTK", "м²", 80),      # square metre
    ("MTQ", "м³", 90),      # cubic metre
    ("KGM", "кг", 100),     # kilogram
    ("GRM", "г", 110),      # gram
    ("TNE", "т", 120),      # tonne (metric ton)
    ("LTR", "л", 130),      # litre
    ("MLT", "мл", 140),     # millilitre
    ("XPK", "упак.", 150),  # package
    ("HUR", "час", 160),    # hour
    ("DAY", "сутки", 170),  # day
]


def seed_uom(apps, schema_editor):
    UnitOfMeasure = apps.get_model("master_data", "UnitOfMeasure")
    for code, name, sort_order in UOM_CODES:
        UnitOfMeasure.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("master_data", "0004_dedupe_uom_stubs"),
    ]

    operations = [
        migrations.RunPython(seed_uom, noop),
    ]
