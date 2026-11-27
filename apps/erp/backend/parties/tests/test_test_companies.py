"""ТЕСТ-1: отметка «Тестовая» у контрагента — действие, журнал, шина, исключение из рабочих списков и счётчиков.

`POST|DELETE /api/v1/parties/organizations/{id}/test/`; тестовая компания уходит из списков по умолчанию и видна по
`?test=only`, но открывается по номеру, письма и вход в кабинет у неё работают. Мир — `inventory.tests.support`.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from finance.services import receivables
from integration.models import CrmClientMapping
from integration.tests.bus_support import published
from inventory.tests.support import api, make_world
from parties import test_companies
from parties.models import Company, Contact
from portal.desk import service_counterparty as counterparty
from portal.services.access import company_access
from supply.models import SupplierOrder
from supply.services import tasks as supply_tasks

from core.views.stats import PlatformDashboardView
from crm.models import ActivityLog, Deal, DealStage, Invoice, InvoiceStatus

pytestmark = pytest.mark.django_db

URL = "/api/v1/parties/organizations/"


@pytest.fixture
def world():
    world = make_world()
    # два клиента с одинаковой историей: настоящий и тестовый
    world["real"] = world["client"]
    world["fake"] = Company.objects.create(name="ООО Пробная Компания", inn="6600000399")
    world["fake"].types.set(world["real"].types.all())
    Contact.objects.create(company=world["fake"], name="Тест", email="t@fake.example", is_primary=True, can_act=True)
    return world


def _mark(world, company):
    return api(world["supply"]).post(f"{URL}{company.pk}/test/")


def _journal(company):
    return list(
        ActivityLog.objects.filter(entity_type="company", entity_id=company.pk, event_code="admin.company.updated")
        .order_by("id")
        .values_list("action", flat=True)
    )


def _results(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) else body


# ── действие ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_mark_and_unmark_are_audited_and_repeat_is_safe(world):
    company = world["fake"]
    response = _mark(world, company)
    assert response.status_code == 200, response.content
    assert response.json()["is_test"] is True
    company.refresh_from_db()
    assert company.is_test is True
    assert _mark(world, company).status_code == 200  # повтор безопасен
    assert _journal(company) == ["Контрагент отмечен как тестовый"]

    removed = api(world["supply"]).delete(f"{URL}{company.pk}/test/")
    assert removed.status_code == 200 and removed.json()["is_test"] is False
    assert api(world["supply"]).delete(f"{URL}{company.pk}/test/").status_code == 200
    assert _journal(company) == ["Контрагент отмечен как тестовый", "С контрагента снята отметка «Тестовая»"]


def test_only_those_who_edit_counterparties_may_mark(world):
    assert api(world["reader"]).post(f"{URL}{world['fake'].pk}/test/").status_code == 403
    world["fake"].refresh_from_db()
    assert world["fake"].is_test is False


def test_the_mark_goes_to_the_bus_in_the_company_snapshot(world):
    company = world["fake"]
    CrmClientMapping.objects.create(crm_client_id=9001, company=company)
    before = len(published("company.updated"))
    counterparty.set_test(company, True, actor=world["supply"])
    events = published("company.updated")
    assert len(events) == before + 1
    assert events[-1]["data"]["company"]["is_test"] is True
    counterparty.set_test(company, False, actor=world["supply"])
    assert published("company.updated")[-1]["data"]["company"]["is_test"] is False


def test_a_contact_of_a_test_company_keeps_the_cabinet(world):
    company = world["fake"]
    roles_before, _ = company_access(company.pk)
    counterparty.set_test(company, True, actor=world["supply"])
    roles_after, _ = company_access(company.pk)
    assert roles_after == roles_before and "client" in roles_after


# ── списки: по умолчанию без тестовых, по фильтру — только они ──────────────────────────────────────────────────────


def _deal(company, title):
    return Deal.objects.create(title=title, company=company, stage=DealStage.objects.get(code="DRAFT"))


def test_deals_list_hides_test_companies_by_default_and_shows_them_by_filter(world):
    real, fake = _deal(world["real"], "Рабочая"), _deal(world["fake"], "Пробная")
    counterparty.set_test(world["fake"], True, actor=world["supply"])
    client = api(world["supply"])
    ids = lambda query: {row["id"] for row in _results(client.get(f"/api/v1/crm/deals/{query}"))}  # noqa: E731
    assert ids("") == {real.pk}
    assert ids("?test=only") == {fake.pk}
    assert ids("?test=all") == {real.pk, fake.pk}
    # карточка по номеру открывается
    assert client.get(f"/api/v1/crm/deals/{fake.pk}/").status_code == 200


def test_organizations_list_has_the_test_filter(world):
    counterparty.set_test(world["fake"], True, actor=world["supply"])
    Deal.objects.create(title="Связь", company=world["fake"], stage=DealStage.objects.get(code="DRAFT"))
    client = api(world["supply"])
    names = lambda query: {row["name"] for row in _results(client.get(f"{URL}{query}"))}  # noqa: E731
    assert "ООО Пробная Компания" not in names("")
    assert names("?test=only") == {"ООО Пробная Компания"}
    assert "ООО Пробная Компания" in names("?test=all")
    # карточка тестовой компании открывается
    assert client.get(f"{URL}{world['fake'].pk}/").json()["is_test"] is True


def test_dashboard_counters_do_not_count_test_companies(world):
    _deal(world["real"], "Рабочая")
    _deal(world["fake"], "Пробная")
    before = PlatformDashboardView._get_deal_dashboard_stats()["total"]
    companies_before = PlatformDashboardView._get_company_stats()["total"]
    counterparty.set_test(world["fake"], True, actor=world["supply"])
    assert PlatformDashboardView._get_deal_dashboard_stats()["total"] == before - 1
    assert PlatformDashboardView._get_company_stats()["total"] == companies_before - 1


def test_receivables_counts_and_board_skip_test_companies(world):
    from crm.constants import InvoiceStatusCode

    status = InvoiceStatus.objects.get(code=InvoiceStatusCode.ISSUED)
    for company, number in ((world["real"], "INV-R"), (world["fake"], "INV-F")):
        deal = _deal(company, number)
        Invoice.objects.create(
            deal=deal,
            number=number,
            status=status,
            due_date=date.today() - timedelta(days=3),
            total_incl_vat=Decimal("100.00"),
        )
    day = date.today()
    all_before = sum(receivables.counts(day).values())
    counterparty.set_test(world["fake"], True, actor=world["supply"])
    assert sum(receivables.counts(day).values()) < all_before
    rows, _total = receivables.board(tab="all", day=day)
    assert {row.number for row in rows} == {"INV-R"}
    assert receivables.get_invoice(Invoice.objects.get(number="INV-F").pk) is not None  # карточка открывается


def test_supply_queue_and_orders_skip_test_companies(world):
    def order(supplier):
        body = {"supplier_id": supplier.pk, "lines": [{"product_id": world["rail"].pk, "quantity": 5}]}
        made = api(world["supply"]).post("/api/v1/stock/orders/", body, format="json")
        assert made.status_code == 201, made.content
        return SupplierOrder.objects.get(pk=made.json()["id"])

    real_order, fake_order = order(world["vendor"]), order(world["silent"])
    ids = lambda: {
        row["id"] for row in supply_tasks.supply_tasks(world["supply"]) if row["kind"] == "send_order"
    }  # noqa: E731
    assert ids() == {real_order.pk, fake_order.pk}
    counterparty.set_test(world["silent"], True, actor=world["supply"])
    assert ids() == {real_order.pk}
    listed = api(world["supply"]).get("/api/v1/stock/orders/").json()
    assert {row["id"] for row in listed["results"]} == {real_order.pk}


def test_the_calc_registry_skips_test_companies(world):
    from django.utils import timezone

    from crm.models import CalcTask
    from crm.services import calculation

    for company, title in ((world["real"], "Рабочая"), (world["fake"], "Пробная")):
        deal = _deal(company, title)
        CalcTask.objects.create(deal=deal, resolution_text="Рассчитать", due=date.today(), decided_at=timezone.now())
    total = lambda: calculation.list_tasks_page(world["supply"], state="all")[1]  # noqa: E731
    assert total() == 2
    counterparty.set_test(world["fake"], True, actor=world["supply"])
    assert total() == 1


# ── вспомогательные выборки ─────────────────────────────────────────────────────────────────────────────────────────


def test_scope_modes(world):
    counterparty.set_test(world["fake"], True, actor=world["supply"])
    qs = Company.objects.filter(pk__in=[world["real"].pk, world["fake"].pk])
    assert set(test_companies.scope(qs, {}, "")) == {world["real"]}
    assert set(test_companies.scope(qs, {"test": "only"}, "")) == {world["fake"]}
    assert set(test_companies.scope(qs, {"test": "all"}, "")) == {world["real"], world["fake"]}
    assert set(test_companies.scope(qs, {"test": "junk"}, "")) == {world["real"]}


# ── management command ──────────────────────────────────────────────────────────────────────────────────────────────


def _run(*args):
    out = StringIO()
    call_command("mark_test_companies", *args, stdout=out)
    return out.getvalue()


def test_command_is_a_dry_run_by_default_and_prints_only_counts(world):
    ids = f"{world['fake'].pk},{world['real'].pk},999999"
    text = _run("--ids", ids)
    assert "dry-run" in text and "requested=3" in text and "missing=1" in text and "to_change=2" in text
    assert "ООО" not in text and world["fake"].name not in text
    world["fake"].refresh_from_db()
    assert world["fake"].is_test is False


def test_command_apply_marks_and_is_idempotent(world):
    ids = str(world["fake"].pk)
    assert "changed=1" in _run("--ids", ids, "--apply")
    world["fake"].refresh_from_db()
    assert world["fake"].is_test is True
    assert "changed=0" in _run("--ids", ids, "--apply") and "already=1" in _run("--ids", ids)
    assert "changed=1" in _run("--ids", ids, "--unmark", "--apply")
    world["fake"].refresh_from_db()
    assert world["fake"].is_test is False


def test_command_rejects_garbage_ids():
    with pytest.raises(CommandError):
        _run("--ids", "12,abc")
