"""Remove duplicate UnitOfMeasure stubs — idempotent.

Prod had two overlapping UoM sets: the canonical Latin/ISO codes the catalog
import and seed use (KG, SET, M, T, PCS, L, HR — Product.uom references PCS) next
to leftover Cyrillic-code duplicates with the SAME display name (кг, компл, м, т,
шт). Selecting the stub yielded a second "Штука"/"Килограмм"/… row in the unit
dropdown.

This remaps every FK that points at a stub onto its canonical Latin twin, then
deletes the stub. Remap-before-delete is required because Product.uom is PROTECT.
Operates only on rows that exist (safe on a fresh DB). Reverse is a no-op — a merge
can't be undone. Mirrors 0003_dedupe_country_stubs.
"""

from django.db import migrations

# cyrillic stub code → canonical Latin code (same display name)
STUB_TO_CANONICAL = {
    "кг": "KG",
    "компл": "SET",
    "м": "M",
    "т": "T",
    "шт": "PCS",
}


def dedupe_uom_stubs(apps, schema_editor):
    UnitOfMeasure = apps.get_model("master_data", "UnitOfMeasure")
    for stub_code, canonical_code in STUB_TO_CANONICAL.items():
        stub = UnitOfMeasure.objects.filter(code=stub_code).first()
        canonical = UnitOfMeasure.objects.filter(code=canonical_code).first()
        if not stub or not canonical or stub.pk == canonical.pk:
            continue
        # Repoint every FK to UnitOfMeasure (Product.uom, …) from the stub to the
        # canonical row. Scan forward FK fields on every model rather than
        # related_objects so related_name="+" FKs aren't missed, and because
        # Product.uom is PROTECT — a missed ref would block the delete.
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if getattr(field, "many_to_one", False) and field.related_model is UnitOfMeasure:
                    model._default_manager.filter(**{field.name: stub}).update(**{field.name: canonical})
        stub.delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("master_data", "0003_dedupe_country_stubs"),
        ("catalog", "0007_manufacturer_product_brand"),
    ]

    operations = [
        migrations.RunPython(dedupe_uom_stubs, reverse_code=noop),
    ]
