"""N1 — configurable document numbering scheme.

Adds `DocumentNumberingScheme` (token-mask numbering config, one row per company +
a platform default row = the historical format at ZERO visual diff) and widens the
`DocumentSequence` counter scope from `year` to a `period` key (never/yearly/monthly).

Ordering is deliberate:
  * period is BACKFILLED (period = str(year)) BEFORE the new (company, doc_type, period)
    unique constraint is added — otherwise existing rows would all carry period="" and
    collide.
  * the platform default scheme is seeded via get_or_create (idempotent, reverse deletes
    it) so a fresh migrate reproduces `{prefix}{type}-{YYYY}-{seq}` with no code change.
"""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

# The historical hardcoded format, seeded as the platform default (zero visual diff).
_DEFAULT_PATTERN = "{prefix}{type}-{YYYY}-{seq}"
_DEFAULT_PADDING = 5
_DEFAULT_RESET_PERIOD = "yearly"
_DEFAULT_START_VALUE = 0


def backfill_periods(apps, schema_editor):
    DocumentSequence = apps.get_model("crm", "DocumentSequence")
    for seq in DocumentSequence.objects.filter(period=""):
        # Yearly period key == str(year) — existing counters keep working unchanged.
        seq.period = str(seq.year)
        seq.save(update_fields=["period"])


def seed_platform_scheme(apps, schema_editor):
    DocumentNumberingScheme = apps.get_model("crm", "DocumentNumberingScheme")
    DocumentNumberingScheme.objects.get_or_create(
        company=None,
        defaults={
            "pattern": _DEFAULT_PATTERN,
            "padding": _DEFAULT_PADDING,
            "reset_period": _DEFAULT_RESET_PERIOD,
            "start_value": _DEFAULT_START_VALUE,
        },
    )


def unseed_platform_scheme(apps, schema_editor):
    DocumentNumberingScheme = apps.get_model("crm", "DocumentNumberingScheme")
    DocumentNumberingScheme.objects.filter(company__isnull=True).delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0039_alter_customuser_totp_secret'),
        ('crm', '0072_declutter_sample_template_bodies'),
    ]

    operations = [
        migrations.CreateModel(
            name='DocumentNumberingScheme',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pattern', models.CharField(default='{prefix}{type}-{YYYY}-{seq}', help_text='Токены: {prefix} {type} {YYYY} {YY} {MM} {seq}. Обязателен {seq}.', max_length=128, verbose_name='Маска номера')),
                ('padding', models.PositiveSmallIntegerField(default=5, help_text='Сколько цифр в {seq} с ведущими нулями (напр. 5 → 00001)', validators=[django.core.validators.MinValueValidator(1)], verbose_name='Ширина счётчика')),
                ('reset_period', models.CharField(choices=[('never', 'Никогда'), ('yearly', 'Ежегодно'), ('monthly', 'Ежемесячно')], default='yearly', help_text='Когда счётчик обнуляется: никогда / ежегодно / ежемесячно', max_length=16, verbose_name='Период сброса')),
                ('start_value', models.PositiveIntegerField(default=0, help_text='Первый номер = start_value + 1 (по умолчанию 0 → первый номер 1)', verbose_name='Стартовое значение')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлён')),
            ],
            options={
                'verbose_name': 'Схема нумерации документов',
                'verbose_name_plural': 'Схемы нумерации документов',
            },
        ),
        migrations.AddField(
            model_name='documentnumberingscheme',
            name='company',
            field=models.OneToOneField(blank=True, help_text='Компания-владелец схемы; NULL — платформенная схема по умолчанию', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='numbering_scheme', to='accounts.company', verbose_name='Компания'),
        ),
        migrations.RunPython(seed_platform_scheme, unseed_platform_scheme),
        # ── DocumentSequence: year → period scope ──────────────────────────────────
        migrations.RemoveConstraint(
            model_name='documentsequence',
            name='uniq_document_sequence_company_type_year',
        ),
        migrations.AddField(
            model_name='documentsequence',
            name='period',
            field=models.CharField(blank=True, default='', help_text='Ключ периода счётчика: «ALL» (без сброса), «2026» (год) или «2026-07» (месяц)', max_length=16, verbose_name='Период сброса'),
        ),
        migrations.RunPython(backfill_periods, noop),
        migrations.AddConstraint(
            model_name='documentsequence',
            constraint=models.UniqueConstraint(fields=('company', 'doc_type', 'period'), name='uniq_document_sequence_company_type_period'),
        ),
    ]
