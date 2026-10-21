from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0003_aicall'),
    ]

    operations = [
        migrations.AddField(
            model_name='aijob',
            name='applied_rows',
            field=models.PositiveIntegerField(blank=True, help_text='FIX-67b: сколько строк КП записал этот job. Не NULL — результат уже применён, повторный запуск той же задачи (ретрай, повторная доставка) строки не дублирует.', null=True, verbose_name='Записано строк'),
        ),
    ]
