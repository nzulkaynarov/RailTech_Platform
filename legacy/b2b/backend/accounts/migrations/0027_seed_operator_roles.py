"""Seed the five platform-operator sub-roles (ADR-0004 G1) + map existing operators.

SUPER_OPERATOR is the immutable full-rights role (= the legacy single ADMIN). Every existing
platform operator (SystemRole.ADMIN, no active membership) is mapped to SUPER_OPERATOR so the
granular split is backward-compatible — nobody loses access. Values are inlined (migrations
must stay frozen — do NOT import accounts.constants). See Docs/adr/0004-three-admin-planes-core.md.
"""

from django.db import migrations

ALL = [
    "users.view", "users.manage",
    "companies.view", "companies.manage",
    "kyc.view", "kyc.verify",
    "billing.view", "billing.manage",
    "moderation.role_applications", "moderation.force_override",
    "platform.settings", "operators.manage",
]

# code → (name, permissions, is_system, description)
TEMPLATES = {
    "SUPER_OPERATOR": (
        "Супероператор", ALL, True,
        "Полный доступ ко всем функциям платформенного оператора (= прежний единый администратор).",
    ),
    "SUPPORT": (
        "Поддержка",
        ["users.view", "companies.view", "kyc.view", "billing.view"], False,
        "Только просмотр пользователей, компаний, KYC и биллинга для триажа обращений.",
    ),
    "KYC_OFFICER": (
        "Офицер KYC",
        ["users.view", "companies.view", "kyc.view", "kyc.verify"], False,
        "Проверка и верификация KYC (L1→L3), загрузка документов.",
    ),
    "BILLING_OPERATOR": (
        "Оператор биллинга",
        ["users.view", "companies.view", "billing.view", "billing.manage"], False,
        "Управление подписками поставщиков и проведение платежей.",
    ),
    "MODERATOR": (
        "Модератор",
        ["users.view", "companies.view", "kyc.view",
         "moderation.role_applications", "moderation.force_override"], False,
        "Модерация заявок на роли и аварийные force-override действия (с указанием причины).",
    ),
}


def seed(apps, schema_editor):
    OperatorRole = apps.get_model("accounts", "OperatorRole")
    CustomUser = apps.get_model("accounts", "CustomUser")
    CompanyMember = apps.get_model("accounts", "CompanyMember")

    roles = {}
    for code, (name, perms, is_system, description) in TEMPLATES.items():
        roles[code] = OperatorRole.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "permissions": list(perms),
                "is_system": is_system,
                "description": description,
            },
        )[0]

    super_operator = roles["SUPER_OPERATOR"]
    # Existing platform operators: SystemRole.ADMIN holders with NO active membership
    # (the no-membership invariant from migration 0010). Map them to SUPER_OPERATOR.
    admins = CustomUser.objects.filter(role__code="ADMIN", operator_role__isnull=True)
    for admin in admins:
        if CompanyMember.objects.filter(user=admin, is_active=True).exists():
            continue
        admin.operator_role = super_operator
        admin.save(update_fields=["operator_role"])


def unseed(apps, schema_editor):
    OperatorRole = apps.get_model("accounts", "OperatorRole")
    CustomUser = apps.get_model("accounts", "CustomUser")
    CustomUser.objects.filter(operator_role__isnull=False).update(operator_role=None)
    OperatorRole.objects.filter(code__in=list(TEMPLATES.keys())).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0026_operatorrole_customuser_operator_role")]
    operations = [migrations.RunPython(seed, unseed)]
