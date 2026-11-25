from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("parties", "0036_move_company_logos_to_private")]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="request_resolution",
            field=models.CharField(
                choices=[("always", "always"), ("cabinet_letters", "cabinet_letters"), ("never", "never")],
                default="always",
                help_text="always — у каждой заявки; cabinet_letters — только у заявок из Кабинета и писем; never — не нужна, заявка сразу в расчёт ответственному.",
                max_length=16,
                verbose_name="Резолюция перед расчётом",
            ),
        ),
    ]
