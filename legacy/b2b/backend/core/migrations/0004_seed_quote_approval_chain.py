"""
Seed the КП (quote) internal approval chain — idempotent data migration.

Adds the QuoteStatus rows and WorkspaceRole rows the documented sales-approval
workflow needs (see crm.services.quotes.QuoteLifecycleService):

    DRAFT → PENDING_TRADE_REVIEW → PENDING_APPROVAL → READY_TO_SEND → SENT

  * PENDING_TRADE_REVIEW — sales submitted, awaiting ВЭД (foreign-trade) confirm
  * PENDING_APPROVAL      — ВЭД confirmed, awaiting director approval
  * READY_TO_SEND         — director approved internally; may now go to client

  * SALES_MANAGER            — builds & submits the КП
  * FOREIGN_TRADE_SPECIALIST — confirms the trade review (ВЭД)
  * DIRECTOR                 — approves the КП before it leaves the company
                               (distinct from OWNER, who administers the team)

Rule 1 (CLAUDE.md): business lookups = data migrations. Reverse is a no-op —
seeded lookup rows are never auto-deleted (they anchor FK chains in prod).
"""

from django.db import migrations

# (code, name, sort_order) — slotted between DRAFT (10) and SENT (20).
NEW_QUOTE_STATUSES = [
    ("PENDING_TRADE_REVIEW", "На проверке ВЭД", 12),
    ("PENDING_APPROVAL", "На утверждении", 14),
    ("READY_TO_SEND", "Готово к отправке", 16),
]

# (code, name, sort_order)
NEW_WORKSPACE_ROLES = [
    ("DIRECTOR", "Директор", 15),
    ("SALES_MANAGER", "Менеджер по продажам", 25),
    ("FOREIGN_TRADE_SPECIALIST", "Менеджер ВЭД", 35),
]


def seed(apps, schema_editor):
    QuoteStatus = apps.get_model("crm", "QuoteStatus")
    WorkspaceRole = apps.get_model("accounts", "WorkspaceRole")

    for code, name, sort_order in NEW_QUOTE_STATUSES:
        QuoteStatus.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )
    for code, name, sort_order in NEW_WORKSPACE_ROLES:
        WorkspaceRole.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_supportticket_supportticketmessage"),
        ("crm", "0013_alter_deal_created_at"),
        ("accounts", "0012_customuser_position_alter_company_inn"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_code=noop),
    ]
