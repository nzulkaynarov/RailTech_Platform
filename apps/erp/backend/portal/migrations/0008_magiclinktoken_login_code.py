from django.db import migrations, models


class Migration(migrations.Migration):
    """B-MAIL-1: код входа рядом со ссылкой — хеш кода и счётчик неверных попыток."""

    dependencies = [
        ("portal", "0007_quote_comment"),
    ]

    operations = [
        migrations.AddField(
            model_name="magiclinktoken",
            name="code_hash",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Сырой 6-значный код есть только в письме; пусто — у записи нет кода",
                max_length=64,
                verbose_name="HMAC-SHA256 кода входа",
            ),
        ),
        migrations.AddField(
            model_name="magiclinktoken",
            name="code_attempts",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Неверных попыток кода"),
        ),
    ]
