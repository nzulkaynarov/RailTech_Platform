"""M1-ERP-08 — право `finance.rates` (курс КП вручную с причиной, факт закупки для отклонения маржи).

Системные роли «Финансы» и «Руководитель» своей компании получают новый код (данные; схема не
меняется). `ensure_default_company_roles` и так догоняет системные роли до шаблона в коде — миграция
делает это сразу, без первого обращения к списку ролей.
"""

from django.db import migrations


def grant_finance_rates(apps, schema_editor):
    from core.seeds.backoffice_roles import grant_finance_rates as run

    run(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_backoffice_roles"),
    ]

    operations = [
        migrations.RunPython(grant_finance_rates, migrations.RunPython.noop),
    ]
