"""ЗАЯВ-1: реестр заявок — состояния «В работе / Закрытые / Все», поиск, страницы, видимость, клиент для «по образцу»
(`GET /api/v1/calc/tasks/?state=`, карточка заявки)."""

from __future__ import annotations

import pytest
from integration.models import CrmClientMapping

from crm.models import Deal, DealStage
from crm.tests.test_calc import _api, _url, _user, world  # noqa: F401 — фикстура world

pytestmark = pytest.mark.django_db

TASKS = "/api/v1/calc/tasks/"


def _close(world, code="CLOSED_LOST"):  # noqa: F811
    Deal.objects.filter(pk=world["deal"].pk).update(stage=DealStage.objects.get(code=code))


def _numbers(response):
    return [row["deal"]["number"] for row in response.json()["results"]]


def test_state_tabs_split_open_and_closed_requests_and_count(world):  # noqa: F811
    api = _api(world["supply"])
    assert api.get(TASKS).json()["results"] and "count" not in api.get(TASKS).json()  # без state — как было
    assert api.get(TASKS, {"state": "open"}).json()["count"] == 1
    assert api.get(TASKS, {"state": "closed"}).json() == {"results": [], "count": 0}
    _close(world)
    assert api.get(TASKS, {"state": "open"}).json()["count"] == 0
    closed = api.get(TASKS, {"state": "closed"}).json()
    assert closed["count"] == 1 and closed["results"][0]["deal"]["stage_code"] == "CLOSED_LOST"
    assert api.get(TASKS, {"state": "all"}).json()["count"] == 1
    _close(world, "CONTRACT_SIGNED")  # стала проектом — тоже «Закрытые»
    assert api.get(TASKS, {"state": "closed"}).json()["count"] == 1


def test_rows_of_the_registry_carry_crm_client_for_copy(world):  # noqa: F811
    CrmClientMapping.objects.create(company=world["deal"].company, crm_client_id=77)
    (row,) = _api(world["supply"]).get(TASKS, {"state": "all"}).json()["results"]
    assert row["crm_client_id"] == 77


def test_hidden_error_and_test_requests_stay_out_of_closed_and_all(world):  # noqa: F811
    _close(world)
    Deal.objects.filter(pk=world["deal"].pk).update(hidden_in_lists=True)
    api = _api(world["supply"])
    assert api.get(TASKS, {"state": "closed"}).json()["count"] == 0
    assert api.get(TASKS, {"state": "all"}).json()["count"] == 0


def test_search_by_number_client_and_text_and_paging(world):  # noqa: F811
    _close(world)
    api = _api(world["supply"])
    deal = Deal.objects.get(pk=world["deal"].pk)
    for needle in (deal.number, "Пример Логистик", "стрелочных перевода", "ВХ-104"):
        assert api.get(TASKS, {"state": "all", "q": needle}).json()["count"] == 1, needle
    assert api.get(TASKS, {"state": "all", "q": "нет-такого"}).json() == {"results": [], "count": 0}
    page = api.get(TASKS, {"state": "all", "limit": 1, "offset": 1}).json()
    assert page["results"] == [] and page["count"] == 1


def test_closed_requests_of_others_are_not_opened_to_non_staff_and_mine_narrows(world):  # noqa: F811
    _close(world)
    outsider = _user("buyer2@client.test")
    for state in ("open", "closed", "all"):
        assert _api(outsider).get(TASKS, {"state": state, "q": "ООО"}).status_code == 403
    # «Мои»: исполнитель резолюции видит свою закрытую, сотрудник без назначения — нет
    assert _api(world["supply"]).get(TASKS, {"state": "closed", "mine": 1}).json()["count"] == 1
    assert _api(world["accountant"]).get(TASKS, {"state": "closed", "mine": 1}).json()["count"] == 0


def test_request_card_names_crm_client_for_copy(world):  # noqa: F811
    CrmClientMapping.objects.create(company=world["deal"].company, crm_client_id=77)
    api = _api(world["supply"])
    assert api.get(_url(world, "request/")).json()["request"]["crm_client_id"] == 77
