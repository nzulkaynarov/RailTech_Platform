from django.db import migrations

# Incoterms 2020 — basis code, Russian name, and the cost-responsibility flags
# (seller_pays_freight, seller_pays_insurance, seller_pays_import, seller_pays_delivery).
# These flags drive the КП charge engine: the basis the seller picks determines which
# expense layers the cost UI shows/requires — no hardcoded `if code == 'DDP'` in services.
# B3 fix: this reference data lived ONLY in core_seed (a demo seeder), so a clean
# production DB had a DEAD basis/charge apparatus. Moved here so a fresh `migrate`
# yields a working Incoterm matrix on day one (IRON RULE 1).
INCOTERMS = [
    # (code, name, freight, insurance, import, delivery)
    ("EXW", "Франко-завод", False, False, False, False),
    ("FCA", "Франко-перевозчик", False, False, False, False),
    ("FAS", "Свободно вдоль борта судна", False, False, False, False),
    ("FOB", "Свободно на борту", False, False, False, False),
    ("CFR", "Стоимость и фрахт", True, False, False, False),
    ("CIF", "Стоимость, страхование и фрахт", True, True, False, False),
    ("CPT", "Перевозка оплачена до", True, False, False, False),
    ("CIP", "Перевозка и страхование оплачены до", True, True, False, False),
    ("DAP", "Поставка в место назначения", True, False, False, True),
    ("DPU", "Поставка в месте выгрузки", True, False, False, True),
    ("DDP", "Поставка с оплатой пошлин", True, False, True, True),
]


def seed_incoterms(apps, schema_editor):
    DeliveryBasis = apps.get_model("master_data", "DeliveryBasis")
    for sort_order, (code, name, freight, insurance, imp, delivery) in enumerate(INCOTERMS):
        DeliveryBasis.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "sort_order": sort_order,
                "seller_pays_freight": freight,
                "seller_pays_insurance": insurance,
                "seller_pays_import": imp,
                "seller_pays_delivery": delivery,
            },
        )


def noop(apps, schema_editor):
    """Reverse = no-op. We never delete business lookups on rollback."""


class Migration(migrations.Migration):

    dependencies = [
        ("master_data", "0007_deliverybasis_seller_pays_delivery_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_incoterms, noop),
    ]
