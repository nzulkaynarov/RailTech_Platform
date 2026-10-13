"""Remove duplicate country stubs with a wrong flat VAT — idempotent.

Prod had two overlapping country sets (checkup 2026-06-09): leftover 3-letter
seed stubs (GER/RUS/CHN/KAZ/UZB, English names, no alpha-2, flat 12% VAT) next to
the canonical ISO alpha-2 rows (DE/RU/CN/KZ/UZ with real rates). Selecting the
stub yielded the wrong VAT in price calculations.

This remaps every FK that points at a stub onto its canonical twin, then deletes
the stub. Remap-before-delete is required because Quote.tax_country is PROTECT.
Operates only on rows that exist, so it's safe to run on any DB (incl. a fresh
one where no stubs were ever seeded). Reverse is a no-op — a merge can't be undone.
"""

from django.db import migrations

# stub code → canonical (ISO alpha-2) code
STUB_TO_CANONICAL = {
    "GER": "DE",
    "RUS": "RU",
    "CHN": "CN",
    "KAZ": "KZ",
    "UZB": "UZ",
}


def dedupe_country_stubs(apps, schema_editor):
    Country = apps.get_model("master_data", "Country")
    for stub_code, canonical_code in STUB_TO_CANONICAL.items():
        stub = Country.objects.filter(code=stub_code).first()
        canonical = Country.objects.filter(code=canonical_code).first()
        if not stub or not canonical or stub.pk == canonical.pk:
            continue
        # Repoint every FK to Country (Company.country, Quote.tax_country, catalog
        # origin, …) from the stub to the canonical row. We scan forward FK fields
        # on every model rather than Country._meta.related_objects because
        # related_name="+" FKs (Quote.tax_country) are absent from related_objects,
        # and Quote.tax_country is PROTECT — missing it would block the delete.
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if getattr(field, "many_to_one", False) and field.related_model is Country:
                    model._default_manager.filter(**{field.name: stub}).update(**{field.name: canonical})
        stub.delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("master_data", "0002_alter_country_alpha2_alter_country_code_and_more"),
        ("accounts", "0013_backfill_company_is_verified"),
        ("crm", "0013_alter_deal_created_at"),
        ("catalog", "0007_manufacturer_product_brand"),
    ]

    operations = [
        migrations.RunPython(dedupe_country_stubs, reverse_code=noop),
    ]
