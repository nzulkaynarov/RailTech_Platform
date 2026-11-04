"""Роли сессии кабинета и модули (ADR-0022 п. 3; решение владельца 2026-11-04).

Роли две и складываются: `client` (тип компании CLIENT) и `partner` (отношение `partner`, его заводит сотрудник). Модули —
разделы кабинета; меню Cabinet строится из `/me.modules`, а эндпоинт портала открыт сессии, у которой есть его модуль
(`portal.permissions.HasPortalModule`). Модули клиента — весь шаблон роли; модули партнёра — те, что сотрудник включил на
отношении (`CompanyRelationship.modules`), но только из шаблона роли `partner`. Роли и модули складываются: компания с CLIENT
и активным партнёрским отношением получает клиентские модули и включённые партнёрские.

Шаблон — данные в одном месте. Контракт `erp-portal.yaml` несёт тот же (`Me.x-role-modules`, `x-role-default-modules` и
перечень `ModuleCode`), тест `portal/tests/test_portal_roles.py` сверяет их: новая роль или модуль сначала в контракте.
Порядок модулей — порядок пунктов меню.
"""

from parties.models import RelationshipRole

#: Клиентские разделы кабинета (ARCHITECTURE §5). `catalog_requests` — каталог и заявки: оба пункта меню и их эндпоинты.
CLIENT_MODULES = (
    "catalog_requests",
    "quotes",
    "documents",
    "contracts",
    "invoices",
    "acts",
    "deliveries",
    "company",
    "team",
    "profile",
)

#: Модули, которые шаблон разрешает роли (для партнёра — те, что сотрудник может включить). Клиентские КП, договоры,
#: счета, акты, отгрузки и документы партнёру не включаются: они появляются, когда компания становится клиентом.
ROLE_MODULES: dict[str, tuple[str, ...]] = {
    RelationshipRole.CLIENT.value: CLIENT_MODULES,
    RelationshipRole.PARTNER.value: ("my_products", "catalog_requests", "profile"),
}

#: Модули, которые есть у любой сессии кабинета и не выключаются переключателем: «Профиль» — выход и язык (владелец 2026-11-04).
ALWAYS_ON = ("profile",)

#: Что получает новое отношение. Клиент — всё (тип CLIENT, отношения у клиента нет); партнёр — «Мои товары» и «Каталог и
#: заявки» (владелец 2026-11-04: оба включены по умолчанию, сотрудник выключает переключателем в Платформе).
ROLE_DEFAULT_MODULES: dict[str, tuple[str, ...]] = {
    RelationshipRole.CLIENT.value: CLIENT_MODULES,
    RelationshipRole.PARTNER.value: ("my_products", "catalog_requests", "profile"),
}

#: Модули партнёра, которые сотрудник включает и выключает (шаблон роли без обязательных).
PARTNER_TOGGLEABLE = tuple(m for m in ROLE_MODULES[RelationshipRole.PARTNER.value] if m not in ALWAYS_ON)
PARTNER_DEFAULT_TOGGLEABLE = tuple(
    m for m in ROLE_DEFAULT_MODULES[RelationshipRole.PARTNER.value] if m not in ALWAYS_ON
)

PARTNER = RelationshipRole.PARTNER.value
CLIENT = RelationshipRole.CLIENT.value


def partner_enabled(modules) -> list[str]:
    """Модули партнёра в кабинете: включённые сотрудником и обязательные, только из шаблона роли, в порядке шаблона
    (мусор и повторы в базе не открывают ничего)."""
    wanted = set(modules or []) | set(ALWAYS_ON)
    return [module for module in ROLE_MODULES[PARTNER] if module in wanted]


def partner_toggled(modules) -> list[str]:
    """То, что сотрудник видит переключателями: включённые партнёру модули без обязательных."""
    return [module for module in partner_enabled(modules) if module not in ALWAYS_ON]


def modules_for(roles: list[str], partner_modules=None) -> list[str]:
    """Модули сессии: клиентские (если есть роль `client`) плюс включённые партнёру (если есть роль `partner`)."""
    modules: list[str] = []
    if CLIENT in roles:
        modules.extend(ROLE_MODULES[CLIENT])
    if PARTNER in roles:
        modules.extend(module for module in partner_enabled(partner_modules) if module not in modules)
    return modules
