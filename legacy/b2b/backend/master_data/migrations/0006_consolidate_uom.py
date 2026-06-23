"""Consolidate the unit-of-measure справочник to one canonical UN/ECE Rec 20 set.

The table had TWO overlapping seed sources: a legacy set (core_seed: PCS/KG/M/T/L/HR
with full Russian names) AND the canonical UN/ECE Rec 20 set (migration 0005:
H87/KGM/MTR/TNE/LTR/HUR with abbreviated names). They duplicated the same physical
units with different codes + naming conventions — the "каша" the owner flagged.

This remaps every reference off the legacy duplicates onto their canonical UN/ECE
twin, then deletes the legacy rows. `Product.uom` is PROTECT, so we repoint it BEFORE
deleting; `QuoteItem.unit_code` is a plain code string, so we rewrite it too. Idempotent
and safe on empty data (prod). core_seed no longer seeds the legacy set.
"""

from django.db import migrations

# legacy code → canonical UN/ECE Rec 20 code (same physical unit)
_LEGACY_TO_CANONICAL = {
    "PCS": "H87",  # штука
    "KG": "KGM",  # килограмм
    "M": "MTR",  # метр
    "T": "TNE",  # тонна
    "L": "LTR",  # литр
    "HR": "HUR",  # час
}


def consolidate(apps, schema_editor):
    UnitOfMeasure = apps.get_model("master_data", "UnitOfMeasure")
    Product = apps.get_model("catalog", "Product")
    QuoteItem = apps.get_model("crm", "QuoteItem")

    for legacy_code, canonical_code in _LEGACY_TO_CANONICAL.items():
        legacy = UnitOfMeasure.objects.filter(code=legacy_code).first()
        canonical = UnitOfMeasure.objects.filter(code=canonical_code).first()
        if legacy is None or canonical is None:
            continue  # nothing to merge (already consolidated / not seeded)
        # Repoint the PROTECT FK first, else the delete below would fail.
        Product.objects.filter(uom=legacy).update(uom=canonical)
        # unit_code is a free code string on request lines — normalise it too.
        QuoteItem.objects.filter(unit_code=legacy_code).update(unit_code=canonical_code)
        legacy.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("master_data", "0005_seed_uom_unece"),
        ("catalog", "0010_product_owner_company"),
        ("crm", "0026_rfq_line_gost_drawing"),
    ]

    operations = [
        migrations.RunPython(consolidate, migrations.RunPython.noop),
    ]
