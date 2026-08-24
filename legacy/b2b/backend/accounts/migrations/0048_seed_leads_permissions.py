"""Доливка прав `leads.*` в уже заведённые пресеты операторских ролей.

Право появилось вместе с механикой «очередь лидов → назначение компании → приём» (паттерн
Salesforce Lead Queue). Пресеты уже посеяны миграцией 0027, поэтому новые коды доливаются, а
не переписываются: у операторов могли быть выданы собственные наборы, и затирать их нельзя.

Значения инлайнятся — миграции обязаны оставаться замороженными (не импортировать constants).
"""

from django.db import migrations

ADDITIONS = {
    "SUPER_OPERATOR": ["leads.view", "leads.route"],
    "SUPPORT": ["leads.view"],
    "MODERATOR": ["leads.view", "leads.route"],
}


def add_lead_permissions(apps, schema_editor):
    OperatorRole = apps.get_model("accounts", "OperatorRole")
    for code, codes in ADDITIONS.items():
        role = OperatorRole.objects.filter(code=code).first()
        if role is None:
            continue
        permissions = list(role.permissions or [])
        added = [code_ for code_ in codes if code_ not in permissions]
        if added:
            role.permissions = permissions + added
            role.save(update_fields=["permissions"])


def noop(apps, schema_editor):
    """Обратная миграция — no-op: снимать выданное право небезопасно (оператор мог получить
    его и вручную), а схема от этого не зависит."""


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0047_company_archive"),
    ]

    operations = [migrations.RunPython(add_lead_permissions, noop)]
