"""Notification audience — разделение USER vs PLATFORM_ADMIN каналов."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0003_alter_notification_created_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='audience',
            field=models.CharField(
                choices=[('USER', 'Пользователь'), ('PLATFORM_ADMIN', 'Platform Admin')],
                db_index=True,
                default='USER',
                help_text=(
                    'USER — персональное или broadcast для обычных пользователей. '
                    'PLATFORM_ADMIN — операционные алёрты платформы (видит только admin).'
                ),
                max_length=20,
                verbose_name='Аудитория',
            ),
        ),
    ]
