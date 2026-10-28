"""D2-1 — права виз строки расчёта `quote.visa_goods` и `quote.visa_services` (ADR-0012 п. 6).

Системные роли «Расчёт» и «Руководитель» своей компании получают оба кода (данные; схема не меняется). Сотрудники
Платформы получают их провижинингом CRM из разделов `erp.calc.goods` и `erp.calc.services`.
"""

from django.db import migrations


def grant_calc_visas(apps, schema_editor):
    from core.seeds.backoffice_roles import grant_calc_visas as run

    run(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_prune_quote_final_approval"),
    ]

    operations = [
        migrations.RunPython(grant_calc_visas, migrations.RunPython.noop),
    ]
