# FIX-33: плановое время следующей попытки доставки вебхука (по нему Beat находит зависшие PENDING)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integration', '0003_crm_client_mapping_handoff_deal'),
    ]

    operations = [
        migrations.AddField(
            model_name='integrationwebhookevent',
            name='next_attempt_at',
            field=models.DateTimeField(blank=True, help_text='Когда доставка должна повториться по сетке ретраев; пусто — отправлено, исчерпано или ещё не планировалось. Задача Beat подбирает PENDING, у которых этот срок давно прошёл (FIX-33).', null=True, verbose_name='Плановое время следующей попытки'),
        ),
        migrations.AddIndex(
            model_name='integrationwebhookevent',
            index=models.Index(fields=['status', 'next_attempt_at'], name='int_event_status_next_idx'),
        ),
    ]
