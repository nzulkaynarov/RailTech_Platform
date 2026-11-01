"""Роли пилота (P8; DECISIONS 2026-10-29 W-1, W-2; 2026-11-01 п. 1): матрица прав четырёх ролей.

Для каждой роли — какие разделы Платформы она видит и какие действия ей доступны в CRM, ERP и
EDS. Ожидания выписаны по runbook 18a (строка P8), SPEC-v3 §3.2a «Права» и §4.1, независимо от
`platform-rbac.yaml`: ловят правку каталога, которая незаметно отняла бы у роли пилота действие
или дала лишнее (резолюцию делопроизводителю).
"""

import pytest

from app.domain.platform_roles import default_roles, derive_access, eds_permissions_of
from tests.platform_role_data import make_grant

PILOT = ("ADMIN", "DIRECTOR", "REGISTRAR", "MANAGER_ALL")

# Разделы, которые роль видит (ключи матрицы `access`), и уровень.
SECTIONS: dict[str, dict[str, str]] = {
    "REGISTRAR": {
        "dashboard.queue": "full",
        "crm.leads": "read",
        "crm.leads.triage": "full",
        "crm.clients": "read",
        "eds.inbox": "read",
        "eds.inbox.register": "full",
        "eds.projects": "read",
        "eds.memo.create": "full",
        "chats.internal": "full",
        "chats.external": "read",
    },
    "MANAGER_ALL": {
        "dashboard.queue": "full",
        "crm.leads": "full",
        "crm.clients": "full",
        "eds.inbox": "read",
        "eds.drafts": "read",
        "eds.projects": "full",
        "eds.payments": "full",
        "eds.memo.create": "full",
        "erp.calc": "full",
        "erp.calc.goods": "full",
        "erp.calc.services": "full",
        "erp.stock": "full",
        "chats.internal": "full",
        "chats.external": "full",
    },
}

# Действие -> право бэкенда (CRM `ресурс:действие`, ERP или EDS код) и роли, которым оно положено.
ACTIONS: dict[str, tuple[str, set[str]]] = {
    # D17G-1 (DECISIONS 2026-11-01 п. 1): делопроизводитель — разбор и передача; «Забрать», ответ
    # клиенту, «Вернуть боту» и «Передать коллеге» — менеджер-универсал.
    "забрать лида": ("crm:leads:take", {"MANAGER_ALL"}),
    "вести лида (вернуть боту, передать коллеге)": ("crm:leads:work", {"MANAGER_ALL"}),
    "ответить лиду": ("crm:leads:reply", {"MANAGER_ALL"}),
    "разобрать и передать менеджеру": ("crm:leads:triage", {"REGISTRAR"}),
    "читать лидов": ("crm:leads:read", {"REGISTRAR", "MANAGER_ALL", "DIRECTOR"}),
    "ответить клиенту в переписке": ("crm:chats:reply", {"MANAGER_ALL"}),
    "создать заявку": ("erp:deal.manage", {"MANAGER_ALL", "DIRECTOR"}),
    "отправить КП клиенту": ("erp:quote.send", {"MANAGER_ALL", "DIRECTOR"}),
    "виза расчёта: товары": ("erp:quote.visa_goods", {"MANAGER_ALL", "DIRECTOR"}),
    "виза расчёта: услуги": ("erp:quote.visa_services", {"MANAGER_ALL", "DIRECTOR"}),
    "снабжение и закупки": ("erp:supply.manage", {"MANAGER_ALL", "DIRECTOR"}),
    "договор": ("erp:contract.manage", {"MANAGER_ALL", "DIRECTOR"}),
    "акт": ("erp:fulfillment.act", {"MANAGER_ALL", "DIRECTOR"}),
    "выставить счёт": ("erp:finance.invoice", {"MANAGER_ALL"}),
    "подтвердить оплату (счёт ERP)": ("erp:finance.payment", {"MANAGER_ALL"}),
    "подтвердить оплату служебки": ("eds:payments.confirm", {"MANAGER_ALL"}),
    "зарегистрировать входящее": ("eds:letters.register", {"REGISTRAR", "DIRECTOR"}),
    "наложить резолюцию": ("eds:letters.resolve", {"DIRECTOR"}),
    "читать входящие": ("eds:letters.read", {"REGISTRAR", "MANAGER_ALL", "DIRECTOR"}),
    "одобрить КП": ("eds:approvals.decide", {"DIRECTOR"}),
    "согласовать служебку": ("eds:memos.approve", {"DIRECTOR"}),
    "роли и сотрудники": ("crm:users:write", {"ADMIN"}),
}


def _rights(code: str) -> set[str]:
    """Права по матрице роли. Суперпользователь ERP у системного администратора (до C2,
    `erp_access_for`) — техническая учётка, не бизнес-действие: в матрицу пилота не входит."""
    grant = make_grant(code)
    derived = derive_access([grant])
    return (
        {f"crm:{res}:{act}" for res, act in derived.crm_permissions}
        | {f"erp:{p}" for p in derived.erp_permissions}
        | {f"eds:{p}" for p in eds_permissions_of([grant])}
    )


def test_the_four_pilot_roles_exist_as_catalog_rows() -> None:
    codes = {row["code"] for row in default_roles()}
    assert {"ADMIN", "DIRECTOR", "tpl:REGISTRAR", "tpl:MANAGER_ALL"} <= codes
    names = {row["code"]: row["name"] for row in default_roles()}
    assert names["tpl:REGISTRAR"] == "Делопроизводитель"
    assert names["tpl:MANAGER_ALL"] == "Менеджер-универсал"


@pytest.mark.parametrize("code", list(SECTIONS))
def test_pilot_template_sections(code: str) -> None:
    assert dict(make_grant(code).access) == SECTIONS[code]


@pytest.mark.parametrize("action", list(ACTIONS))
def test_pilot_action_matrix(action: str) -> None:
    right, holders = ACTIONS[action]
    got = {code for code in PILOT if right in _rights(code)}
    assert got == holders, action


def test_registrar_registers_but_never_resolves() -> None:
    """SPEC-v3 §3.2a «Права»: «регистрировать входящие» ≠ «резолюция»; назначения в ERP — нет."""
    rights = _rights("REGISTRAR")
    assert "eds:letters.register" in rights
    assert not rights & {"eds:letters.resolve", "erp:deal.assign", "erp:deal.manage"}


def test_registrar_hands_leads_over_but_never_answers_the_client() -> None:
    """D17G-1: первая линия не забирает лида и не пишет клиенту — ни через реестр, ни через чаты."""
    rights = _rights("REGISTRAR")
    assert "crm:leads:triage" in rights
    assert not rights & {
        "crm:leads:take",
        "crm:leads:work",
        "crm:leads:reply",
        "crm:leads:assist",
        "crm:chats:reply",
        "crm:chats:assist",
    }


def test_the_all_round_manager_holds_both_calc_visas_and_the_accountant_work() -> None:
    """W-1: визу услуг на пилоте ставит менеджер-универсал; бухгалтерия — у него же (2026-10-29)."""
    rights = _rights("MANAGER_ALL")
    assert {"erp:quote.visa_goods", "erp:quote.visa_services", "eds:payments.confirm"} <= rights
    assert "eds:letters.resolve" not in rights
    assert derive_access([make_grant("MANAGER_ALL")]).restricted_fields == (
        "cost_margin",
        "supplier_prices",
    )
