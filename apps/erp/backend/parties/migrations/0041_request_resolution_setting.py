from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("parties", "0040_ds1_contract_term")]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="request_resolution",
            field=models.CharField(
                choices=[("always", "always"), ("never", "never")],
                default="always",
                help_text="always — у каждой заявки; never — не нужна, заявка сразу в расчёт ответственному.",
                max_length=16,
                verbose_name="Резолюция перед расчётом",
            ),
        ),
    ]
