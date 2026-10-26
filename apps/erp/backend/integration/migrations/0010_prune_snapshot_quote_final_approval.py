"""Волна 12 (EDS-03): код права финального утверждения КП снят и со снимков провижининга CRM.

Снимок (`CrmUserMapping.provision_snapshot`) применяется к своей компании, созданной позже провижининга: без чистки
снятый код вернулся бы роли «CRM Sync». Данные, схема не меняется; обратного хода нет.
"""

from django.db import migrations


def prune(apps, schema_editor):
    from core.seeds.backoffice_roles import prune_unknown_snapshot_permissions

    prune_unknown_snapshot_permissions(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("integration", "0009_credential_slot_webhook_previous"),
    ]

    operations = [
        migrations.RunPython(prune, migrations.RunPython.noop),
    ]
