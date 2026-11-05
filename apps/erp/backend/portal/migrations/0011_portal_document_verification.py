# Generated for SIGN-VERIFY-1 (ADR-0024 §6)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0010_portal_notice'),
    ]

    operations = [
        migrations.CreateModel(
            name='PortalDocumentVerification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_index=True, help_text='Случайный код с QR-кода на бланке или колонтитула', max_length=64, unique=True, verbose_name='Код проверки')),
                ('kind', models.CharField(help_text='letter_out, quote, contract, invoice, act, memo, other', max_length=32, verbose_name='Вид документа')),
                ('number', models.CharField(help_text='Регистрационный номер, например ИСХ-042/26', max_length=128, verbose_name='Номер документа')),
                ('date', models.DateField(verbose_name='Дата документа')),
                ('company_name', models.CharField(help_text='Наименование организации-эмитента', max_length=255, verbose_name='Организация')),
                ('signatory_name', models.CharField(max_length=255, verbose_name='ФИО подписанта')),
                ('signatory_position', models.CharField(blank=True, default='', max_length=255, verbose_name='Должность подписанта')),
                ('signatory_basis', models.TextField(blank=True, default='', help_text='на основании Устава / по доверенности № ...', verbose_name='Основание подписи')),
                ('status', models.CharField(choices=[('valid', 'Действует'), ('revoked', 'Отозван')], default='valid', max_length=16, verbose_name='Статус')),
                ('sha256_hash', models.CharField(blank=True, help_text='Контрольная сумма итогового PDF файла', max_length=64, null=True, verbose_name='SHA-256 хеш файла')),
                ('signed_at', models.DateTimeField(blank=True, null=True, verbose_name='Время подписания')),
                ('eds_document_id', models.UUIDField(blank=True, null=True, unique=True, verbose_name='ID документа в EDS')),
                ('revoked_at', models.DateTimeField(blank=True, null=True, verbose_name='Время отзыва')),
                ('revocation_reason', models.TextField(blank=True, null=True, verbose_name='Причина отзыва')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Проверка официального документа',
                'verbose_name_plural': 'Проверки официальных документов',
                'ordering': ['-signed_at', '-id'],
            },
        ),
    ]
