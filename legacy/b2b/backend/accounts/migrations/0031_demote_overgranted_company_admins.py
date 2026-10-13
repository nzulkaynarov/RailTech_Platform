"""Corrective data-fix for the U2 privilege-escalation (post-merge audit 2026-06-30).

Migration 0030_backfill_company_roles over-granted the is_system «Администратор компании»
CompanyRole (ALL permissions) to any member whose legacy WorkspaceRole was NOT in its ROLE_MAP
AND who had can_sell AND can_buy (both DEFAULT True). The seeded WorkspaceRole «MEMBER»
(«Сотрудник») is unmapped, so plain employees were silently made full company admins. After
ADR-0005 U2 keyed the company-admin gates on the `team.manage`/`settings.edit` PERMISSIONS
(which the is_system role grants), that latent over-grant became exploitable: such a member could
invite/manage the team, edit the document profile, КП defaults, numbering and roles.

The RUNTIME path (services/roles.default_company_role_for) already maps unknown WorkspaceRole
codes to «Наблюдатель», so no NEW over-grants occur. This migration corrects the data the buggy
backfill left behind: any active member on an is_system role whose WorkspaceRole is NOT an admin
role (OWNER/DIRECTOR) is re-mapped to the role their WorkspaceRole implies (default «Наблюдатель»).

Conservative by design:
  * OWNER / DIRECTOR keep their admin role (legitimate company admins).
  * Never-orphan: a member who is the SOLE active is_system admin of their company is left
    untouched (demoting them would strip the company of every admin) — flagged for manual review.
  * A deliberately-delegated admin (a non-OWNER promoted via U2) WILL be reset to their
    WorkspaceRole's role; the company OWNER can re-promote them in the access-matrix UI. This is the
    accepted trade-off for closing the escalation (owner decision, 2026-06-30).

Values inlined (migrations stay frozen — no import of accounts.constants). Reverse = no-op.
"""

from django.db import migrations

ADMIN_NAME = "Администратор компании"
ADMIN_WORKSPACE_CODES = {"OWNER", "DIRECTOR"}
ROLE_MAP = {
    "SALES_MANAGER": "Менеджер по продажам",
    "LOGIST": "Менеджер по продажам",
    "CONTRACT_MANAGER": "Менеджер по продажам",
    "FOREIGN_TRADE_SPECIALIST": "Менеджер по продажам",
    "PROCUREMENT_MANAGER": "Менеджер закупок",
    "BUYER_MANAGER": "Менеджер закупок",
}
DEFAULT_ROLE = "Наблюдатель"


def demote_overgranted(apps, schema_editor):
    CompanyMember = apps.get_model("accounts", "CompanyMember")
    CompanyRole = apps.get_model("accounts", "CompanyRole")

    candidates = (
        CompanyMember.objects.filter(is_active=True, company_role__is_system=True)
        .exclude(role__code__in=ADMIN_WORKSPACE_CODES)
        .select_related("role", "company_role")
    )
    for member in candidates:
        # Never-orphan: keep this member as admin if they are the company's only active admin.
        has_other_admin = (
            CompanyMember.objects.filter(
                company_id=member.company_id, is_active=True, company_role__is_system=True
            )
            .exclude(pk=member.pk)
            .exists()
        )
        if not has_other_admin:
            continue

        target_name = ROLE_MAP.get(getattr(member.role, "code", None), DEFAULT_ROLE)
        target = (
            CompanyRole.objects.filter(company_id=member.company_id, name=target_name).first()
            or CompanyRole.objects.filter(company_id=member.company_id, name=DEFAULT_ROLE).first()
        )
        if target is not None and target.pk != member.company_role_id:
            member.company_role = target
            member.save(update_fields=["company_role"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0030_backfill_company_roles")]
    operations = [migrations.RunPython(demote_overgranted, migrations.RunPython.noop)]
