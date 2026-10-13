from django.db import migrations

# Seed-A (audit): the ChargeType catalog offered PAYROLL / COMMISSION / RENT as document-level
# КП charges billed to the BUYER. That is the overhead/SG&A anti-pattern — salary, sales
# commission and rent are period costs covered BY the seller's margin, NOT UBL document-level
# AllowanceCharges added to the customer's invoice (and not marked up). Leaving them selectable
# let demo/stray data produce nonsense (a flat «Оплата труда +15 000 000» on an 11k-cost КП).
# Deactivate them (kept in the DB for history; the picker filters is_active=True) and drop any
# templates that auto-applied them. Legit document charges stay: FREIGHT / INSURANCE / CUSTOMS /
# CERTIFICATION / DISCOUNT / OTHER.

SGA_CODES = ["PAYROLL", "COMMISSION", "RENT"]


def deactivate_sga(apps, schema_editor):
    ChargeType = apps.get_model("crm", "ChargeType")
    ChargeTemplate = apps.get_model("crm", "ChargeTemplate")
    QuoteCharge = apps.get_model("crm", "QuoteCharge")
    sga = ChargeType.objects.filter(code__in=SGA_CODES)
    sga_ids = list(sga.values_list("id", flat=True))
    # Stop them auto-applying: remove their charge-template rows (global + per-company).
    ChargeTemplate.objects.filter(charge_type_id__in=sga_ids).delete()
    # Drop any TEMPLATE-sourced charges already sitting on quotes (manual ones — from_template
    # False — are left to the seller to remove, but these were auto-injected).
    QuoteCharge.objects.filter(charge_type_id__in=sga_ids, from_template=True).delete()
    sga.update(is_active=False)


def reactivate_sga(apps, schema_editor):
    ChargeType = apps.get_model("crm", "ChargeType")
    ChargeType.objects.filter(code__in=SGA_CODES).update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0045_quotecharge_cost_amount"),
    ]

    operations = [
        migrations.RunPython(deactivate_sga, reactivate_sga),
    ]
