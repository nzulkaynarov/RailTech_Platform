"""РЕЗ-1: «Резолюция перед расчётом» — настройка компании «Правила работы · Продажи», а не код.

Три значения: `always` (по умолчанию — как раньше: письмо директору у каждой заявки), `cabinet_letters` (письмо только у
заявок из Кабинета; заявка, заведённая сотрудником или переданная из CRM, идёт сразу в расчёт) и `never`. Когда резолюция
не нужна, ERP сам ставит задание расчёта ответственному (обе зоны виз), переводит сделку в «Расчёт» и сообщает EDS флагом
`resolution_required=false` в `request.created` — письмо директору не заводится. Нет ответственного — прежний путь.
"""

from __future__ import annotations

import pytest
from integration.services import events
from integration.tests import bus_support
from integration.tests.test_client_requests import (  # noqa: F401  (фикстуры и помощники того же шва)
    _body,
    _create,
    _handoff,
    _manager,
    api,
    integration_env,
)
from parties.models import CompanySettings

from accounts.models import Company, CompanyMember, CustomUser, WorkspaceRole
from accounts.testing import make_own_company
from crm.models import CalcTask, Deal

pytestmark = pytest.mark.django_db


@pytest.fixture
def own(settings):
    company = Company.objects.create(name="Своя", inn="500000009")
    user = CustomUser.objects.create_user(email="own@x.test", username="own@x.test", password=None, is_active=True)
    role = WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "m"})[0]
    CompanyMember.objects.create(user=user, company=company, role=role)
    make_own_company(company)
    settings.OWN_COMPANY_ID = company.pk
    return company


def mode(own_company, value):
    CompanySettings.objects.update_or_create(company=own_company, defaults={"request_resolution": value})


def request_payload():
    return bus_support.only("request.created")["data"]["payload"]


# ── по умолчанию — как раньше ─────────────────────────────────────────────────────────────────────────────────────


def test_default_is_always_resolution_and_no_calc_task(api, own):  # noqa: F811
    _handoff(api)
    _manager()
    deal = Deal.objects.get(pk=_create(api, _body()).json()["erp_request_id"])

    assert request_payload().get("resolution_required", True) is True
    assert not CalcTask.objects.filter(deal=deal).exists()
    assert deal.stage.code == "DRAFT"


def test_always_keeps_the_letter_for_every_source(api, own):  # noqa: F811
    mode(own, "always")
    _handoff(api)
    _manager()
    _create(api, _body())
    assert request_payload().get("resolution_required", True) is True
    assert CalcTask.objects.count() == 0


# ── «только Кабинет и письма» ──────────────────────────────────────────────────────────────────────────────────────


def test_cabinet_letters_sends_a_crm_request_straight_to_calculation(api, own):  # noqa: F811
    mode(own, "cabinet_letters")
    _handoff(api)
    manager = _manager()

    deal = Deal.objects.get(pk=_create(api, _body()).json()["erp_request_id"])

    event = bus_support.only("request.created")
    bus_support.assert_matches_contract(event)
    assert event["data"]["payload"]["resolution_required"] is False
    task = CalcTask.objects.get(deal=deal)
    assert task.eds_letter_id is None and task.letter_number == deal.number
    assert {(a.zone, a.user_id) for a in task.assignees.all()} == {("goods", manager.pk), ("services", manager.pk)}
    deal.refresh_from_db()
    assert deal.stage.code == "CALCULATING"


def test_cabinet_letters_still_asks_for_a_resolution_on_a_cabinet_request(api, own):  # noqa: F811
    mode(own, "cabinet_letters")
    _handoff(api)
    _manager()
    deal = Deal.objects.get(pk=_create(api, _body()).json()["erp_request_id"])
    CalcTask.objects.all().delete()
    bus_support.reset()

    events.publish_request_created(deal, source="cabinet", erp_request_id=deal.pk, crm_client_id=1001)

    assert request_payload().get("resolution_required", True) is True
    assert not CalcTask.objects.filter(deal=deal).exists()


# ── «не нужна» ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_never_skips_the_resolution_even_for_a_cabinet_request(api, own):  # noqa: F811
    mode(own, "never")
    _handoff(api)
    manager = _manager()
    deal = Deal.objects.get(pk=_create(api, _body()).json()["erp_request_id"])
    CalcTask.objects.all().delete()
    Deal.objects.filter(pk=deal.pk).update(stage=deal.stage)  # вернуть в исходное для повторной публикации
    bus_support.reset()

    events.publish_request_created(deal, source="cabinet", erp_request_id=deal.pk, crm_client_id=1001)

    assert request_payload()["resolution_required"] is False
    assert CalcTask.objects.get(deal=deal).assignees.filter(user=manager).count() == 2


def test_no_responsible_person_falls_back_to_the_resolution(api, own):  # noqa: F811
    """Некому ставить расчёт — заявка не повисает: прежний путь через директора."""
    mode(own, "never")
    _handoff(api)
    body = _body(owner={"crm_user_id": 999, "name": "Нет в ERP"})
    deal = Deal.objects.get(pk=_create(api, body).json()["erp_request_id"])
    assert deal.manager_id is None

    payload = request_payload()
    assert payload["manager_crm_user_id"] == 999
    # менеджер CRM известен, пользователя ERP нет: расчёт ставится на сотрудника CRM без пользователя ERP (предупреждение)
    assert payload["resolution_required"] is False
    assert CalcTask.objects.get(deal=deal).assignees.filter(user__isnull=True, crm_user_id=999).count() == 2


def test_deal_without_any_manager_keeps_the_letter(api, own):  # noqa: F811
    mode(own, "always")
    _handoff(api)
    deal = Deal.objects.get(pk=_create(api, _body()).json()["erp_request_id"])
    Deal.objects.filter(pk=deal.pk).update(manager=None, assigned_to=None)
    deal.refresh_from_db()
    mode(own, "never")
    bus_support.reset()

    events.publish_request_created(deal, source="crm", erp_request_id=deal.pk, crm_client_id=1001)

    assert request_payload().get("resolution_required", True) is True
    assert not CalcTask.objects.filter(deal=deal).exists()


def test_direct_calculation_is_idempotent(api, own):  # noqa: F811
    mode(own, "never")
    _handoff(api)
    _manager()
    deal = Deal.objects.get(pk=_create(api, _body()).json()["erp_request_id"])

    events.publish_request_created(deal, source="crm", erp_request_id=deal.pk, crm_client_id=1001)

    assert CalcTask.objects.filter(deal=deal).count() == 1


def test_setting_accepts_only_the_three_modes(own, monkeypatch):  # noqa: F811
    from accounts.services import company_settings
    from accounts.services.company_settings import update_company_settings

    monkeypatch.setattr(company_settings, "is_company_owner", lambda user, company: True)
    row, error = update_company_settings(None, own, {"request_resolution": "cabinet_letters"})
    assert error is None and row.request_resolution == "cabinet_letters" and mode_of() == "cabinet_letters"
    _, error = update_company_settings(None, own, {"request_resolution": "sometimes"})
    assert error == "BAD_REQUEST_RESOLUTION" and mode_of() == "cabinet_letters"


def mode_of():
    from crm.services import request_resolution

    return request_resolution.mode()
