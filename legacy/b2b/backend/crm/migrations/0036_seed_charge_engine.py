from django.db import migrations

# B3 fix: the КП charge engine's reference data (ChargeType catalog + the GLOBAL
# `company IS NULL` ChargeTemplate Incoterm cost profiles) lived ONLY in core_seed —
# a dev/demo seeder — so a clean production DB had NO expense articles and NO default
# templates, leaving apply_charge_template_to_quote a no-op. Moved here so a fresh
# `migrate` yields a working charge apparatus on day one (IRON RULE 1).

# Expense-article kinds the КП uses (UBL 2.1 document-level cac:AllowanceCharge).
CHARGE_TYPES = [
    ("FREIGHT", "Фрахт / логистика"),
    ("INSURANCE", "Страхование груза"),
    ("CUSTOMS", "Таможенное оформление"),
    ("CERTIFICATION", "Сертификация"),
    ("RENT", "Аренда (склад/площадка)"),
    ("PAYROLL", "Оплата труда проектной команды"),
    ("COMMISSION", "Комиссионные выплаты"),
    ("DISCOUNT", "Скидка клиенту"),
    ("OTHER", "Прочие расходы"),
]

# Global (company IS NULL) default cost profiles per Incoterm basis. When a seller
# picks a basis on the КП and their company has no own templates for it, these
# platform defaults seed the QuoteCharge rows (seller then edits). Mirrors the
# responsibility matrix: the seller only sees the expense layers they actually bear.
CHARGE_TEMPLATES = {
    "CFR": ["FREIGHT"],
    "CPT": ["FREIGHT"],
    "CIF": ["FREIGHT", "INSURANCE"],
    "CIP": ["FREIGHT", "INSURANCE"],
    "DAP": ["FREIGHT", "INSURANCE"],
    "DPU": ["FREIGHT", "INSURANCE"],
    "DDP": ["FREIGHT", "INSURANCE", "CUSTOMS", "CERTIFICATION"],
}


def seed_charge_engine(apps, schema_editor):
    ChargeType = apps.get_model("crm", "ChargeType")
    ChargeTemplate = apps.get_model("crm", "ChargeTemplate")
    DeliveryBasis = apps.get_model("master_data", "DeliveryBasis")

    for sort_order, (code, name) in enumerate(CHARGE_TYPES):
        ChargeType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": sort_order})

    for basis_code, type_codes in CHARGE_TEMPLATES.items():
        try:
            basis = DeliveryBasis.objects.get(code=basis_code)
        except DeliveryBasis.DoesNotExist:
            continue
        for order, type_code in enumerate(type_codes):
            try:
                charge_type = ChargeType.objects.get(code=type_code)
            except ChargeType.DoesNotExist:
                continue
            ChargeTemplate.objects.get_or_create(
                company=None,  # global platform default
                delivery_basis=basis,
                charge_type=charge_type,
                defaults={"sort_order": order},
            )


def noop(apps, schema_editor):
    """Reverse = no-op. We never delete business lookups on rollback."""


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0035_remove_quoteitem_quote_item_snapshot_insert_or_update_and_more"),
        # Needs the DeliveryBasis Incoterm rows seeded by the master_data data migration.
        ("master_data", "0008_seed_delivery_basis_incoterms"),
    ]

    operations = [
        migrations.RunPython(seed_charge_engine, noop),
    ]
