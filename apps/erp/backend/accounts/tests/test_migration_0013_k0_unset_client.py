"""Миграция accounts/0013 на данных (K0): поставщики без клиентской истории теряют CLIENT, остальные — нет.

Настоящий прогон: `MigrationExecutor` откатывает `accounts` к 0012, данные пишутся историческими моделями, затем
0013 применяется заново и откатывается ещё раз. Всё в транзакции теста.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db

#: Состояние «до»: сама 0013 откатывается, остальные приложения остаются на листьях, от которых она зависит.
BEFORE = [
    ("accounts", "0012_finance_view_permission"),
    ("parties", "0008_contact_archived_at"),
    ("integration", "0010_prune_snapshot_quote_final_approval"),
    ("sales", "0011_contract_status_v3"),
    ("finance", "0004_payment_confirmation"),
    ("portal", "0006_portalupload_private_storage"),
    ("documents", "0003_initial"),
]
AFTER = [("accounts", "0013_k0_unset_client_on_suppliers")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def _type(apps, code):
    return apps.get_model("parties", "CompanyType").objects.get_or_create(code=code, defaults={"name": code})[0]


def _company(apps, name, inn, *codes):
    company = apps.get_model("parties", "Company").objects.create(name=name, inn=inn)
    company.types.add(*[_type(apps, code) for code in codes])
    return company


def _codes(apps, company):
    return set(apps.get_model("parties", "Company").objects.get(pk=company.pk).types.values_list("code", flat=True))


@pytest.fixture
def world(settings):
    settings.OWN_COMPANY_ID = None
    old = _migrate(BEFORE)
    Deal = old.get_model("sales", "Deal")
    w = {
        "idle": _company(old, "Idle Supplier", "700000001", "SUPPLIER", "CLIENT"),
        "maker": _company(old, "Idle Maker", "700000002", "MANUFACTURER", "CLIENT"),
        "with_deal": _company(old, "Supplier With Deal", "700000003", "SUPPLIER", "CLIENT"),
        "mapped": _company(old, "Supplier From CRM", "700000004", "SUPPLIER", "CLIENT"),
        "contact_deal": _company(old, "Supplier Contact Deal", "700000005", "SUPPLIER", "CLIENT"),
        "client": _company(old, "Plain Client", "700000006", "CLIENT"),
        "both_only_supplier": _company(old, "Already Supplier Only", "700000007", "SUPPLIER"),
    }
    Deal.objects.create(title="Сделка поставщика", company=w["with_deal"])
    old.get_model("integration", "CrmClientMapping").objects.create(crm_client_id=991, company=w["mapped"])
    contact = old.get_model("parties", "Contact").objects.create(company=w["contact_deal"], name="Контакт")
    Deal.objects.create(title="Сделка контакта", contact=contact)
    return w


def test_idle_suppliers_lose_client_and_the_rest_keep_it(world):
    new = _migrate(AFTER)

    assert _codes(new, world["idle"]) == {"SUPPLIER"}
    assert _codes(new, world["maker"]) == {"MANUFACTURER"}
    assert _codes(new, world["with_deal"]) == {"SUPPLIER", "CLIENT"}, "есть сделка — клиент"
    assert _codes(new, world["mapped"]) == {"SUPPLIER", "CLIENT"}, "есть клиент CRM — клиент"
    assert _codes(new, world["contact_deal"]) == {"SUPPLIER", "CLIENT"}, "сделка по контакту — клиент"
    assert _codes(new, world["client"]) == {"CLIENT"}
    assert _codes(new, world["both_only_supplier"]) == {"SUPPLIER"}


def test_own_company_loses_client_even_with_history(world, settings):
    settings.OWN_COMPANY_ID = world["with_deal"].pk  # у неё есть сделка, но она своя

    new = _migrate(AFTER)

    assert _codes(new, world["with_deal"]) == {"SUPPLIER"}


def test_reverse_restores_client_exactly_for_the_same_companies(world):
    _migrate(AFTER)

    old = _migrate(BEFORE)

    assert _codes(old, world["idle"]) == {"SUPPLIER", "CLIENT"}
    assert _codes(old, world["maker"]) == {"MANUFACTURER", "CLIENT"}
    assert _codes(old, world["both_only_supplier"]) == {"SUPPLIER"}, "ему CLIENT не снимали — и не возвращаем"
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('accounts_k0_client_unset')")
        assert cursor.fetchone()[0] is None, "служебная таблица удалена"


def test_migration_on_a_database_without_candidates_does_nothing():
    _migrate(BEFORE)

    _migrate(AFTER)
    _migrate(BEFORE)
    _migrate(AFTER)
