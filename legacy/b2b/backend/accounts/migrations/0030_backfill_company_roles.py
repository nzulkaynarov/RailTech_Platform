"""Backfill default CompanyRoles + member company_role for tenants created AFTER mig 0023.

0023 seeded only companies existing at that time. Companies registered later (via
submit_company_profile) got NO CompanyRole rows and members with company_role=NULL, so the
access-matrix dropdown was empty and the G4 permission engine fell back to can_sell/can_buy.
This re-runs the same seed/assign for any company/member still missing it (idempotent).
Code paths are now fixed to seed on creation; this catches the gap window. Values inlined
(migrations stay frozen — no import of accounts.constants).
"""

from django.db import migrations

ADMIN_NAME = "Администратор компании"
ALL = [
    "quote.build", "quote.send", "quote.view_cost_margin", "quote.edit_pricing",
    "quote.review", "quote.approve_final",
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
ROLE_MAP = {
    "OWNER": ADMIN_NAME, "DIRECTOR": ADMIN_NAME,
    "SALES_MANAGER": "Менеджер по продажам", "LOGIST": "Менеджер по продажам",
    "CONTRACT_MANAGER": "Менеджер по продажам", "FOREIGN_TRADE_SPECIALIST": "Менеджер по продажам",
    "PROCUREMENT_MANAGER": "Менеджер закупок", "BUYER_MANAGER": "Менеджер закупок",
}


def backfill(apps, schema_editor):
    Company = apps.get_model("accounts", "Company")
    CompanyRole = apps.get_model("accounts", "CompanyRole")
    CompanyMember = apps.get_model("accounts", "CompanyMember")

    for company in Company.objects.all():
        roles = {}
        for name, perms in TEMPLATES.items():
            # get_or_create keeps already-seeded companies untouched (don't overwrite ALL perms,
            # which now includes the two new quote.review / quote.approve_final on the admin role).
            role, created = CompanyRole.objects.get_or_create(
                company=company, name=name,
                defaults={"permissions": list(perms), "is_system": name == ADMIN_NAME},
            )
            roles[name] = role
        for member in CompanyMember.objects.filter(company=company, company_role__isnull=True).select_related("role"):
            code = getattr(member.role, "code", None)
            target = ROLE_MAP.get(code)
            if target is None:
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
    dependencies = [("accounts", "0029_companysettings_min_margin_percent_and_more")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
