# Generated manually for COUNTRY-MASK-1

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        ("parties", "0015_partnerapplication_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="partnerapplication",
            name="country",
            field=models.ForeignKey(
                blank=True,
                help_text="Страна регистрации кандидата (справочник ISO 3166-1)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="core.country",
                verbose_name="Страна регистрации",
            ),
        ),
        migrations.AddField(
            model_name="partnerapplication",
            name="registration_number",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Регистрационный номер / Tax ID для нерезидентов",
                max_length=64,
                verbose_name="Рег. номер (нерезидент)",
            ),
        ),
        migrations.AlterField(
            model_name="partnerapplication",
            name="inn",
            field=models.CharField(
                blank=True,
                default="",
                help_text="ИНН для резидентов Узбекистана",
                max_length=32,
                verbose_name="ИНН",
            ),
        ),
    ]
