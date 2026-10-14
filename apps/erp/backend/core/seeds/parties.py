"""Parties lookups seed (CompanyType)."""

COMPANY_TYPES = [
    ("CLIENT", "Клиент", 10),
    ("SUPPLIER", "Поставщик", 20),
    ("MANUFACTURER", "Производитель", 30),
    ("LOGISTICS_PROVIDER", "Логистика", 40),
]


def seed_company_types(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        CompanyType = apps.get_model("parties", "CompanyType")
    except LookupError:
        CompanyType = apps.get_model("accounts", "CompanyType")

    for code, name, sort_order in COMPANY_TYPES:
        CompanyType.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )
