"""D2-4 — право `finance.view` (чтение счетов и оплат без права выставлять и фиксировать).

Системные роли «Финансы» и «Руководитель» своей компании получают новый код (данные; схема не меняется), как в 0004.
Директор и менеджер Платформы читают доску «Счета и оплаты» по этому праву: каталог ролей даёт его уровню `read`.
"""

from django.db import migrations


def grant_finance_view(apps, schema_editor):
    from core.seeds.backoffice_roles import grant_finance_view as run

    run(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_prune_quote_final_approval"),
    ]

    operations = [
        migrations.RunPython(grant_finance_view, migrations.RunPython.noop),
    ]
