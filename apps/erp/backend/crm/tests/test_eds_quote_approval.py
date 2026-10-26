"""EDS-03: одобрение КП директором — маршрут EDS (волна 12, runbook §2.4–§2.5, решение архитектора §4 п. 3).

* КП готово к одобрению (визы собраны или проверяющих нет) → ERP публикует `quote.ready_for_approval` в транзакции
  изменения: снимок КП, визы по зонам резолюции, порог маржи и срок из задания расчёта; откат — события нет.
* `eds.approval.decided` по КП: approve — ИСХ-номер EDS на КП и «Готово к отправке» (отправка разрешена); return —
  черновик с комментарием директора, повторная отправка — новая редакция и новое событие; reject — КП отклонено.
  Решение по устаревшей редакции не применяется (запись в журнал), повтор решения — без изменений.
* Своей цепочки одобрения директором в ERP нет: ни шага «Руководитель», ни права финального утверждения КП.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import transaction
from integration.models import CrmClientMapping, CrmUserMapping
from integration.services import eds_inbound
from integration.tests import bus_support

from accounts.constants import ALL_PERMISSIONS, Permission
from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from crm.models import ActivityLog, Deal, DealStage, Quote, QuoteStatus
from crm.models.approvals import StepParticipation, StepStatus
from crm.services import calc_tasks
from crm.services.approvals import act_on_step
from crm.services.quotes import QuoteLifecycleService as QLS
from master_data.models import Country

pytestmark = pytest.mark.django_db

EVENTS_DIR = Path(os.environ.get("RT_BUS_CONTRACTS_DIR", "/opt/rt/contracts/events"))


def _user(email, crm_user_id=None):
    user = CustomUser.objects.create_user(
        email=email, username=email, password="pw", is_active=True, first_name=email.split("@")[0].title()
    )
    if crm_user_id is not None:
        CrmUserMapping.objects.create(crm_user_id=crm_user_id, user=user)
    return user


def _member(company, user, roles):
    return CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "MEMBER", "sort_order": 10})[0],
        company_roles=list(roles),
        is_primary=True,
        is_active=True,
        can_sell=False,
    )


@pytest.fixture
def world(db):
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})
    supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})[
        0
    ]
    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})[0]
    seller = Company.objects.create(name="ООО РельсТех Демо", inn="7700000101")
    seller.types.add(supplier_type)
    build = CompanyRole.objects.create(
        company=seller, name="Расчёт КП", permissions=[Permission.QUOTE_BUILD.value, Permission.QUOTE_SEND.value]
    )
    calc = _user("calc@railtech.test", crm_user_id=21)
    _member(seller, calc, [build])
    buyer = _user("buyer@client.test")
    client = Company.objects.create(name="ООО Пример Логистик", inn="6600000101")
    client.types.add(client_type)
    CrmClientMapping.objects.create(company=client, crm_client_id=42)
    deal = Deal.objects.create(
        title="Поставка стрелочных переводов",
        company=client,
        client=buyer,
        manager=calc,
        stage=DealStage.objects.get(code="CALCULATING"),
    )
    return {"seller": seller, "calc": calc, "deal": deal, "client": client}


def _quote(world):
    return Quote.objects.create(
        deal=world["deal"],
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=world["calc"],
        seller_company=world["seller"],
        tax_country=Country.objects.get(code="UZ"),
        vat_rate=Decimal("12.00"),
        subtotal_excl_vat=Decimal("100.00"),
        vat_amount=Decimal("12.00"),
        total_incl_vat=Decimal("112.00"),
    )


def _resolution(deal, assignees=((11, "goods"), (12, "services"))):
    from datetime import date, datetime, timezone

    return calc_tasks.apply_resolution(
        deal,
        eds_letter_id=uuid.UUID("e2b7a5e9-37c3-5a33-948a-7a999c5e7ec9"),
        letter_number="ВХ-104/26",
        letter_subject="Запрос КП",
        text="Подготовить расчёт и КП",
        due=date(2026, 10, 29),
        min_margin_pct=Decimal("15"),
        decided_by_crm_user_id=3,
        decided_by_name="Рустам Директоров",
        decided_at=datetime(2026, 10, 26, 6, 30, tzinfo=timezone.utc),
        assignees=[calc_tasks.Assignment(c, z) for c, z in assignees],
    ).task


def _reviewer(world, email, crm_user_id):
    role = CompanyRole.objects.create(
        company=world["seller"], name=f"Визы {email}", permissions=[Permission.QUOTE_REVIEW.value]
    )
    user = _user(email, crm_user_id=crm_user_id)
    _member(world["seller"], user, [role])
    return user


def _status(quote):
    quote.refresh_from_db()
    return quote.status.code


def decided(quote, decision="approve", *, version=None, comment=None, outgoing="ИСХ-082/26") -> dict:
    data = copy.deepcopy(
        json.loads((EVENTS_DIR / "eds" / "examples" / "approval.decided.v1.json").read_text(encoding="utf-8"))["data"]
    )
    data["approval"]["object"].update(
        {
            "erp_quote_id": quote.pk,
            "quote_version": version or quote.eds_revision,
            "quote_number": quote.number,
            "erp_deal_id": quote.deal_id,
        }
    )
    route = {"approve": "approved", "return": "returned", "reject": "rejected"}[decision]
    data.update(
        {
            "decision": decision,
            "route_status": route,
            "comment": comment,
            "outgoing_number": outgoing if decision == "approve" else None,
        }
    )
    if decision != "approve":
        data.pop("channels", None)
    return data


# ── quote.ready_for_approval ────────────────────────────────────────────────────────────────────────


def test_submit_without_reviewers_sends_the_quote_to_the_director_in_eds(world):
    _resolution(world["deal"])
    quote = _quote(world)

    _, err = QLS.submit_for_review(quote.id, world["calc"])

    assert err is None and _status(quote) == "PENDING_APPROVAL"
    assert quote.number and quote.eds_revision == 1
    assert not quote.approval_steps.exists(), "шага директора в ERP нет"
    event = bus_support.only("quote.ready_for_approval")
    bus_support.assert_matches_contract(event)
    assert event["source"] == "rt://erp" and event["subject"] == quote.number
    data = event["data"]
    assert data["erp_company_id"] == world["client"].pk and data["crm_client_id"] == 42
    assert data["deal"]["erp_deal_id"] == world["deal"].pk and data["deal"]["stage"] == "quoting"
    payload = data["payload"]
    assert payload["erp_quote_id"] == quote.pk and payload["number"] == quote.number and payload["version"] == 1
    assert payload["total"] == "112.00" and payload["currency"] == "UZS"
    assert payload["min_margin_pct"] == "15.00" and payload["due"] == "2026-10-29"
    assert payload["required_zones"] == ["goods", "services"] and payload["visas"] == []
    assert payload["eds_letter_id"] == "e2b7a5e9-37c3-5a33-948a-7a999c5e7ec9"
    assert payload["client_name"] == "ООО Пример Логистик"
    assert ActivityLog.objects.filter(entity_id=quote.pk, event_code="quote.sent_to_director").count() == 1


def test_event_waits_for_the_visas_and_carries_them_by_zone(world):
    _resolution(world["deal"])
    supply = _reviewer(world, "supply@railtech.test", 11)
    engineer = _reviewer(world, "engineer@railtech.test", 12)
    quote = _quote(world)

    QLS.submit_for_review(quote.id, world["calc"])
    assert bus_support.published("quote.ready_for_approval") == [], "визы ещё не собраны"
    steps = {s.approver.user_id: s for s in quote.approval_steps.select_related("approver")}
    assert {s.participation for s in steps.values()} == {StepParticipation.APPROVER}

    assert act_on_step(steps[supply.pk].id, supply, "APPROVE")[1] is None
    assert bus_support.published("quote.ready_for_approval") == []
    assert act_on_step(steps[engineer.pk].id, engineer, "APPROVE")[1] is None

    assert _status(quote) == "PENDING_APPROVAL", "после виз КП ждёт директора, а не «Готово к отправке»"
    event = bus_support.only("quote.ready_for_approval")
    bus_support.assert_matches_contract(event)
    visas = {(v["zone"], v["by"]["crm_user_id"]) for v in event["data"]["payload"]["visas"]}
    assert visas == {("goods", 11), ("services", 12)}


def test_company_without_crm_client_still_reaches_eds(world):
    CrmClientMapping.objects.filter(company=world["client"]).delete()
    quote = _quote(world)
    QLS.submit_for_review(quote.id, world["calc"])
    event = bus_support.only("quote.ready_for_approval")
    bus_support.assert_matches_contract(event)
    assert event["data"]["crm_client_id"] is None
    assert event["data"]["payload"]["min_margin_pct"] is None and event["data"]["payload"]["required_zones"] == []


def test_rollback_publishes_nothing(world):
    quote = _quote(world)
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            _, err = QLS.submit_for_review(quote.id, world["calc"])
            assert err is None
            raise RuntimeError("сбой после отправки на согласование")
    assert bus_support.published("quote.ready_for_approval") == []
    assert _status(quote) == "DRAFT" and quote.eds_revision == 0


def test_calculator_draft_without_client_is_not_sent_to_the_director(world):
    deal = Deal.objects.create(title="Калькулятор", company=None, stage=DealStage.objects.get(code="DRAFT"))
    quote = _quote(world)
    quote.deal = deal
    quote.save(update_fields=["deal"])
    _, err = QLS.submit_for_review(quote.id, world["calc"])
    assert err == "QUOTE_CLIENT_REQUIRED" and _status(quote) == "DRAFT"


# ── eds.approval.decided ──────────────────────────────────────────────────────────────────────────────


def _submitted(world):
    quote = _quote(world)
    QLS.submit_for_review(quote.id, world["calc"])
    quote.refresh_from_db()
    return quote


def test_approve_stores_the_outgoing_number_and_unlocks_sending(world):
    quote = _submitted(world)
    director = _user("director@railtech.test", crm_user_id=3)

    outcome = eds_inbound.apply_approval_decided(decided(quote, "approve"))

    assert outcome.applied
    quote.refresh_from_db()
    assert quote.status.code == "READY_TO_SEND"
    assert quote.outgoing_number == "ИСХ-082/26" and quote.send_channels == ["telegram", "cabinet"]
    assert quote.director_decision == "approve" and quote.director_decided_at is not None
    entry = ActivityLog.objects.get(entity_id=quote.pk, event_code="quote.director_approved")
    assert entry.user_id == director.pk and entry.event_params["outgoing_number"] == "ИСХ-082/26"

    sent = QLS.send_to_client(quote.id, world["calc"])
    assert sent.status.code == "SENT" and sent.number == quote.number, "отправка клиенту разблокирована"


def test_sending_is_blocked_until_the_director_approves(world):
    quote = _submitted(world)
    with pytest.raises(ValueError):
        QLS.send_to_client(quote.id, world["calc"])


def test_repeated_approval_changes_nothing(world):
    quote = _submitted(world)
    eds_inbound.apply_approval_decided(decided(quote, "approve"))
    again = eds_inbound.apply_approval_decided(decided(quote, "approve", outgoing="ИСХ-999/26"))
    quote.refresh_from_db()
    assert again.reason == "duplicate" and quote.outgoing_number == "ИСХ-082/26"
    assert ActivityLog.objects.filter(entity_id=quote.pk, event_code="quote.director_approved").count() == 1


def test_return_sends_the_quote_back_to_draft_with_the_comment_and_resubmit_is_a_new_version(world):
    from notifications.models import Notification

    quote = _submitted(world)
    outcome = eds_inbound.apply_approval_decided(decided(quote, "return", comment="Пересчитать логистику"))

    assert outcome.applied
    quote.refresh_from_db()
    assert quote.status.code == "DRAFT" and quote.director_comment == "Пересчитать логистику"
    assert quote.director_decision == "return" and not quote.outgoing_number
    note = Notification.objects.get(user=world["calc"], event_code="quote.approval_returned")
    assert note.event_params["comment"] == "Пересчитать логистику"

    _, err = QLS.submit_for_review(quote.id, world["calc"])
    assert err is None
    events = bus_support.published("quote.ready_for_approval")
    assert [e["data"]["payload"]["version"] for e in events] == [1, 2]
    assert events[0]["data"]["payload"]["number"] == events[1]["data"]["payload"]["number"]
    quote.refresh_from_db()
    assert quote.director_decision == "" and quote.director_comment == ""


def test_decision_on_a_stale_version_is_ignored_and_journaled(world):
    quote = _submitted(world)
    eds_inbound.apply_approval_decided(decided(quote, "return", comment="Доработать"))
    QLS.submit_for_review(quote.id, world["calc"])
    quote.refresh_from_db()
    assert quote.eds_revision == 2

    outcome = eds_inbound.apply_approval_decided(decided(quote, "approve", version=1))

    assert not outcome.applied and outcome.reason == "stale"
    assert _status(quote) == "PENDING_APPROVAL" and quote.outgoing_number == ""
    entry = ActivityLog.objects.get(entity_id=quote.pk, event_code="quote.director_decision_stale")
    assert entry.event_params["version"] == 1 and entry.event_params["current_revision"] == 2


def test_decision_after_recall_is_not_applied(world):
    from crm.services.approvals import recall_quote

    quote = _submitted(world)
    recall_quote(quote.id, world["calc"])
    outcome = eds_inbound.apply_approval_decided(decided(quote, "approve"))
    assert outcome.reason == "ignored" and _status(quote) == "DRAFT"
    assert ActivityLog.objects.filter(entity_id=quote.pk, event_code="quote.director_decision_ignored").exists()


def test_reject_marks_the_quote_rejected_by_the_director(world):
    quote = _submitted(world)
    outcome = eds_inbound.apply_approval_decided(decided(quote, "reject", comment="Маржа ниже порога"))
    assert outcome.applied
    quote.refresh_from_db()
    assert quote.status.code == "REJECTED" and quote.director_comment == "Маржа ниже порога"
    assert ActivityLog.objects.filter(entity_id=quote.pk, event_code="quote.director_rejected").exists()


def test_open_route_and_non_quote_objects_are_not_applied(world):
    quote = _submitted(world)
    data = decided(quote, "approve")
    data["route_status"] = "open"
    assert eds_inbound.apply_approval_decided(data).reason == "route_open"

    memo = decided(quote, "approve")
    memo["approval"]["template"] = "memo"
    memo["approval"]["object"] = {
        "kind": "memo",
        "eds_document_id": str(uuid.uuid4()),
        "number": "СЗ-2026/001",
    }
    assert eds_inbound.apply_approval_decided(memo).reason == "not_a_quote"
    assert _status(quote) == "PENDING_APPROVAL"


def test_unknown_quote_is_skipped(world):
    quote = _submitted(world)
    data = decided(quote, "approve")
    data["approval"]["object"]["erp_quote_id"] = 999999
    assert eds_inbound.apply_approval_decided(data).reason == "unknown_quote"


# ── прежней цепочки одобрения директором нет ─────────────────────────────────────────────────────────


def test_there_is_no_director_step_and_no_final_approval_permission():
    assert "HEAD" not in StepParticipation.values
    assert not any(code.startswith("quote.approve") for code in ALL_PERMISSIONS)
    assert {name for name in Permission.names if name.startswith("QUOTE_")} == {
        "QUOTE_BUILD",
        "QUOTE_EDIT_PRICING",
        "QUOTE_VIEW_COST_MARGIN",
        "QUOTE_SEND",
        "QUOTE_REVIEW",
    }
    assert StepStatus.PENDING  # шаги виз остаются


def test_migration_drops_director_steps_and_returns_quotes_waiting_only_for_them_to_draft(world):
    """sales/0005: шаги «Руководитель» прежней цепочки удаляются; КП, ждавшее только руководителя, — в черновик."""
    import importlib

    from django.apps import apps

    from crm.models import QuoteApprovalStep

    migration = importlib.import_module("sales.migrations.0005_eds_calc_tasks_director_decision")
    waiting = _quote(world)
    waiting.status = QuoteStatus.objects.get(code="PENDING_APPROVAL")
    waiting.save(update_fields=["status"])
    QuoteApprovalStep.objects.create(quote=waiting, order=100, participation="HEAD", status="PENDING")
    reviewer_left = Quote.objects.create(
        deal=world["deal"], version=2, status=QuoteStatus.objects.get(code="PENDING_APPROVAL")
    )
    QuoteApprovalStep.objects.create(quote=reviewer_left, order=1, participation="APPROVER", status="PENDING")
    QuoteApprovalStep.objects.create(quote=reviewer_left, order=100, participation="HEAD", status="PENDING")

    migration.drop_head_steps(apps, None)

    assert not QuoteApprovalStep.objects.filter(participation="HEAD").exists()
    assert _status(waiting) == "DRAFT"
    assert _status(reviewer_left) == "PENDING_APPROVAL", "виза проверяющего ещё ждёт — КП остаётся на согласовании"
