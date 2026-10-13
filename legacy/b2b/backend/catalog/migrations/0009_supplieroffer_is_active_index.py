from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0008_dedupe_taxonomy"),
    ]

    operations = [
        migrations.AlterField(
            model_name="supplieroffer",
            name="is_active",
            field=models.BooleanField(
                default=True,
                db_index=True,
                help_text="Неактивные офферы не отображаются при выборе",
                verbose_name="Активен",
            ),
        ),
    ]
