"""Сроки в настройках компании (задача «Н3c», аудит захардкоженного 2026-11-13): «цена истекает за N дней» и пауза
между напоминаниями об акте; начальные значения — прежние константы (14 дней, 24 часа)."""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parties", "0023_company_bank_accounts"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="act_reminder_hours",
            field=models.PositiveSmallIntegerField(
                default=24,
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(720)],
                verbose_name="Пауза между напоминаниями об акте (часов)",
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="offer_expiring_days",
            field=models.PositiveSmallIntegerField(
                default=14,
                help_text="Цена поставщика со сроком действия ближе этого числа дней помечается «истекает».",
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(90)],
                verbose_name="Предупреждать об окончании цены (дней)",
            ),
        ),
    ]
