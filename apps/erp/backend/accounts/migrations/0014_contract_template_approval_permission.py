"""ДОК-10 — право `contract.approve_template` (утверждение шаблонов договоров и решение по отступлениям).

Системная роль «Руководитель» своей компании получает новый код (данные; схема не меняется), как в 0004, 0011 и 0012.
Сотрудники Платформы получают его провижинингом CRM из раздела каталога `eds.visa.legal` (держатель зоны «Право»).
"""

from django.db import migrations


def grant(apps, schema_editor):
    from core.seeds.backoffice_roles import grant_contract_template_approval as run

    run(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_k0_unset_client_on_suppliers"),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
