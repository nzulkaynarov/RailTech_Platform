"""Currencies seed."""

CURRENCIES = [
    ("UZS", "Узбекский сум", "сўм", 10),
    ("USD", "Доллар США", "$", 20),
    ("EUR", "Евро", "€", 30),
    ("RUB", "Российский рубль", "₽", 40),
    ("CNY", "Китайский юань", "¥", 50),
]


def seed_currencies(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        Currency = apps.get_model("core", "Currency")
    except LookupError:
        Currency = apps.get_model("master_data", "Currency")

    for code, name, symbol, sort_order in CURRENCIES:
        Currency.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "symbol": symbol,
                "sort_order": sort_order,
                "is_active": True,
            },
        )
