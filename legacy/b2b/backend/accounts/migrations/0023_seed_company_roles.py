"""Seed per-company role templates (Role+Permission-set) + map existing members.

Each company gets 5 starting roles; each member's company_role is derived from their
legacy WorkspaceRole. Values are inlined (migrations must stay frozen — do NOT import
accounts.constants). See Docs/dev/specs/rbac-roles-design-2026-06-25.md.
"""

from django.db import migrations

ADMIN_NAME = "Администратор компании"

# name → permission codes (mirror of accounts.constants.ROLE_TEMPLATES at this point in time)
ALL = [
    "quote.build", "quote.send", "quote.view_cost_margin", "quote.edit_pricing",
    "request.create", "quote.approve", "contract.sign", "payment.record",
    "catalog.manage", "catalog.publish",
    "team.manage", "settings.edit", "charge_templates.manage", "data.export",
]
TEMPLATES = {
    ADMIN_NAME: ALL,
    "Менеджер по продажам": ["quote.build", "quote.send", "quote.view_cost_margin", "quote.edit_pricing", "catalog.manage"],
    "Менеджер закупок": ["request.create", "quote.approve", "contract.sign", "payment.record"],
    "Финансы": ["payment.record", "quote.view_cost_margin", "data.export"],
    "Наблюдатель": [],
}
# legacy WorkspaceRole.code → template name
ROLE_MAP = {
    "OWNER": ADMIN_NAME,
    "DIRECTOR": ADMIN_NAME,
    "SALES_MANAGER": "Менеджер по продажам",
    "LOGIST": "Менеджер по продажам",
    "CONTRACT_MANAGER": "Менеджер по продажам",
    "FOREIGN_TRADE_SPECIALIST": "Менеджер по продажам",
    "PROCUREMENT_MANAGER": "Менеджер закупок",
    "BUYER_MANAGER": "Менеджер закупок",
}


def seed(apps, schema_editor):
    Company = apps.get_model("accounts", "Company")
    CompanyRole = apps.get_model("accounts", "CompanyRole")
    CompanyMember = apps.get_model("accounts", "CompanyMember")

    for company in Company.objects.all():
        roles = {}
        for name, perms in TEMPLATES.items():
            roles[name] = CompanyRole.objects.get_or_create(
                company=company, name=name,
                defaults={"permissions": list(perms), "is_system": name == ADMIN_NAME},
            )[0]
        for member in CompanyMember.objects.filter(company=company).select_related("role"):
            code = getattr(member.role, "code", None)
            target = ROLE_MAP.get(code)
            if target is None:
                # Unknown/legacy role → derive from capabilities, else viewer.
                if member.can_sell and member.can_buy:
                    target = ADMIN_NAME
                elif member.can_sell:
                    target = "Менеджер по продажам"
                elif member.can_buy:
                    target = "Менеджер закупок"
                else:
                    target = "Наблюдатель"
            member.company_role = roles[target]
            member.save(update_fields=["company_role"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0022_companyrole_companymember_company_role_and_more")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
