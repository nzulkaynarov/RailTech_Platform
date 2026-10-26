"""Волна 12 (EDS-03): одобрение КП директором — маршрут EDS; код права финального утверждения КП снят с ролей.

Данные, схема не меняется. Каталог после миграции — `core.seeds.backoffice_roles.CATALOG_0010`; коды вне него
снимаются с `CompanyRole.permissions` (системных и своих ролей). Обратного хода нет (код удалён из ERP).
"""

from django.db import migrations


def prune(apps, schema_editor):
    from core.seeds.backoffice_roles import prune_unknown_permissions

    prune_unknown_permissions(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_companymember_crm_granted_roles"),
    ]

    operations = [
        migrations.RunPython(prune, migrations.RunPython.noop),
    ]
