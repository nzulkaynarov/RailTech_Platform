"""Finance lookups seed (InvoiceStatus, ActStatus)."""

INVOICE_STATUSES = [
    ("DRAFT", "Черновик", 10),
    ("ISSUED", "Выставлен", 20),
    ("PARTIAL", "Частично оплачен", 30),
    ("PAID", "Оплачен", 40),
    ("OVERDUE", "Просрочен", 50),
    ("CANCELLED", "Отменён", 60),
]

ACT_STATUSES = [
    ("DRAFT", "Черновик", 10),
    ("ISSUED", "Выставлен", 20),
    ("SIGNED", "Подписан", 30),
    ("CANCELLED", "Отменён", 40),
]


def seed_finance_lookups(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        InvoiceStatus = apps.get_model("finance", "InvoiceStatus")
        ActStatus = apps.get_model("finance", "ActStatus")
    except LookupError:
        InvoiceStatus = apps.get_model("crm", "InvoiceStatus")
        ActStatus = apps.get_model("crm", "ActStatus")

    for code, name, sort_order in INVOICE_STATUSES:
        InvoiceStatus.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )

    for code, name, sort_order in ACT_STATUSES:
        ActStatus.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )
