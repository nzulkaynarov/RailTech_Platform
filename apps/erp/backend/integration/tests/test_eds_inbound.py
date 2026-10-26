"""ERP ← EDS (волна 12, EDS-01): резолюция → задание расчёта и стадия «Расчёт»; отказ по письму → сделка LOST.

Тела событий — примеры контракта (`packages/contracts/events/eds/examples/`) с подменой ссылок на сделку теста. Повтор
события — без дублей; неизвестный сотрудник и письмо без сделки — запись в журнал, не ошибка (событие не уходит в
автоповтор). Сквозной тест принимает подписанное событие EDS приёмником `/bus/v1/events`.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import transaction
from django.test import Client
from django.utils import timezone
from integration.bus import get_bus
from integration.models import CrmUserMapping
from integration.services import eds_inbound
from integration.tests import bus_support
from integration.tests.world import make_company, make_deal
from rt_bus.django.models import Inbox
from rt_bus.signing import format_timestamp, sign

from accounts.models import CustomUser
from crm.constants import DealStageCode
from crm.models import ActivityLog, CalcTask, Deal, DealStage

pytestmark = pytest.mark.django_db

EVENTS_DIR = Path(os.environ.get("RT_BUS_CONTRACTS_DIR", "/opt/rt/contracts/events"))


def envelope(name: str) -> dict:
    return json.loads((EVENTS_DIR / "eds" / "examples" / f"{name}.v1.json").read_text(encoding="utf-8"))


def resolved(deal: Deal, *, letter_id: str | None = None, assignees=None, margin="15") -> dict:
    data = copy.deepcopy(envelope("letter.resolved")["data"])
    data["links"].update({"erp_deal_id": deal.pk, "erp_request_id": deal.pk})
    if letter_id:
        data["letter"]["eds_letter_id"] = letter_id
    if assignees is not None:
        data["resolution"]["assignees"] = assignees
    data["resolution"]["min_margin_pct"] = margin
    return data


def rejected(deal: Deal) -> dict:
    data = copy.deepcopy(envelope("letter.rejected")["data"])
    data["links"].update({"erp_deal_id": deal.pk, "erp_request_id": deal.pk})
    return data


def staff(email: str, crm_user_id: int) -> CustomUser:
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CrmUserMapping.objects.create(crm_user_id=crm_user_id, user=user)
    return user


@pytest.fixture
def deal():
    return make_deal(make_company(name="ООО Пример Логистик", crm_client_id=42), DealStageCode.DRAFT)


@pytest.fixture
def people():
    return {"supply": staff("supply@railtech.test", 11), "engineer": staff("engineer@railtech.test", 12)}


def _stage(deal: Deal) -> str:
    deal.refresh_from_db()
    return deal.stage.code


# ── letter.resolved → задание расчёта ───────────────────────────────────────────────────────────────


def test_resolution_creates_a_calc_task_with_assignees_due_margin_and_moves_the_deal_to_calculation(deal, people):
    outcome = eds_inbound.apply_letter_resolved(resolved(deal), event_id=uuid.uuid4())

    assert outcome.applied
    task = CalcTask.objects.get(deal=deal)
    assert task.letter_number == "ВХ-104/26" and task.due == date(2026, 10, 29)
    assert task.min_margin_pct == Decimal("15") and task.decided_by_crm_user_id == 3
    assert task.resolution_text.startswith("Подготовить расчёт")
    rows = {(a.crm_user_id, a.zone, a.user_id) for a in task.assignees.all()}
    assert rows == {(11, "goods", people["supply"].pk), (12, "services", people["engineer"].pk)}
    assert _stage(deal) == DealStageCode.CALCULATING
    # Смена стадии — обычный переход FSM: событие шины deal.stage_changed (request → quoting) в той же транзакции.
    changed = bus_support.published("deal.stage_changed")[-1]
    assert changed["data"]["payload"] == {"from": "request", "to": "quoting"}
    bus_support.assert_matches_contract(changed)
    assert ActivityLog.objects.filter(deal=deal, event_code="deal.calc_task_created").count() == 1
    # Исполнители получили уведомление о задании.
    from notifications.models import Notification

    assert set(Notification.objects.filter(event_code="deal.calc_assigned").values_list("user_id", flat=True)) == {
        people["supply"].pk,
        people["engineer"].pk,
    }


def test_resolution_without_margin_threshold_keeps_it_empty(deal, people):
    eds_inbound.apply_letter_resolved(resolved(deal, margin=None))
    assert CalcTask.objects.get(deal=deal).min_margin_pct is None


def test_repeated_resolution_event_creates_no_duplicates(deal, people):
    event_id = uuid.uuid4()
    data = resolved(deal)
    eds_inbound.apply_letter_resolved(data, event_id=event_id)
    outbox_before = len(bus_support.published())

    again = eds_inbound.apply_letter_resolved(copy.deepcopy(data), event_id=event_id)
    # Тот же письмо — другим событием (например, повтор EDS после сбоя) — тоже без дублей строк и уведомлений.
    eds_inbound.apply_letter_resolved(copy.deepcopy(data), event_id=uuid.uuid4())

    assert not again.applied
    assert CalcTask.objects.filter(deal=deal).count() == 1
    assert CalcTask.objects.get(deal=deal).assignees.count() == 2
    assert len(bus_support.published()) == outbox_before, "повтор не двигает стадию и не публикует событий"
    from notifications.models import Notification

    assert Notification.objects.filter(event_code="deal.calc_assigned").count() == 2


def test_new_resolution_of_the_same_letter_updates_the_task(deal, people):
    data = resolved(deal)
    eds_inbound.apply_letter_resolved(data, event_id=uuid.uuid4())
    data["resolution"]["assignees"] = [{"crm_user_id": 12, "zone": "services"}]
    data["resolution"]["due"] = "2026-11-02"
    eds_inbound.apply_letter_resolved(data, event_id=uuid.uuid4())

    task = CalcTask.objects.get(deal=deal)
    assert task.due == date(2026, 11, 2)
    assert [(a.crm_user_id, a.zone) for a in task.assignees.all()] == [(12, "services")]
    assert ActivityLog.objects.filter(deal=deal, event_code="deal.calc_task_updated").count() == 1


def test_unknown_employee_is_kept_without_user_and_written_to_the_journal(deal, people):
    data = resolved(
        deal, assignees=[{"crm_user_id": 11, "zone": "goods"}, {"crm_user_id": 999, "zone": "payment_terms"}]
    )

    outcome = eds_inbound.apply_letter_resolved(data, event_id=uuid.uuid4())

    assert outcome.applied
    unknown = CalcTask.objects.get(deal=deal).assignees.get(crm_user_id=999)
    assert unknown.user_id is None and unknown.zone == "payment_terms"
    entry = ActivityLog.objects.get(deal=deal, event_code="deal.calc_assignee_unknown")
    assert entry.level == "WARNING" and entry.event_params["crm_user_id"] == 999
    assert "не заведён в ERP" in entry.detail
    assert _stage(deal) == DealStageCode.CALCULATING


def test_resolution_of_a_letter_without_deal_is_skipped_with_a_journal_entry(deal):
    data = resolved(deal)
    data["links"].update({"erp_deal_id": None, "erp_request_id": None})

    outcome = eds_inbound.apply_letter_resolved(data, event_id=uuid.uuid4())

    assert not outcome.applied and outcome.reason == "no_deal"
    assert not CalcTask.objects.exists()
    entry = ActivityLog.objects.get(event_code="eds.letter_skipped")
    assert entry.level == "WARNING" and entry.event_params["letter_number"] == "ВХ-104/26"


def test_request_id_is_used_when_the_deal_link_is_empty(deal, people):
    data = resolved(deal)
    data["links"]["erp_deal_id"] = None
    assert eds_inbound.apply_letter_resolved(data).applied
    assert CalcTask.objects.get().deal_id == deal.pk


def test_resolution_on_a_deal_past_calculation_keeps_its_stage(people):
    deal = make_deal(make_company(crm_client_id=43), DealStageCode.CONTRACT_SIGNED)
    eds_inbound.apply_letter_resolved(resolved(deal))
    assert _stage(deal) == DealStageCode.CONTRACT_SIGNED
    assert CalcTask.objects.filter(deal=deal).exists()
    assert ActivityLog.objects.filter(deal=deal, event_code="deal.calc_stage_kept", level="WARNING").exists()


# ── letter.rejected → LOST ───────────────────────────────────────────────────────────────────────────


def test_rejection_moves_the_deal_to_lost_with_the_reason(deal):
    outcome = eds_inbound.apply_letter_rejected(rejected(deal))

    assert outcome.applied
    assert _stage(deal) == DealStageCode.CLOSED_LOST
    lost = bus_support.only("deal.lost")
    assert lost["data"]["payload"]["lost_reason"] == "Не наш профиль: позиции вне номенклатуры компании."
    bus_support.assert_matches_contract(lost)
    entry = ActivityLog.objects.get(deal=deal, event_code="deal.lost_by_letter_rejection")
    assert entry.event_params == {
        "letter_number": "ВХ-104/26",
        "reason": "Не наш профиль: позиции вне номенклатуры компании.",
    }


def test_repeated_rejection_changes_nothing(deal):
    eds_inbound.apply_letter_rejected(rejected(deal))
    again = eds_inbound.apply_letter_rejected(rejected(deal))

    assert not again.applied
    assert len(bus_support.published("deal.lost")) == 1
    assert ActivityLog.objects.filter(deal=deal, event_code="deal.lost_by_letter_rejection").count() == 1


def test_rejection_of_a_won_deal_is_not_applied_and_is_journaled():
    deal = make_deal(make_company(crm_client_id=44), DealStageCode.CLOSED_WON)
    outcome = eds_inbound.apply_letter_rejected(rejected(deal))
    assert not outcome.applied
    assert _stage(deal) == DealStageCode.CLOSED_WON
    assert ActivityLog.objects.filter(deal=deal, event_code="deal.letter_rejection_kept", level="WARNING").exists()


def test_rollback_of_the_handler_transaction_leaves_neither_task_nor_event(deal, people):
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            eds_inbound.apply_letter_resolved(resolved(deal))
            raise RuntimeError("сбой после обработки")
    assert not CalcTask.objects.exists()
    assert bus_support.published() == []
    assert _stage(deal) == DealStageCode.DRAFT


# ── приёмник шины: подписанное событие EDS ────────────────────────────────────────────────────────────


def _signed_post(env: dict, secret: str):
    body = json.dumps(env, ensure_ascii=False).encode()
    stamp = format_timestamp(timezone.now())
    return Client().post(
        "/bus/v1/events",
        data=body,
        content_type="application/cloudevents+json",
        HTTP_X_RT_PUBLISHER="eds",
        HTTP_X_RT_EVENT_ID=env["id"],
        HTTP_X_RT_TIMESTAMP=stamp,
        HTTP_X_RT_SIGNATURE=sign(secret, env["id"], stamp, body),
    )


def test_receiver_accepts_signed_eds_events_and_the_handlers_apply_them(
    deal, people, monkeypatch, django_capture_on_commit_callbacks
):
    secret = "e" * 64
    monkeypatch.setenv("RT_BUS_SECRET_EDS_ERP", secret)
    bus = get_bus()
    monkeypatch.setattr(bus, "enqueue", bus.process_inbox)

    env = envelope("letter.resolved")
    env.update({"id": str(uuid.uuid4()), "time": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")})
    env["data"]["links"].update({"erp_deal_id": deal.pk, "erp_request_id": deal.pk})
    with django_capture_on_commit_callbacks(execute=True):
        response = _signed_post(env, secret)
    assert response.status_code == 200 and response.json()["status"] == "received"
    assert Inbox.objects.get(event_id=env["id"]).status == "processed"
    assert CalcTask.objects.filter(deal=deal).count() == 1
    assert _stage(deal) == DealStageCode.CALCULATING

    # Повтор того же id приёмником — `duplicate`, вторая обработка не запускается.
    assert _signed_post(env, secret).json()["status"] == "duplicate"

    rej = envelope("letter.rejected")
    rej.update({"id": str(uuid.uuid4()), "time": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")})
    rej["data"]["links"].update({"erp_deal_id": deal.pk, "erp_request_id": deal.pk})
    with django_capture_on_commit_callbacks(execute=True):
        assert _signed_post(rej, secret).status_code == 200
    assert Inbox.objects.get(event_id=rej["id"]).status == "processed"
    assert _stage(deal) == DealStageCode.CLOSED_LOST
    assert DealStage.objects.filter(code=DealStageCode.CLOSED_LOST).exists()
