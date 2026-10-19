"""FIX-13 — покупательских аккаунтов в ERP нет: флаг `CompanyMember.can_buy` удалён (данные не переносятся)."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_finance_rates_permission"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="companymember",
            name="can_buy",
        ),
    ]
