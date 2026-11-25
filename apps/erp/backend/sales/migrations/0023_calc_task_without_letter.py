from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0022_dok10_contract_template_approval")]

    operations = [
        migrations.AlterField(
            model_name="calctask",
            name="eds_letter_id",
            field=models.UUIDField(
                blank=True,
                help_text="Входящее письмо EDS, на которое наложена резолюция (одно задание на письмо); пусто — расчёт поставлен без резолюции (РЕЗ-1)",
                null=True,
                unique=True,
                verbose_name="Письмо EDS",
            ),
        ),
        migrations.AddField(
            model_name="calctask",
            name="request_file_pending",
            field=models.BooleanField(
                default=False,
                help_text="РЕЗ-1: расчёт без резолюции ждёт файл письма клиента из EDS; сбросится, когда файл пришёл или не придёт",
                verbose_name="Файл заявки загружается",
            ),
        ),
    ]
