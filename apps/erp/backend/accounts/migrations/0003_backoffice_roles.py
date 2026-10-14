"""M1-ERP-05 — роли бэк-офиса: несколько ролей на сотрудника, код системной роли, новый каталог прав.

1. `CompanyMember.company_role` (FK, одна роль) → `company_roles` (M2M, права складываются);
   данные переносятся, FK снимается.
2. `CompanyRole.code` — стабильный код системной роли (`BackofficeRoleCode`), уникален в компании.
3. Своей компании сеются шесть системных ролей (BUSINESS §11 + Руководитель, Наблюдатель), коды
   прав до M1-ERP-05 переписываются (`payment.record` → `finance.payment`, …), участники старых
   шаблонов маркетплейса и участники без роли получают новые роли (`core.seeds.backoffice_roles`).
"""

import django.db.models.deletion
from django.db import migrations, models


def copy_single_role_to_set(apps, schema_editor):
    from core.seeds.backoffice_roles import copy_single_role_to_set as run

    run(apps, schema_editor)


def seed_backoffice_roles(apps, schema_editor):
    from core.seeds.backoffice_roles import seed_backoffice_roles as run

    run(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_initial"),
        ("parties", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="companymember",
            name="company_role",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="accounts.companyrole",
            ),
        ),
        migrations.AddField(
            model_name="companymember",
            name="company_roles",
            field=models.ManyToManyField(
                blank=True,
                help_text="Роли бэк-офиса; права складываются",
                related_name="members",
                to="accounts.companyrole",
                verbose_name="Роли (с правами)",
            ),
        ),
        migrations.RunPython(copy_single_role_to_set, migrations.RunPython.noop),
        migrations.RemoveField(model_name="companymember", name="company_role"),
        migrations.AddField(
            model_name="companyrole",
            name="code",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Код системной роли (BackofficeRoleCode); пусто у ролей, созданных компанией",
                max_length=40,
                verbose_name="Код",
            ),
        ),
        migrations.AlterField(
            model_name="companyrole",
            name="is_system",
            field=models.BooleanField(
                default=False,
                help_text="Роль-шаблон бэк-офиса — имя и права не меняются, удалить нельзя",
                verbose_name="Системная",
            ),
        ),
        migrations.AddConstraint(
            model_name="companyrole",
            constraint=models.UniqueConstraint(
                condition=models.Q(("code", ""), _negated=True),
                fields=("company", "code"),
                name="unique_role_code_per_company",
            ),
        ),
        migrations.RunPython(seed_backoffice_roles, migrations.RunPython.noop),
    ]
