"""Sync migration state with Deal.created_at db_index=True (pre-existing model drift)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0012_deal_composite_indexes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="deal",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Дата создания"),
        ),
    ]
