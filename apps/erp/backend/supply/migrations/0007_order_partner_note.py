# СЦ-10: комментарий партнёру отдельно от внутреннего примечания заказа.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("supply", "0006_decimal_quantity"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplierorder",
            name="partner_note",
            field=models.TextField(blank=True, default="", verbose_name="Комментарий партнёру"),
        ),
    ]
