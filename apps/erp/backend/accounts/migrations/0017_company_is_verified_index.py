from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0016_alter_companymember_can_sell"),
    ]

    operations = [
        migrations.AlterField(
            model_name="company",
            name="is_verified",
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text="Компания прошла базовую проверку RailTech",
                verbose_name="Верифицирован",
            ),
        ),
    ]
