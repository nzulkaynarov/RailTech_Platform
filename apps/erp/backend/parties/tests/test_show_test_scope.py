"""ТЕСТ-2: «Показывать тестовые» на стороне ERP — `?test=all` от BFF возвращает тестовые компании в рабочие выборки.

Переключатель решает BFF по профилю сотрудника (CRM `users.show_test`) и добавляет `?test=all`; ERP читает параметр на
запросе: списки и агрегаты по умолчанию без тестовых (ТЕСТ-1), с параметром — с тестовыми, а строки тестовых компаний
несут `is_test`, чтобы клиент нарисовал метку «Тестовая». Мир — `inventory.tests.support`.
"""

from __future__ import annotations

import pytest
from inventory.tests.support import api, make_world
from parties import test_companies
from parties.models import Company
from portal.desk import service_counterparty as counterparty

from crm.models import Deal, DealStage
from notifications.models import Notification
from notifications.services import notify_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    world = make_world()
    world["real"] = world["client"]
    world["fake"] = Company.objects.create(name="ООО Пробная Компания", inn="6600000399")
    world["fake"].types.set(world["real"].types.all())
    counterparty.set_test(world["fake"], True, actor=world["supply"])
    world["fake"].refresh_from_db()
    return world


def _deal(company, title):
    return Deal.objects.create(title=title, company=company, stage=DealStage.objects.get(code="DRAFT"))


def _rows(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) else body


def test_list_with_test_all_has_test_rows_with_the_tag_and_without_it_has_neither(world):
    real, fake = _deal(world["real"], "Рабочая"), _deal(world["fake"], "Пробная")
    client = api(world["supply"])

    hidden = _rows(client.get("/api/v1/crm/deals/"))
    assert {row["id"] for row in hidden} == {real.pk}
    assert all("is_test" not in row for row in hidden)

    shown = _rows(client.get("/api/v1/crm/deals/?test=all"))
    assert {row["id"]: row["is_test"] for row in shown} == {real.pk: False, fake.pk: True}


def test_counters_follow_the_request_scope(world):
    from parties import test_companies

    from core.views.stats import PlatformDashboardView

    _deal(world["real"], "Рабочая")
    _deal(world["fake"], "Пробная")
    without = PlatformDashboardView._get_deal_dashboard_stats()["total"]
    token = test_companies._show_all.set(True)
    try:
        with_test = PlatformDashboardView._get_deal_dashboard_stats()["total"]
        suffix = test_companies.cache_suffix()
    finally:
        test_companies._show_all.reset(token)
    assert with_test == without + 1
    assert (suffix, test_companies.cache_suffix()) == (":test", "")  # агрегаты в кэше разделены по признаку


class _Layer:
    def __init__(self):
        self.groups: list[str] = []

    async def group_send(self, group, message):
        self.groups.append(group)


def test_notifications_of_test_companies_need_the_switch_and_do_not_push_live(world, monkeypatch):
    layer = _Layer()
    monkeypatch.setattr("notifications.services.get_channel_layer", lambda: layer)
    real, fake = _deal(world["real"], "Рабочая"), _deal(world["fake"], "Пробная")
    user = world["supply"]
    notify_user(user=user, title="Рабочая", message="m", deal=real)
    test_one = notify_user(user=user, title="Пробная", message="m", deal=fake)
    assert test_one is not None and Notification.objects.filter(user=user).count() == 2
    assert layer.groups == [f"notifications_{user.pk}"]  # живой пуш только по рабочей сделке

    client = api(user)
    assert [row["title"] for row in _rows(client.get("/api/v1/notifications/"))] == ["Рабочая"]
    shown = {row["title"]: row["is_test"] for row in _rows(client.get("/api/v1/notifications/?test=all"))}
    assert shown == {"Рабочая": False, "Пробная": True}

    # «прочитано всё» без переключателя не трогает скрытое
    client.patch("/api/v1/notifications/mark_all_read/")
    assert Notification.objects.get(title="Пробная").is_read is False
    client.patch("/api/v1/notifications/mark_all_read/?test=all")
    assert Notification.objects.get(title="Пробная").is_read is True


def test_every_push_goes_through_the_one_gate_even_without_notify_user(world, monkeypatch):
    """Места, что создают уведомление сами (задание на расчёт и др.), проходят тот же шлюз: тестовая сделка — без пуша."""
    from django.utils import timezone

    from crm.models import CalcTask
    from crm.services import calc_tasks

    layer = _Layer()
    monkeypatch.setattr("notifications.services.get_channel_layer", lambda: layer)
    for company in (world["real"], world["fake"]):
        deal = _deal(company, "Сделка")
        task = CalcTask.objects.create(
            deal=deal, resolution_text="Рассчитать", due=timezone.now().date(), decided_at=timezone.now()
        )
        calc_tasks._notify_assignee(world["supply"].pk, deal, task)
    assert layer.groups == [f"notifications_{world['supply'].pk}"]
    hidden = api(world["supply"]).get("/api/v1/notifications/")
    assert len(_rows(hidden)) == 1  # уведомление по тестовой сделке скрыто без переключателя
    assert len(_rows(api(world["supply"]).get("/api/v1/notifications/?test=all"))) == 2


def test_live_push_is_sent_only_from_the_central_function():
    """Охрана: прямой `group_send` в канал уведомлений — только в `notifications/services.py` (+ потребители и тесты)."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    allowed = {"notifications/services.py"}
    found = set()
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if "/tests/" in f"/{rel}" or rel.startswith("tests/") or "migrations" in rel or rel.endswith("conftest.py"):
            continue
        if re.search(r"\bgroup_send\(", path.read_text(encoding="utf-8")) and "notifications_" in path.read_text(
            encoding="utf-8"
        ):
            found.add(rel)
    assert found <= allowed, f"живой пуш мимо шлюза: {sorted(found - allowed)}"


def test_scope_does_not_leak_into_the_next_request(world):
    _deal(world["fake"], "Пробная")
    client = api(world["supply"])
    assert len(_rows(client.get("/api/v1/crm/deals/?test=all"))) == 1
    assert _rows(client.get("/api/v1/crm/deals/")) == []


def test_calc_registry_and_projects_carry_the_tag_only_when_shown(world):
    from datetime import date

    from django.utils import timezone

    from crm.models import CalcTask
    from crm.services import calculation, projects

    for company, title in ((world["real"], "Рабочая"), (world["fake"], "Пробная")):
        deal = _deal(company, title)
        CalcTask.objects.create(deal=deal, resolution_text="Рассчитать", due=date.today(), decided_at=timezone.now())
    user = world["supply"]

    def calc_rows() -> dict:
        rows, _total = calculation.list_tasks_page(user, state="all")
        return {row["deal"]["title"]: row["deal"].get("is_test") for row in rows}

    assert calc_rows() == {"Рабочая": None}  # выключено: тестовой заявки нет, поля нет
    token = test_companies._show_all.set(True)
    try:
        assert calc_rows() == {"Рабочая": None, "Пробная": True}
        assert projects.project_row(Deal.objects.get(title="Пробная")).get("is_test") is True
        assert "is_test" not in projects.project_row(Deal.objects.get(title="Рабочая"))
    finally:
        test_companies._show_all.reset(token)
    assert "is_test" not in projects.project_row(Deal.objects.get(title="Пробная"))
