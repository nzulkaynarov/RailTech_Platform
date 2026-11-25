"""РЕЗ-1: «Резолюция перед расчётом» — настройка компании «Правила работы · Продажи», а не код.

Три значения: `always` (по умолчанию — как раньше: письмо директору у каждой заявки), `client_own` («только заявки,
которые клиент подал сам»: Кабинет, бот, передача из лида, заявка по письму клиента; заведённая сотрудником идёт сразу в
расчёт) и `never`. Когда резолюция не нужна, ERP сам ставит задание расчёта ответственному (обе зоны виз, срок, уведомление),
переводит сделку в «Расчёт», кладёт файл письма клиента в исходники заявки и сообщает EDS флагом `resolution_required=false`
в `request.created` — письмо директору не заводится. Нет ответственного с пользователем ERP — прежний путь с письмом.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from integration.models import CrmUserMapping, DeferredRequestEvent
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
from integration.tests.test_handoff import handoff, payload
from parties.models import CompanySettings

from accounts.models import Company, CompanyMember, CustomUser, WorkspaceRole
from accounts.testing import make_own_company
from crm.models import CalcTask, Deal
from crm.services import request_resolution
from crm.services.draft_quote import deal_request_files
from notifications.models import Notification

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


@pytest.fixture
def letter_file(monkeypatch):
    """EDS отдаёт файл письма клиента; тест подменяет сервисный вызов."""
    calls = []

    def fake(file_id, created_by):
        calls.append((file_id, created_by))
        return ("письмо клиента.pdf", b"%PDF-1.4 client letter")

    monkeypatch.setattr(request_resolution, "fetch_letter_file", fake)
    return calls


def mode(own_company, value):
    CompanySettings.objects.update_or_create(company=own_company, defaults={"request_resolution": value})


def request_payload():
    return bus_support.only("request.created")["data"]["payload"]


def letter_is_created():
    return request_payload().get("resolution_required", True) is True


def new_deal(api, **changes):  # noqa: F811
    changes.setdefault("letter_file_id", None)  # файл письма — только там, где он проверяется
    return Deal.objects.get(pk=_create(api, _body(**changes)).json()["erp_request_id"])


def republish(deal, source, **kwargs):
    """Повторная публикация заявки из источника `source` на «чистой» сделке (без задания, стадия — исходная)."""
    CalcTask.objects.all().delete()
    bus_support.reset()
    events.publish_request_created(deal, source=source, erp_request_id=deal.pk, crm_client_id=1001, **kwargs)


# ── по умолчанию — как раньше ─────────────────────────────────────────────────────────────────────────────────────


def test_default_is_always_resolution_and_no_calc_task(api, own):  # noqa: F811
    _handoff(api)
    _manager()
    deal = new_deal(api)

    assert letter_is_created()
    assert not CalcTask.objects.filter(deal=deal).exists()
    assert deal.stage.code == "DRAFT"


def test_always_keeps_the_letter_for_every_source(api, own):  # noqa: F811
    mode(own, "always")
    _handoff(api)
    _manager()
    deal = new_deal(api)
    for source in ("crm", "cabinet", "erp"):
        republish(deal, source)
        assert letter_is_created() and not CalcTask.objects.exists()


# ── «только заявки, которые клиент подал сам» ─────────────────────────────────────────────────────────────────────


def test_client_own_staff_request_in_erp_goes_straight_to_calculation(api, own):  # noqa: F811
    mode(own, "client_own")
    _handoff(api)
    manager = _manager()
    deal = new_deal(api)

    republish(deal, "erp")  # «Создать заявку» в ERP: заведена сотрудником

    assert request_payload()["resolution_required"] is False
    task = CalcTask.objects.get(deal=deal)
    assert {(a.zone, a.user_id) for a in task.assignees.all()} == {("goods", manager.pk), ("services", manager.pk)}
    deal.refresh_from_db()
    assert deal.stage.code == "CALCULATING"


def test_client_own_crm_request_without_the_client_letter_skips_the_resolution(api, own):  # noqa: F811
    mode(own, "client_own")
    _handoff(api)
    _manager()
    deal = new_deal(api)  # CRM «Создать заявку» без письма клиента

    event = bus_support.only("request.created")
    bus_support.assert_matches_contract(event)
    assert event["data"]["payload"]["resolution_required"] is False
    assert CalcTask.objects.filter(deal=deal).exists()


def test_client_own_keeps_the_letter_for_cabinet_bot_handoff_and_a_request_with_the_client_letter(
    api, own, letter_file  # noqa: F811
):
    mode(own, "client_own")
    _handoff(api)
    _manager()
    deal = new_deal(api)
    republish(deal, "cabinet")
    assert letter_is_created() and not CalcTask.objects.exists()
    republish(deal, "crm", client_initiated=True)  # передача из лида, бот
    assert letter_is_created() and not CalcTask.objects.exists()
    republish(deal, "crm", letter_file_id="3f2c1a7e-5b9d-4c8e-9a1f-0d2e3c4b5a69")  # заявка по письму клиента
    assert letter_is_created() and not CalcTask.objects.exists()
    assert letter_file == []  # файл тянется только когда письма не будет


def test_client_own_lead_handoff_with_a_request_keeps_the_letter(api, own):  # noqa: F811
    mode(own, "client_own")
    _manager(101)
    response = handoff(api, payload(create_request=True))
    assert response.status_code == 201, response.content
    assert letter_is_created() and not CalcTask.objects.exists()


# ── «не нужна» ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_never_skips_even_for_cabinet_with_notification_and_due_date(api, own):  # noqa: F811
    mode(own, "never")
    _handoff(api)
    manager = _manager()
    deal = new_deal(api)
    Notification.objects.all().delete()

    republish(deal, "cabinet")

    assert request_payload()["resolution_required"] is False
    task = CalcTask.objects.get(deal=deal)
    assert task.due == timezone.localdate() + datetime.timedelta(days=request_resolution.DIRECT_DUE_DAYS)
    note = Notification.objects.get(user=manager, event_code="deal.calc_assigned")
    assert deal.number in note.message and "Резолюция" not in note.message
    assert note.link == f"#deal/{deal.id}"


def test_direct_task_has_no_letter_and_is_named_by_the_deal(api, own):  # noqa: F811
    mode(own, "never")
    _handoff(api)
    _manager()
    deal = new_deal(api)

    task = CalcTask.objects.get(deal=deal)
    assert task.eds_letter_id is None and task.letter_number == "" and not task.has_resolution
    assert task.label == deal.number


def test_direct_calculation_is_idempotent(api, own):  # noqa: F811
    mode(own, "never")
    _handoff(api)
    _manager()
    deal = new_deal(api)

    events.publish_request_created(deal, source="crm", erp_request_id=deal.pk, crm_client_id=1001)

    assert CalcTask.objects.filter(deal=deal).count() == 1


def test_partner_request_released_after_matching_honours_the_setting(api, own):  # noqa: F811
    mode(own, "never")
    _handoff(api)
    manager = _manager()
    deal = new_deal(api)
    CalcTask.objects.all().delete()
    Deal.objects.filter(pk=deal.pk).update(manager=manager)
    DeferredRequestEvent.objects.create(deal=deal)
    bus_support.reset()

    from integration.services.partner_client import release_deferred_requests

    assert release_deferred_requests(deal.company, 1001) == 1

    assert request_payload()["source"] == "cabinet" and request_payload()["resolution_required"] is False
    assert CalcTask.objects.filter(deal=deal).exists()


# ── нет ответственного — прежний путь, никто не остаётся с заданием «в никуда» ────────────────────────────────────


def test_no_responsible_person_falls_back_to_the_resolution_letter(api, own):  # noqa: F811
    """Сотрудник CRM без пользователя ERP — «ответственного нет»: письмо директору, а не задание без исполнителя."""
    mode(own, "never")
    _handoff(api)
    deal = new_deal(api, owner={"crm_user_id": 999, "name": "Нет в ERP"})

    assert deal.manager_id is None
    assert request_payload()["manager_crm_user_id"] == 999
    assert letter_is_created()
    assert not CalcTask.objects.exists()
    from sales.models import CalcTaskAssignee

    assert not CalcTaskAssignee.objects.exists()


def test_inactive_erp_user_is_not_responsible(api, own):  # noqa: F811
    mode(own, "never")
    _handoff(api)
    manager = _manager()
    CustomUser.objects.filter(pk=manager.pk).update(is_active=False)
    deal = new_deal(api)

    assert letter_is_created() and not CalcTask.objects.filter(deal=deal).exists()


def test_deal_without_any_manager_keeps_the_letter(api, own):  # noqa: F811
    mode(own, "always")
    _handoff(api)
    deal = new_deal(api)
    Deal.objects.filter(pk=deal.pk).update(manager=None, assigned_to=None)
    deal.refresh_from_db()
    mode(own, "never")

    republish(deal, "crm")

    assert letter_is_created() and not CalcTask.objects.filter(deal=deal).exists()


# ── файл письма клиента виден расчёту ─────────────────────────────────────────────────────────────────────────────


def test_client_letter_file_is_a_request_file_of_the_calculation_when_the_letter_is_skipped(
    api, own, letter_file  # noqa: F811
):
    mode(own, "never")
    _handoff(api)
    manager = _manager()
    deal = new_deal(api, letter_file_id="3f2c1a7e-5b9d-4c8e-9a1f-0d2e3c4b5a69")

    assert request_payload()["resolution_required"] is False
    assert letter_file == [("3f2c1a7e-5b9d-4c8e-9a1f-0d2e3c4b5a69", 101)]
    files = deal_request_files(deal)
    assert [f["name"] for f in files] == ["письмо клиента.pdf"]
    assert CalcTask.objects.get(deal=deal).assignees.filter(user=manager).exists()


def test_unreachable_letter_file_keeps_the_letter_instead_of_losing_it(api, own, monkeypatch):  # noqa: F811
    mode(own, "never")
    monkeypatch.setattr(request_resolution, "fetch_letter_file", lambda file_id, created_by: None)
    _handoff(api)
    _manager()
    deal = new_deal(api, letter_file_id="3f2c1a7e-5b9d-4c8e-9a1f-0d2e3c4b5a69")

    assert letter_is_created() and not CalcTask.objects.filter(deal=deal).exists()
    assert deal_request_files(deal) == []


# ── значение настройки ────────────────────────────────────────────────────────────────────────────────────────────


def test_setting_accepts_only_the_three_modes(own, monkeypatch):  # noqa: F811
    from accounts.services import company_settings
    from accounts.services.company_settings import update_company_settings

    monkeypatch.setattr(company_settings, "is_company_owner", lambda user, company: True)
    row, error = update_company_settings(None, own, {"request_resolution": "client_own"})
    assert error is None and row.request_resolution == "client_own" and request_resolution.mode() == "client_own"
    _, error = update_company_settings(None, own, {"request_resolution": "sometimes"})
    assert error == "BAD_REQUEST_RESOLUTION" and request_resolution.mode() == "client_own"


def test_unknown_crm_user_is_not_mapped(api, own):  # noqa: F811
    assert not CrmUserMapping.objects.filter(crm_user_id=999).exists()
