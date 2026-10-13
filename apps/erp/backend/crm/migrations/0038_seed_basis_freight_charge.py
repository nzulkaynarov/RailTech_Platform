"""Add FREIGHT to the global per-basis charge templates (F3.8 follow-up).

The F3.8 refactor moved freight from a per-line column to a DOCUMENT-level charge,
but the global charge-template seed (0036) — written under the old per-line model —
never carried FREIGHT for any basis. So picking CIF/DDP auto-applied insurance/cert
but silently dropped freight, forcing the seller to add «Фрахт / логистика» by hand.
This seeds a global FREIGHT template for every Incoterm where the SELLER bears main
carriage (Incoterms 2020). Amount left blank — the seller fills the actual cost.
Idempotent (get_or_create); reverse = no-op.
"""

from django.db import migrations

# Incoterms 2020 where the seller arranges & pays main carriage → freight is the
# seller's document-level cost. (EXW/FCA/FAS/FOB = buyer pays carriage → no freight.)
FREIGHT_BASES = ["CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]


def seed_basis_freight(apps, schema_editor):
    DeliveryBasis = apps.get_model("master_data", "DeliveryBasis")
    ChargeType = apps.get_model("crm", "ChargeType")
    ChargeTemplate = apps.get_model("crm", "ChargeTemplate")

    freight = ChargeType.objects.filter(code="FREIGHT").first()
    if not freight:
        return  # ChargeType catalog not seeded yet — 0036 owns it
    for basis_code in FREIGHT_BASES:
        basis = DeliveryBasis.objects.filter(code=basis_code).first()
        if not basis:
            continue
        ChargeTemplate.objects.get_or_create(company=None, delivery_basis=basis, charge_type=freight)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0037_backfill_document_sequences"),
        ("master_data", "0008_seed_delivery_basis_incoterms"),
    ]
    operations = [migrations.RunPython(seed_basis_freight, noop)]
