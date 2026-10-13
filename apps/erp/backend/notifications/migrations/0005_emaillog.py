"""EmailLog — audit log of outbound email for Unfold inspection."""
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0004_notification_audience'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('template', models.CharField(
                    db_index=True, max_length=100,
                    help_text="Код шаблона, например 'setup_password', 'kyc_verified'",
                    verbose_name='Шаблон',
                )),
                ('channel', models.CharField(
                    db_index=True, default='transactional', max_length=40,
                    help_text='Ключ из settings.EMAIL_CHANNELS: transactional / marketing / system',
                    verbose_name='Канал',
                )),
                ('subject', models.CharField(max_length=255, verbose_name='Тема')),
                ('from_email', models.CharField(max_length=255, verbose_name='Отправитель')),
                ('to_emails', models.JSONField(
                    default=list, verbose_name='Получатели',
                    help_text='Список email-адресов',
                )),
                ('body_text', models.TextField(blank=True, verbose_name='Текст (plain)')),
                ('body_html', models.TextField(blank=True, verbose_name='Тело (HTML)')),
                ('status', models.CharField(
                    choices=[('SENT', 'Отправлено'), ('FAILED', 'Ошибка')],
                    db_index=True, default='SENT', max_length=10,
                    verbose_name='Статус',
                )),
                ('error', models.TextField(
                    blank=True, verbose_name='Ошибка',
                    help_text='Текст исключения, если отправка не удалась',
                )),
                ('created_at', models.DateTimeField(
                    auto_now_add=True, db_index=True, verbose_name='Время',
                )),
                ('user', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name='email_logs',
                    to=settings.AUTH_USER_MODEL,
                    help_text='Основной адресат, если известен (для поиска по user__email)',
                    verbose_name='Пользователь',
                )),
            ],
            options={
                'verbose_name': 'Журнал email',
                'verbose_name_plural': 'Журнал email-рассылок',
                'ordering': ['-created_at'],
            },
        ),
    ]
