from decimal import Decimal

from django.db import migrations, models


def fill_unset_margin(apps, schema_editor):
    """РАСЧ-1: «не задано» больше не значит наценку 0 % — у компаний без своей наценки ставится умолчание 20 %."""
    apps.get_model("parties", "CompanySettings").objects.filter(default_margin_percent__isnull=True).update(
        default_margin_percent=Decimal("20.00")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("parties", "0046_test1_company_is_test"),
    ]

    operations = [
        migrations.AlterField(
            model_name="companysettings",
            name="default_margin_percent",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                default=Decimal("20.00"),
                help_text="Наценка на себестоимость, подставляемая в новый КП и в цену клиенту строки расчёта (РАСЧ-1); по умолчанию 20 %",
                max_digits=6,
                null=True,
                verbose_name="Маржа по умолчанию (%)",
            ),
        ),
        migrations.RunPython(fill_unset_margin, migrations.RunPython.noop),
    ]
