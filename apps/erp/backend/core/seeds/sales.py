"""Sales lookups, statuses, and charge engine seed."""

DEAL_STAGES = [
    ("DRAFT", "Черновик", 10, True),
    ("KYC_PENDING", "Ожидание KYC", 20, False),  # retired stage, kept inactive for legacy FKs
    ("RFQ_OPEN", "Заявка открыта", 30, True),
    ("SOURCING", "Подбор поставщиков", 40, True),
    ("CALCULATING", "Расчёт цен", 50, True),
    ("QUOTE_SENT", "КП отправлено", 60, True),
    ("CONTRACT_SIGNED", "Договор подписан", 70, True),
    ("CLOSED_WON", "Закрыта (выиграна)", 80, True),
    ("CLOSED_LOST", "Закрыта (проиграна)", 90, True),
]

QUOTE_STATUSES = [
    ("DRAFT", "Черновик", 10),
    ("PENDING_TRADE_REVIEW", "На проверке ВЭД", 12),
    ("PENDING_APPROVAL", "На утверждении", 14),
    ("READY_TO_SEND", "Готово к отправке", 16),
    ("SENT", "Отправлено клиенту", 20),
    ("APPROVED", "Одобрено клиентом", 30),
    ("REJECTED", "Отклонено", 40),
    ("EXPIRED", "Срок истёк", 50),
]

CONTRACT_STATUSES = [
    ("DRAFT", "Черновик", 10),
    ("PENDING_CLIENT", "Ожидает подписи клиента", 20),
    ("PENDING_MANAGER", "Ожидает подписи менеджера", 30),
    ("SIGNED", "Подписан сторонами", 40),
    ("CANCELLED", "Отменён", 50),
]

FULFILLMENT_STATUSES = [
    ("PENDING", "Ожидает отгрузки", 10),
    ("SHIPPED", "Отгружено", 20),
    ("IN_TRANSIT", "В пути", 30),
    ("DELIVERED", "Доставлено", 40),
    ("ACCEPTED", "Принято клиентом", 50),
    ("DISPUTED", "Спорная ситуация", 60),
]

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

CHARGE_TEMPLATES = {
    "CIF": ["INSURANCE"],
    "CIP": ["INSURANCE"],
    "DAP": ["INSURANCE"],
    "DPU": ["INSURANCE"],
    "DDP": ["INSURANCE", "CERTIFICATION"],
}

FREIGHT_BASES = ["CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]


def seed_sales_lookups(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        DealStage = apps.get_model("sales", "DealStage")
        QuoteStatus = apps.get_model("sales", "QuoteStatus")
        ContractStatus = apps.get_model("sales", "ContractStatus")
        FulfillmentStatus = apps.get_model("sales", "FulfillmentStatus")
    except LookupError:
        DealStage = apps.get_model("crm", "DealStage")
        QuoteStatus = apps.get_model("crm", "QuoteStatus")
        ContractStatus = apps.get_model("crm", "ContractStatus")
        FulfillmentStatus = apps.get_model("crm", "FulfillmentStatus")

    for code, name, sort_order, is_active in DEAL_STAGES:
        DealStage.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": is_active},
        )

    for code, name, sort_order in QUOTE_STATUSES:
        QuoteStatus.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )

    for code, name, sort_order in CONTRACT_STATUSES:
        ContractStatus.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )

    for code, name, sort_order in FULFILLMENT_STATUSES:
        FulfillmentStatus.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )


def seed_charge_engine(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        ChargeType = apps.get_model("sales", "ChargeType")
        ChargeTemplate = apps.get_model("sales", "ChargeTemplate")
    except LookupError:
        ChargeType = apps.get_model("crm", "ChargeType")
        ChargeTemplate = apps.get_model("crm", "ChargeTemplate")

    try:
        DeliveryBasis = apps.get_model("core", "DeliveryBasis")
    except LookupError:
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
                company=None,
                delivery_basis=basis,
                charge_type=charge_type,
                defaults={"sort_order": order},
            )


def seed_basis_freight(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        DeliveryBasis = apps.get_model("core", "DeliveryBasis")
    except LookupError:
        DeliveryBasis = apps.get_model("master_data", "DeliveryBasis")

    try:
        ChargeType = apps.get_model("sales", "ChargeType")
        ChargeTemplate = apps.get_model("sales", "ChargeTemplate")
    except LookupError:
        ChargeType = apps.get_model("crm", "ChargeType")
        ChargeTemplate = apps.get_model("crm", "ChargeTemplate")

    freight = ChargeType.objects.filter(code="FREIGHT").first()
    if not freight:
        return
    for basis_code in FREIGHT_BASES:
        basis = DeliveryBasis.objects.filter(code=basis_code).first()
        if not basis:
            continue
        ChargeTemplate.objects.get_or_create(company=None, delivery_basis=basis, charge_type=freight)
