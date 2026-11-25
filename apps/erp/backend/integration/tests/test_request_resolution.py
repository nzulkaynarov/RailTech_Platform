"""РЕЗ-1: «Резолюция перед расчётом» — настройка компании «Правила работы · Продажи», а не код.

Три значения: `always` (по умолчанию — как раньше: письмо директору у каждой заявки), `client_own` («только заявки,
которые клиент подал сам»: решает `initiated_by` — кто начал заявку, канал, а не экран; заявка сотрудника идёт сразу в
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
def letter_file(monkeypatch, django_capture_on_commit_callbacks):
    """EDS отдаёт файл письма клиента; тест подменяет сервисный вызов, а задачу после коммита гоняет сразу."""
    from integration.services import eds_files
    from integration.tasks import fetch_request_letter_file

    calls = []

    def fake(file_id, created_by, letter_number=""):
        calls.append((file_id, created_by, letter_number))
        return ("письмо клиента.pdf", b"%PDF-1.4 client letter")

    monkeypatch.setattr(eds_files, "fetch_request_file", fake)
    monkeypatch.setattr(fetch_request_letter_file, "delay", lambda *a: fetch_request_letter_file.apply(args=a))
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


def test_client_own_staff_initiated_crm_request_skips_the_resolution(api, own):  # noqa: F811
    """Запись звонка в CRM: `initiated_by = staff` приходит с формы — файл основания тут ничего не решает."""
    mode(own, "client_own")
    _handoff(api)
    _manager()
    deal = new_deal(api, initiated_by="staff")

    event = bus_support.only("request.created")
    bus_support.assert_matches_contract(event)
    assert event["data"]["payload"]["resolution_required"] is False
    assert CalcTask.objects.filter(deal=deal).exists()


def test_client_own_keeps_the_letter_for_every_client_channel(api, own):  # noqa: F811
    mode(own, "client_own")
    _handoff(api)
    _manager()
    deal = new_deal(api, initiated_by="client")  # письмо клиента, в том числе без указания канала
    assert letter_is_created() and not CalcTask.objects.exists()
    republish(deal, "cabinet")
    assert letter_is_created() and not CalcTask.objects.exists()
    republish(deal, "crm", initiated_by="client")  # передача из лида, бот
    assert letter_is_created() and not CalcTask.objects.exists()
    republish(deal, "crm", initiated_by="client", source_letter_number="ВХ-12/26")  # зарегистрированное входящее
    assert letter_is_created() and not CalcTask.objects.exists()


def test_client_own_defaults_to_the_source_when_the_channel_is_not_named(api, own):  # noqa: F811
    mode(own, "client_own")
    _handoff(api)
    _manager()
    deal = new_deal(api, initiated_by="client")
    republish(deal, "erp")  # без `initiated_by` заявка из ERP — сотрудника
    assert request_payload()["resolution_required"] is False


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


FILE = "3f2c1a7e-5b9d-4c8e-9a1f-0d2e3c4b5a69"


def test_client_letter_file_is_fetched_after_commit_and_shown_in_the_calculation(
    api, own, monkeypatch, django_capture_on_commit_callbacks  # noqa: F811
):
    """Сеть не держит транзакцию заявки: до коммита файла нет и расчёт говорит «загружается»; после — файл в исходниках."""
    from integration.services import eds_files
    from integration.tasks import fetch_request_letter_file

    calls = []

    def fake(file_id, created_by, letter_number=""):
        calls.append((file_id, created_by, letter_number))
        return ("письмо клиента.pdf", b"%PDF-1.4 client letter")

    monkeypatch.setattr(eds_files, "fetch_request_file", fake)
    monkeypatch.setattr(fetch_request_letter_file, "delay", lambda *a: fetch_request_letter_file.apply(args=a))
    mode(own, "never")
    _handoff(api)
    manager = _manager()

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        deal = new_deal(api, letter_file_id=FILE, letter_number="ВХ-12/26")

    task = CalcTask.objects.get(deal=deal)
    assert request_payload()["resolution_required"] is False
    assert calls == [] and task.request_file_pending and deal_request_files(deal) == []
    assert len(callbacks) == 1
    callbacks[0]()

    assert calls == [(FILE, 101, "ВХ-12/26")]
    task.refresh_from_db()
    assert not task.request_file_pending
    assert [f["name"] for f in deal_request_files(deal)] == ["письмо клиента.pdf"]
    assert task.assignees.filter(user=manager).exists()
    callbacks[0]()  # повтор задачи не кладёт файл второй раз
    assert len(deal_request_files(deal)) == 1


def test_missing_letter_file_stops_waiting_and_leaves_a_journal_note(api, own, monkeypatch):  # noqa: F811
    from integration.services import eds_files
    from integration.tasks import fetch_request_letter_file

    from crm.models import ActivityLog

    monkeypatch.setattr(eds_files, "fetch_request_file", lambda *a: None)
    mode(own, "never")
    _handoff(api)
    _manager()
    deal = new_deal(api, letter_file_id=FILE)
    task = CalcTask.objects.get(deal=deal)
    assert task.request_file_pending

    assert fetch_request_letter_file.apply(args=(deal.pk, FILE, 101, "")).result is False

    task.refresh_from_db()
    assert not task.request_file_pending and deal_request_files(deal) == []
    assert ActivityLog.objects.filter(deal=deal, event_code="deal.request_file_missing").exists()


def test_eds_down_retries_then_gives_up_without_waiting_forever(api, own, monkeypatch):  # noqa: F811
    from integration.services import eds_files
    from integration.tasks import MAX_RETRIES, fetch_request_letter_file

    def down(*args):
        raise eds_files.EdsFileUnavailable("down")

    monkeypatch.setattr(eds_files, "fetch_request_file", down)
    mode(own, "never")
    _handoff(api)
    _manager()
    deal = new_deal(api, letter_file_id=FILE)

    result = fetch_request_letter_file.apply(args=(deal.pk, FILE, 101, ""), retries=MAX_RETRIES)

    assert result.result is False
    assert not CalcTask.objects.get(deal=deal).request_file_pending


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
    mode(own, "client_own")
    monkeypatch.setattr(calculation, "is_seller", lambda user: True)
    client = APIClient()
    client.force_authenticate(manager)

    response = client.get("/api/v1/calc/request-intake/")

    assert response.status_code == 200, response.content
    assert response.json() == {"mode": "client_own", "ready": True, "reason": None}
    monkeypatch.setattr(calculation, "is_seller", lambda user: False)
    assert client.get("/api/v1/calc/request-intake/").status_code == 403


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
