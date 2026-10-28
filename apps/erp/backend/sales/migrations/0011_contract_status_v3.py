"""D2-5, данные: статусы договора SPEC-v3 §2.4 — «Выставлен у оператора» и «Отклонён клиентом».

Договор подписывают вне платформы (у оператора ЭДО), в ERP остаётся фиксировать статусы и прикреплять скан. Новые
строки словаря добавляются идемпотентно (`get_or_create`): на чистой базе их уже посеял `0001_initial`. Обратного хода
нет: договор в новом статусе при откате остался бы без строки словаря.
"""

from django.db import migrations

NEW_STATUSES = [
    ("ISSUED_EXTERNAL", "Выставлен у оператора", 35),
    ("REJECTED", "Отклонён клиентом", 55),
]


def add_statuses(apps, schema_editor):
    ContractStatus = apps.get_model("sales", "ContractStatus")
    for code, name, sort_order in NEW_STATUSES:
        ContractStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": sort_order})


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0010_calc_line_visa_version"),
    ]

    operations = [
        migrations.RunPython(add_statuses, migrations.RunPython.noop),
    ]
