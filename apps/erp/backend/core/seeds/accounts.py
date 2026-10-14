"""Accounts roles seed (SystemRole, WorkspaceRole and applicability)."""

SYSTEM_ROLES = [
    ("ADMIN", "Администратор платформы", 10),
    ("USER", "Пользователь", 20),
]

WORKSPACE_ROLES = [
    ("OWNER", "Администратор компании", 10),
    ("DIRECTOR", "Директор", 15),
    ("PROCUREMENT_MANAGER", "Снабженец", 20),
    ("BUYER_MANAGER", "Менеджер (Покупатель)", 25),
    ("SALES_MANAGER", "Продавец", 30),
    ("FOREIGN_TRADE_SPECIALIST", "Специалист ВЭД", 35),
    ("CONTRACT_MANAGER", "Договорник", 40),
    ("LOGIST", "Логист", 45),
    ("ACCOUNTANT", "Бухгалтер", 50),
    ("MEMBER", "Сотрудник", 60),
]

ROLE_APPLICABILITY = {
    "OWNER": [],
    "ACCOUNTANT": [],
    "MEMBER": [],
    "PROCUREMENT_MANAGER": ["CLIENT"],
    "BUYER_MANAGER": ["CLIENT"],
    "SALES_MANAGER": ["SUPPLIER", "MANUFACTURER"],
    "FOREIGN_TRADE_SPECIALIST": ["SUPPLIER", "MANUFACTURER"],
    "CONTRACT_MANAGER": ["SUPPLIER", "MANUFACTURER"],
    "DIRECTOR": ["SUPPLIER", "MANUFACTURER"],
    "LOGIST": ["SUPPLIER", "MANUFACTURER", "LOGISTICS_PROVIDER"],
}


def seed_roles(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    SystemRole = apps.get_model("accounts", "SystemRole")
    WorkspaceRole = apps.get_model("accounts", "WorkspaceRole")
    try:
        CompanyType = apps.get_model("parties", "CompanyType")
    except LookupError:
        CompanyType = apps.get_model("accounts", "CompanyType")

    try:
        Group = apps.get_model("auth", "Group")
        Group.objects.get_or_create(name="system_engineers")
    except LookupError:
        pass

    for code, name, sort_order in SYSTEM_ROLES:
        SystemRole.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )

    for code, name, sort_order in WORKSPACE_ROLES:
        WorkspaceRole.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )

    for role_code, type_codes in ROLE_APPLICABILITY.items():
        role = WorkspaceRole.objects.filter(code=role_code).first()
        if role is None:
            continue
        if not type_codes:
            role.applicable_to_types.clear()
            continue
        types = list(CompanyType.objects.filter(code__in=type_codes))
        if types:
            role.applicable_to_types.set(types)


def widen_ved_applicability(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    WorkspaceRole = apps.get_model("accounts", "WorkspaceRole")
    try:
        CompanyType = apps.get_model("parties", "CompanyType")
    except LookupError:
        CompanyType = apps.get_model("accounts", "CompanyType")

    role = WorkspaceRole.objects.filter(code="FOREIGN_TRADE_SPECIALIST").first()
    if role is None:
        return
    types = list(CompanyType.objects.filter(code__in=["SUPPLIER", "MANUFACTURER"]))
    if types:
        role.applicable_to_types.set(types)
