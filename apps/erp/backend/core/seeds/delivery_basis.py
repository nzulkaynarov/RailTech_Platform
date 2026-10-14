"""Incoterms 2020 delivery basis seed with cost-responsibility flags."""

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


def seed_incoterms(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        DeliveryBasis = apps.get_model("core", "DeliveryBasis")
    except LookupError:
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
