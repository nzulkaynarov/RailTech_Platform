"""РЕЗ-1: «Резолюция перед расчётом» — настройка компании «Правила работы · Продажи», а не код.

Два значения: `always` (по умолчанию — как раньше: письмо директору у каждой заявки) и `never` (не нужна). Путь один для
любого канала. Когда резолюция не нужна, ERP сам ставит задание расчёта ответственному (обе зоны виз, срок,
уведомление), переводит сделку в «Расчёт», забирает файл письма клиента задачей после коммита и сообщает EDS флагом
`resolution_required=false` в `request.created` — письмо директору не заводится. Нет ответственного с действующим
пользователем ERP — прежний путь с письмом.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from integration.models import DeferredRequestEvent
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


def test_default_is_the_resolution_letter_and_no_calc_task(api, own):  # noqa: F811
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


# ── «не нужна»: один путь для любого канала ────────────────────────────────────────────────────────────────────────


def test_never_goes_straight_to_calculation_for_every_source(api, own):  # noqa: F811
    mode(own, "never")
    _handoff(api)
    manager = _manager()
    deal = new_deal(api)
    event = bus_support.only("request.created")
    bus_support.assert_matches_contract(event)
    assert event["data"]["payload"]["resolution_required"] is False
    for source in ("crm", "cabinet", "erp"):
        republish(deal, source)
        assert request_payload()["resolution_required"] is False
        task = CalcTask.objects.get(deal=deal)
        assert {(a.zone, a.user_id) for a in task.assignees.all()} == {("goods", manager.pk), ("services", manager.pk)}
    deal.refresh_from_db()
    assert deal.stage.code == "CALCULATING"


def test_lead_handoff_with_a_request_follows_the_setting(api, own):  # noqa: F811
    mode(own, "never")
    _manager(101)
    response = handoff(api, payload(create_request=True))
    assert response.status_code == 201, response.content
    assert request_payload()["resolution_required"] is False and CalcTask.objects.count() == 1


def test_never_notifies_the_responsible_and_sets_the_due_date(api, own):  # noqa: F811
    mode(own, "never")
    _handoff(api)
    manager = _manager()
    deal = new_deal(api)
    Notification.objects.all().delete()

    republish(deal, "cabinet")

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

FILE = "3f2c1a7e-5b9d-4c8e-9a1f-0d2e3c4b5a69"


@pytest.fixture
def eds_file(monkeypatch):
    """EDS отдаёт файл письма клиента; сервисный вызов подменён, задача идёт сразу после коммита."""
    from integration.services import eds_files
    from integration.tasks import fetch_request_letter_file

    calls = []

    def fake(file_id, created_by):
        calls.append((file_id, created_by))
        return ("письмо клиента.pdf", b"%PDF-1.4 client letter")

    monkeypatch.setattr(eds_files, "fetch_request_file", fake)
    monkeypatch.setattr(fetch_request_letter_file, "delay", lambda *a: fetch_request_letter_file.apply(args=a))
    return calls


def test_client_letter_file_is_fetched_after_commit_and_shown_in_the_calculation(
    api, own, eds_file, django_capture_on_commit_callbacks  # noqa: F811
):
    """Сеть не держит транзакцию заявки: до коммита файла нет и расчёт говорит «загружается»; после — файл в исходниках."""
    mode(own, "never")
    _handoff(api)
    manager = _manager()

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        deal = new_deal(api, letter_file_id=FILE)

    task = CalcTask.objects.get(deal=deal)
    assert request_payload()["resolution_required"] is False
    assert eds_file == [] and task.request_file_pending and deal_request_files(deal) == []
    assert len(callbacks) == 1
    callbacks[0]()

    assert eds_file == [(FILE, 101)]
    task.refresh_from_db()
    assert not task.request_file_pending
    assert [f["name"] for f in deal_request_files(deal)] == ["письмо клиента.pdf"]
    assert task.assignees.filter(user=manager).exists()
    callbacks[0]()  # повтор задачи не кладёт файл второй раз
    assert len(deal_request_files(deal)) == 1


def _pending_deal(api, own):  # noqa: F811
    mode(own, "never")
    _handoff(api)
    _manager()
    deal = new_deal(api, letter_file_id=FILE)
    assert CalcTask.objects.get(deal=deal).request_file_pending
    return deal


def _gave_up(deal, reason):
    from crm.models import ActivityLog

    assert not CalcTask.objects.get(deal=deal).request_file_pending, "расчёт не остаётся в ожидании"
    assert deal_request_files(deal) == []
    entry = ActivityLog.objects.get(deal=deal, event_code="deal.request_file_missing")
    assert entry.event_params == {"reason": reason}


def test_missing_letter_file_stops_waiting_and_leaves_a_journal_note(api, own, monkeypatch):  # noqa: F811
    from integration.services import eds_files
    from integration.tasks import fetch_request_letter_file

    monkeypatch.setattr(eds_files, "fetch_request_file", lambda *a: None)
    deal = _pending_deal(api, own)

    assert fetch_request_letter_file.apply(args=(deal.pk, FILE, 101)).result is False
    _gave_up(deal, "not_found")


def test_eds_down_retries_then_gives_up_without_waiting_forever(api, own, monkeypatch):  # noqa: F811
    from integration.services import eds_files
    from integration.tasks import MAX_RETRIES, fetch_request_letter_file

    def down(*args):
        raise eds_files.EdsFileUnavailable("down")

    monkeypatch.setattr(eds_files, "fetch_request_file", down)
    deal = _pending_deal(api, own)

    assert fetch_request_letter_file.apply(args=(deal.pk, FILE, 101), retries=MAX_RETRIES).result is False
    _gave_up(deal, "eds_unavailable")


def test_broker_down_clears_the_wait_and_leaves_a_journal_note(
    api, own, monkeypatch, django_capture_on_commit_callbacks  # noqa: F811
):
    """Задача не поставилась (брокер недоступен): флаг снят, запись в журнале — расчёт не ждёт файл вечно."""
    from integration.tasks import fetch_request_letter_file

    def broken(*args):
        raise ConnectionError("broker is down")

    monkeypatch.setattr(fetch_request_letter_file, "delay", broken)
    mode(own, "never")
    _handoff(api)
    _manager()
    with django_capture_on_commit_callbacks(execute=True):
        deal = new_deal(api, letter_file_id=FILE)

    _gave_up(deal, "queue_unavailable")


def test_storage_error_clears_the_wait_and_leaves_a_journal_note(api, own, eds_file, monkeypatch):  # noqa: F811
    from integration.tasks import fetch_request_letter_file

    from sourcing.models import Attachment

    deal = _pending_deal(api, own)

    def broken(*args, **kwargs):
        raise OSError("storage is down")

    monkeypatch.setattr(Attachment.objects, "create", broken)

    assert fetch_request_letter_file.apply(args=(deal.pk, FILE, 101)).result is False
    _gave_up(deal, "storage_error")


def test_deal_gone_before_the_file_arrives_ends_quietly(api, own, eds_file):  # noqa: F811
    from integration.tasks import fetch_request_letter_file

    assert fetch_request_letter_file.apply(args=(987654, FILE, 101)).result is False
    assert eds_file == []


def test_soft_time_limit_clears_the_wait(api, own, monkeypatch):  # noqa: F811
    from celery.exceptions import SoftTimeLimitExceeded
    from integration.services import eds_files
    from integration.tasks import SOFT_TIME_LIMIT, TIME_LIMIT, fetch_request_letter_file

    def slow(*args):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(eds_files, "fetch_request_file", slow)
    deal = _pending_deal(api, own)

    assert fetch_request_letter_file.apply(args=(deal.pk, FILE, 101)).result is False
    _gave_up(deal, "timeout")
    assert (fetch_request_letter_file.soft_time_limit, fetch_request_letter_file.time_limit) == (
        SOFT_TIME_LIMIT,
        TIME_LIMIT,
    )


def test_request_without_a_file_does_not_wait(api, own):  # noqa: F811
    mode(own, "never")
    _handoff(api)
    _manager()
    deal = new_deal(api)
    assert not CalcTask.objects.get(deal=deal).request_file_pending


# ── что сказать в форме заявки ────────────────────────────────────────────────────────────────────────────────────


def test_intake_info_tells_the_form_the_mode_and_whether_the_calculation_can_start_on_the_user(own):  # noqa: F811
    manager = _manager()
    mode(own, "never")
    assert request_resolution.intake_info(manager) == {"mode": "never", "ready": True, "reason": None}
    loner = CustomUser.objects.create_user(email="loner@x.test", username="loner", password="pw")
    assert request_resolution.intake_info(loner) == {"mode": "never", "ready": False, "reason": "no_crm_mapping"}
    CustomUser.objects.filter(pk=manager.pk).update(is_active=False)
    manager.refresh_from_db()
    assert request_resolution.intake_info(manager)["reason"] == "inactive"


def test_intake_endpoint_is_readable_by_a_seller_without_settings_rights(own, monkeypatch):  # noqa: F811
    """Менеджеру настройки компании недоступны (нужно `settings.edit`), а форме заявки режим нужен: свой маленький путь."""
    from rest_framework.test import APIClient

    from crm.services import calculation

    manager = _manager()
    mode(own, "never")
    monkeypatch.setattr(calculation, "is_seller", lambda user: True)
    client = APIClient()
    client.force_authenticate(manager)

    response = client.get("/api/v1/calc/request-intake/")

    assert response.status_code == 200, response.content
    assert response.json() == {"mode": "never", "ready": True, "reason": None}
    monkeypatch.setattr(calculation, "is_seller", lambda user: False)
    assert client.get("/api/v1/calc/request-intake/").status_code == 403


# ── значение настройки ────────────────────────────────────────────────────────────────────────────────────────────


def test_setting_accepts_only_the_two_modes(own, monkeypatch):  # noqa: F811
    from accounts.services import company_settings
    from accounts.services.company_settings import update_company_settings

    monkeypatch.setattr(company_settings, "is_company_owner", lambda user, company: True)
    row, error = update_company_settings(None, own, {"request_resolution": "never"})
    assert error is None and row.request_resolution == "never" and request_resolution.mode() == "never"
    for bad in ("sometimes", "client_own"):
        _, error = update_company_settings(None, own, {"request_resolution": bad})
        assert error == "BAD_REQUEST_RESOLUTION" and request_resolution.mode() == "never"


def test_an_unknown_stored_value_is_the_default(own):  # noqa: F811
    mode(own, "client_own")  # значение из снятого варианта — как «у каждой заявки»
    assert request_resolution.mode() == "always" and request_resolution.required()
