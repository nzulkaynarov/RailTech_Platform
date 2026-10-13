"""
Migration: Platform Admin model.

Выполняет:
  1) WorkspaceRole.applicable_to_types — M2M на CompanyType.
  2) Удаление поля SystemRole.is_staff_level.
  3) Очистка словаря SystemRole до канонических {ADMIN, USER}.
  4) Любой юзер, чья роль не ADMIN, получает role=USER.
  5) Удаление членств у всех юзеров с role=ADMIN (Platform Admin не привязан к компании).
  6) Посев WorkspaceRole по типам компаний.
"""
from django.db import migrations, models
from django.utils import timezone


SYSTEM_ROLES = [
    # (code, name, sort_order)
    ('ADMIN', 'Администратор платформы', 0),
    ('USER', 'Пользователь', 10),
]

# WorkspaceRole seed: (code, name, sort_order, applicable_company_type_codes)
# Пустой список applicable_to_types = универсальная роль (OWNER).
WORKSPACE_ROLES = [
    ('OWNER', 'Владелец', 0, []),
    ('PROCUREMENT_MANAGER', 'Снабженец', 10, ['CLIENT']),
    ('BUYER_MANAGER', 'Менеджер (Покупатель)', 20, ['CLIENT']),
    ('SALES_MANAGER', 'Продавец', 30, ['SUPPLIER']),
    ('LOGIST', 'Логист', 40, ['SUPPLIER']),
    ('CONTRACT_MANAGER', 'Договорник', 50, ['MANUFACTURER']),
    ('FOREIGN_TRADE_SPECIALIST', 'Специалист ВЭД', 60, ['MANUFACTURER']),
]


def forward(apps, schema_editor):
    SystemRole = apps.get_model('accounts', 'SystemRole')
    WorkspaceRole = apps.get_model('accounts', 'WorkspaceRole')
    CompanyType = apps.get_model('accounts', 'CompanyType')
    CustomUser = apps.get_model('accounts', 'CustomUser')
    CompanyMember = apps.get_model('accounts', 'CompanyMember')

    admin_role, _ = SystemRole.objects.update_or_create(
        code='ADMIN',
        defaults={'name': 'Администратор платформы', 'sort_order': 0, 'is_active': True},
    )
    user_role, _ = SystemRole.objects.update_or_create(
        code='USER',
        defaults={'name': 'Пользователь', 'sort_order': 10, 'is_active': True},
    )

    CustomUser.objects.exclude(role__code='ADMIN').exclude(role__isnull=True).update(role=user_role)
    CustomUser.objects.filter(role__isnull=True).update(role=user_role)

    admin_users = CustomUser.objects.filter(role=admin_role)
    admin_user_ids = list(admin_users.values_list('id', flat=True))
    CompanyMember.objects.filter(user_id__in=admin_user_ids).delete()

    SystemRole.objects.exclude(code__in=['ADMIN', 'USER']).delete()

    for code, name, order, applicable_codes in WORKSPACE_ROLES:
        wr, _ = WorkspaceRole.objects.update_or_create(
            code=code,
            defaults={'name': name, 'sort_order': order, 'is_active': True},
        )
        if applicable_codes:
            types = CompanyType.objects.filter(code__in=applicable_codes)
            wr.applicable_to_types.set(list(types))
        else:
            wr.applicable_to_types.clear()


def backward(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_companymember_can_buy_companymember_can_sell'),
    ]

    operations = [
        migrations.AddField(
            model_name='workspacerole',
            name='applicable_to_types',
            field=models.ManyToManyField(
                blank=True,
                help_text='Если пусто — роль универсальна. Если указаны типы — роль доступна только в компаниях этих типов.',
                related_name='workspace_roles',
                to='accounts.companytype',
                verbose_name='Применимо к типам компаний',
            ),
        ),
        migrations.RemoveField(
            model_name='systemrole',
            name='is_staff_level',
        ),
        migrations.RunPython(forward, backward),
    ]
