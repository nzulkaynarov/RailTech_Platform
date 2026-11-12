"""Узбекские и английские названия стран из CLDR (Babel); заполняются только пустые."""

from django.db import migrations


def fill(apps, schema_editor):
    from master_data.country_names import fill_all

    fill_all(apps.get_model("core", "Country").objects.all())


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_lookup_localized_names"),
    ]

    operations = [
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
