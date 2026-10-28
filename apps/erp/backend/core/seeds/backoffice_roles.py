"""Роли бэк-офиса (M1-ERP-05) для миграции accounts/0003 — ЗАМОРОЖЕННАЯ копия шаблонов.

Миграция не импортирует `accounts.constants` (код меняется, миграция — нет). Рабочая истина —
`accounts.constants.ROLE_TEMPLATES`; тест `accounts/tests/test_backoffice_roles.py` сверяет её
с этой таблицей, а `accounts.services.roles.ensure_default_company_roles` догоняет системные роли
до шаблона в коде при следующем обращении.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Каталог 0003 включал и код финального утверждения КП директором; волна 12 (EDS-03) его удалила: одобрение КП — маршрут
# EDS. На чистой базе 0003 его больше не сеет, на живой — снимает accounts/0010 (`prune_unknown_permissions`).
ALL = [
    "deal.manage",
    "deal.assign",
    "quote.build",
    "quote.edit_pricing",
    "quote.view_cost_margin",
    "quote.send",
    "quote.review",
    "contract.manage",
    "contract.sign",
    "catalog.manage",
    "catalog.publish",
    "supply.manage",
    "fulfillment.manage",
    "fulfillment.act",
    "finance.invoice",
    "finance.payment",
    "settings.edit",
    "settings.charge_templates",
    "team.manage",
    "data.export",
]

# (код, имя, права)
BACKOFFICE_ROLES = [
    (
        "CALCULATION",
        "Расчёт",
        [
            "deal.manage",
            "quote.build",
            "quote.edit_pricing",
            "quote.view_cost_margin",
            "quote.send",
            "quote.review",
            "contract.manage",
        ],
    ),
    (
        "CATALOG_SUPPLY",
        "Каталог и закупки",
        ["catalog.manage", "catalog.publish", "supply.manage", "quote.view_cost_margin"],
    ),
    ("FULFILLMENT", "Исполнение и логистика", ["fulfillment.manage", "fulfillment.act"]),
    ("FINANCE", "Финансы", ["finance.invoice", "finance.payment", "quote.view_cost_margin", "data.export"]),
    ("HEAD", "Руководитель", ALL),
    ("VIEWER", "Наблюдатель", []),
]

# Старые коды прав → новые (держатели прежнего права получают то, что оно покрывало).
LEGACY_RENAMES = {
    "payment.record": ["finance.payment"],
    "charge_templates.manage": ["settings.charge_templates"],
    "catalog.manage": ["catalog.manage", "supply.manage"],
    "quote.build": ["quote.build", "deal.manage"],
}

# Старые шаблоны маркетплейса своей компании → новые роли их участников (шаблон удаляется).
LEGACY_TEMPLATE_ROLES = {
    "Администратор компании": ["HEAD"],
    "Менеджер по продажам": ["CALCULATION", "CATALOG_SUPPLY"],
    "Менеджер закупок": ["VIEWER"],
}

# Участник своей компании без роли получал права из должности (снятый фолбэк) — выдаём роли по ней.
WORKSPACE_TO_ROLES = {
    "OWNER": ["HEAD"],
    "DIRECTOR": ["HEAD"],
    "SALES_MANAGER": ["CALCULATION"],
    "CONTRACT_MANAGER": ["CALCULATION"],
    "FOREIGN_TRADE_SPECIALIST": ["CALCULATION"],
    "PROCUREMENT_MANAGER": ["CATALOG_SUPPLY"],
    "LOGIST": ["FULFILLMENT"],
    "ACCOUNTANT": ["FINANCE"],
}


def _own_company_ids(apps):
    """Своя компания так же, как `core.tenant.own_company_id`: настройка или единственная
    компания-продавец (тип SUPPLIER) с активными участниками. Несколько без настройки — никого:
    роли досеет `ensure_default_company_roles`, когда `OWN_COMPANY_ID` будет задан.

    `OWN_COMPANY_ID` на компанию, которой в базе нет (чистая база при сбросе прода), — пропуск с записью
    в лог, а не ошибка: роли строки `CompanyRole` ссылаются на компанию внешним ключом, и сев на
    несуществующую, миграция падала бы `IntegrityError`. Роли такой компании появятся после мастера
    первого запуска (`create_own_company` → `ensure_default_company_roles`)."""
    configured = getattr(settings, "OWN_COMPANY_ID", None)
    if configured:
        company_id = int(configured)
        Company = apps.get_model("parties", "Company")
        if not Company.objects.filter(pk=company_id).exists():
            logger.warning(
                "accounts.0003_backoffice_roles: OWN_COMPANY_ID=%s указывает на несуществующую компанию — "
                "роли бэк-офиса не засеяны; их создаст мастер первого запуска (ensure_default_company_roles).",
                company_id,
            )
            return []
        return [company_id]
    CompanyMember = apps.get_model("accounts", "CompanyMember")
    ids = sorted(
        set(
            CompanyMember.objects.filter(is_active=True, company__types__code="SUPPLIER").values_list(
                "company_id", flat=True
            )
        )
    )
    return ids if len(ids) == 1 else []


def _renamed(permissions):
    result = []
    for code in permissions or []:
        for new_code in LEGACY_RENAMES.get(code, [code]):
            if new_code in ALL and new_code not in result:
                result.append(new_code)
    return result


def _seed_system_roles(CompanyRole, company_id):
    roles = {}
    for code, name, perms in BACKOFFICE_ROLES:
        role = CompanyRole.objects.filter(company_id=company_id, code=code).first()
        if role is None:
            role = CompanyRole.objects.filter(company_id=company_id, name=name).first()
        if role is None:
            role = CompanyRole(company_id=company_id, name=name)
        role.code, role.permissions, role.is_system = code, list(perms), True
        role.save()
        roles[code] = role
    return roles


def _migrate_own_company(apps, company_id):
    CompanyRole = apps.get_model("accounts", "CompanyRole")
    CompanyMember = apps.get_model("accounts", "CompanyMember")
    for role in CompanyRole.objects.filter(company_id=company_id, code=""):
        role.permissions = _renamed(role.permissions)
        role.save(update_fields=["permissions"])
    roles = _seed_system_roles(CompanyRole, company_id)
    for name, codes in LEGACY_TEMPLATE_ROLES.items():
        legacy = CompanyRole.objects.filter(company_id=company_id, name=name, code="").first()
        if legacy is None:
            continue
        for member in legacy.members.all():
            member.company_roles.add(*[roles[c] for c in codes])
        legacy.delete()
    roleless = CompanyMember.objects.filter(company_id=company_id, company_roles__isnull=True).select_related("role")
    for member in roleless:
        codes = WORKSPACE_TO_ROLES.get(getattr(member.role, "code", ""), ["VIEWER"])
        member.company_roles.add(*[roles[c] for c in codes])


def copy_single_role_to_set(apps, schema_editor):
    """`CompanyMember.company_role` (одна роль) → `company_roles` (набор)."""
    CompanyMember = apps.get_model("accounts", "CompanyMember")
    for member in CompanyMember.objects.exclude(company_role__isnull=True):
        member.company_roles.add(member.company_role_id)


# M1-ERP-08 (миграция accounts/0004): новый код `finance.rates` — системным ролям «Финансы» и
# «Руководитель» своей компании. Замороженная копия, как таблица выше: каталог прав после 0004 =
# ALL + ADDED_0004, шаблоны = BACKOFFICE_ROLES + ROLE_GRANTS_0004 (сверяет test_backoffice_roles).
ADDED_0004 = ["finance.rates"]
ROLE_GRANTS_0004 = {"FINANCE": ["finance.rates"], "HEAD": ["finance.rates"]}


def grant_finance_rates(apps, schema_editor):
    """Догнать системные роли «Финансы» и «Руководитель» до шаблона с `finance.rates`."""
    CompanyRole = apps.get_model("accounts", "CompanyRole")
    for code, added in ROLE_GRANTS_0004.items():
        for role in CompanyRole.objects.filter(code=code, is_system=True):
            missing = [perm for perm in added if perm not in (role.permissions or [])]
            if missing:
                role.permissions = list(role.permissions or []) + missing
                role.save(update_fields=["permissions"])


def seed_backoffice_roles(apps, schema_editor):
    """Каталог прав M1-ERP-05: системные роли своей компании, переименование кодов, роли участникам."""
    for company_id in _own_company_ids(apps):
        _migrate_own_company(apps, company_id)


# Волна 12 (EDS-03, миграции accounts/0010 и integration/0010): одобрение КП директором ушло в маршрут EDS, код права
# финального утверждения из каталога удалён. Каталог после 0010 = ALL + ADDED_0004; коды вне него снимаются с ролей и
# со снимков провижининга CRM (замороженная копия, как таблицы выше: сверяет test_backoffice_roles).
CATALOG_0010 = ALL + ADDED_0004


def _known(permissions):
    return [code for code in (permissions or []) if code in CATALOG_0010]


def prune_unknown_permissions(apps, schema_editor):
    """Снять с ролей коды прав, которых нет в каталоге (код финального утверждения КП — волна 12)."""
    CompanyRole = apps.get_model("accounts", "CompanyRole")
    for role in CompanyRole.objects.all():
        known = _known(role.permissions)
        if known != list(role.permissions or []):
            role.permissions = known
            role.save(update_fields=["permissions"])


def prune_unknown_snapshot_permissions(apps, schema_editor):
    """То же для последнего провижининга CRM (`CrmUserMapping.provision_snapshot["permissions"]`)."""
    CrmUserMapping = apps.get_model("integration", "CrmUserMapping")
    for mapping in CrmUserMapping.objects.exclude(provision_snapshot__isnull=True):
        snapshot = dict(mapping.provision_snapshot or {})
        permissions = snapshot.get("permissions")
        if not isinstance(permissions, list) or _known(permissions) == permissions:
            continue
        snapshot["permissions"] = _known(permissions)
        mapping.provision_snapshot = snapshot
        mapping.save(update_fields=["provision_snapshot"])


# D2-1 (миграция accounts/0011): виза строки расчёта по типу позиции — `quote.visa_goods` и `quote.visa_services`
# (ADR-0012 п. 6). Системные роли «Расчёт» и «Руководитель» своей компании получают оба кода. Замороженная копия, как
# таблицы выше: каталог после 0011 = CATALOG_0010 + ADDED_0011, шаблоны = BACKOFFICE_ROLES + ROLE_GRANTS_0004 +
# ROLE_GRANTS_0011 (сверяет test_backoffice_roles).
ADDED_0011 = ["quote.visa_goods", "quote.visa_services"]
ROLE_GRANTS_0011 = {"CALCULATION": ADDED_0011, "HEAD": ADDED_0011}
CATALOG_0011 = CATALOG_0010 + ADDED_0011


def grant_calc_visas(apps, schema_editor):
    """Догнать системные роли «Расчёт» и «Руководитель» до шаблона с визами расчёта."""
    CompanyRole = apps.get_model("accounts", "CompanyRole")
    for code, added in ROLE_GRANTS_0011.items():
        for role in CompanyRole.objects.filter(code=code, is_system=True):
            missing = [perm for perm in added if perm not in (role.permissions or [])]
            if missing:
                role.permissions = list(role.permissions or []) + missing
                role.save(update_fields=["permissions"])
