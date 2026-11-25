from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("parties", "0036_move_company_logos_to_private")]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="request_resolution",
            field=models.CharField(
                choices=[("always", "always"), ("client_own", "client_own"), ("never", "never")],
                default="always",
                help_text="always — у каждой заявки; client_own — только у заявок, которые клиент подал сам (Кабинет, бот, письмо); never — не нужна, заявка сразу в расчёт ответственному.",
                max_length=16,
                verbose_name="Резолюция перед расчётом",
            ),
        ),
    ]
