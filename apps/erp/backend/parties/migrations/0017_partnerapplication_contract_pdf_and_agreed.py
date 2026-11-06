# Generated manually for PART-PIPELINE-1

import core.storage
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parties", "0016_partnerapplication_country_and_reg"),
    ]

    operations = [
        migrations.AlterField(
            model_name="partnerapplication",
            name="status",
            field=models.CharField(
                choices=[
                    ("submitted", "Подана"),
                    ("contract_sent", "Договор отправлен"),
                    ("candidate_agreed", "Согласован кандидатом"),
                    ("approved", "Одобрена"),
                    ("rejected", "Отклонена"),
                ],
                default="submitted",
                max_length=20,
                verbose_name="Статус",
            ),
        ),
        migrations.AddField(
            model_name="partnerapplication",
            name="contract_pdf",
            field=models.FileField(
                blank=True,
                help_text="Файл проекта или согласованного/подписанного договора",
                null=True,
                storage=core.storage.get_private_storage,
                upload_to=core.storage.partner_application_contract_path,
                verbose_name="PDF договора",
            ),
        ),
        migrations.AddField(
            model_name="partnerapplication",
            name="contract_draft_sent_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Когда отправлен проект договора",
            ),
        ),
        migrations.AddField(
            model_name="partnerapplication",
            name="candidate_agreed_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Когда согласован кандидатом",
            ),
        ),
        migrations.AddField(
            model_name="partnerapplication",
            name="candidate_notes",
            field=models.TextField(
                blank=True,
                default="",
                max_length=1000,
                verbose_name="Комментарий кандидата",
            ),
        ),
    ]
