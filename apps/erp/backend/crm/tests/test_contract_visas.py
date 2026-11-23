"""Х-1: договор не уходит клиенту, пока не собраны визы маршрута подписи (ADR-0025).

Каждый путь отправки закрыт на сервере и проверен «красным без защиты» (мутационная проверка — в описании PR):
* действие `send-to-client` (API и сервис) — 409 `CONTRACT_VISAS_REQUIRED`, причина словами, статус не меняется,
  события и уведомления нет;
* создание договора «сразу у клиента» (`generate-from-quote` по умолчанию и акцепт КП клиентом) — договор остаётся
  проектом, клиенту не виден;
* список действий и карточка проекта — «Отправить клиенту» не предлагается, причина в `send_blocker`.
Состояние виз — факт: проекция события EDS `signing.visas_changed` у запроса подписи ТЕКУЩЕЙ редакции договора.
"""

import pytest
from django.utils import timezone
from integration.models import CommercialSigningRequest
from integration.tests import bus_support

from crm import services as crm_services
from crm.constants import ContractStatusCode as S
from crm.models import Contract
from crm.services import contract_flow, contract_visas
from crm.tests.projects_world import VISAS_APPROVED, api, collect_visas, contract_in, pw  # noqa: F401

pytestmark = pytest.mark.django_db

URL = "/api/v1/crm/contracts/{id}/send-to-client/"
FINANCE, LEGAL = VISAS_APPROVED


def _visas(finance="pending", legal="pending"):
    return [{**FINANCE, "status": finance}, {**LEGAL, "status": legal}]


def _send(user, contract):
    return api(user).post(URL.format(id=contract.id), {}, format="json")


def _assert_not_sent(contract):
    contract.refresh_from_db()
    assert contract.status.code == S.DRAFT
    assert not bus_support.published("contract.status_changed")
    assert not bus_support.published("document.created"), "клиенту ничего не ушло"


def test_without_a_visa_round_the_contract_does_not_go_to_the_client(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)

    response = _send(pw.accountant, contract)

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "CONTRACT_VISAS_REQUIRED"
    assert "На подпись" in body["reason"]
    _assert_not_sent(contract)


def test_reason_names_the_missing_visas_in_words(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    collect_visas(contract, _visas("pending", "pending"))
    response = _send(pw.accountant, contract)
    assert response.status_code == 409
    assert response.json()["reason"] == "Нужны визы: бухгалтер, юрист"
    assert response.json()["missing"] == ["бухгалтер", "юрист"]

    CommercialSigningRequest.objects.update(visas=_visas("approved", "pending"))
    response = _send(pw.accountant, contract)
    assert response.json()["reason"] == "Нужны визы: юрист"
    _assert_not_sent(contract)


def test_collected_visas_let_the_contract_go(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    collect_visas(contract)

    response = _send(pw.accountant, contract)

    assert response.status_code == 200, response.content
    contract.refresh_from_db()
    assert contract.status.code == S.PENDING_CLIENT


def test_visas_of_an_older_edition_do_not_count(pw):  # noqa: F811
    """Договор изменили после виз — это другая редакция: визы собираются заново (ADR-0025 п. 5)."""
    contract = contract_in(pw, S.DRAFT)
    collect_visas(contract)
    contract.notes = "Новый пункт о неустойке"
    contract.save()

    response = _send(pw.accountant, contract)

    assert response.status_code == 409
    assert contract_visas.send_blocker(contract)["code"] == contract_visas.NOT_REQUESTED
    _assert_not_sent(contract)


def test_returned_visa_blocks_with_the_remark(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    collect_visas(contract, _visas("returned", "pending"), status="rejected", comment="Виза бухгалтера: нет графика")

    blocker = contract_visas.send_blocker(contract)

    assert blocker["code"] == contract_visas.RETURNED
    assert blocker["missing"] == ["бухгалтер"]
    assert blocker["remark"] == "Виза бухгалтера: нет графика"
    assert _send(pw.accountant, contract).status_code == 409
    _assert_not_sent(contract)


def test_no_holder_of_a_visa_permission_says_so_and_points_to_settings(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    collect_visas(contract, _visas("pending", "no_holder"), status="rejected", comment="Нет сотрудника с ролью «Юрист»")

    blocker = contract_visas.send_blocker(contract)

    assert blocker["code"] == contract_visas.NO_HOLDER
    assert blocker["missing"] == ["юрист"] and blocker["settings_link"] is True
    assert "юрист" in _send(pw.accountant, contract).json()["reason"]


def test_refusal_before_visas_keeps_the_reason_of_eds(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    collect_visas(contract, [], status="rejected", comment="Нет сотрудника с полномочием подписать этот документ.")

    blocker = contract_visas.send_blocker(contract)

    assert blocker["code"] == contract_visas.DECLINED
    assert "полномочием подписать" in blocker["remark"]


def test_service_refuses_too_not_only_the_view(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)

    updated, error = contract_flow.apply_transition(contract.id, "send_to_client", pw.director)

    assert (updated, error) == (None, "CONTRACT_VISAS_REQUIRED")
    _assert_not_sent(contract)


def test_the_action_is_not_offered_while_it_cannot_succeed(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    assert "send_to_client" not in contract_flow.allowed_actions(contract, pw.accountant)
    assert "send_to_client" not in contract_flow.allowed_actions(contract, pw.admin)

    collect_visas(contract)
    assert "send_to_client" in contract_flow.allowed_actions(contract, pw.accountant)


def test_project_card_carries_the_blocker_while_the_draft_is_unsent(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    collect_visas(contract, _visas("approved", "pending"))

    card = api(pw.accountant).get(f"/api/v1/crm/projects/{pw.deal.pk}/").json()["contract"]

    assert "send_to_client" not in card["actions"]
    assert card["send_blocker"] == {
        "code": "visas_pending",
        "message": "Нужны визы: юрист",
        "missing": ["юрист"],
        "missing_permissions": ["approvals.visa_legal"],
        "remark": "",
        "settings_link": False,
    }
    CommercialSigningRequest.objects.update(visas=VISAS_APPROVED)
    card = api(pw.accountant).get(f"/api/v1/crm/projects/{pw.deal.pk}/").json()["contract"]
    assert card["send_blocker"] is None and "send_to_client" in card["actions"]


def test_list_row_says_why_the_unsent_project_waits(pw):  # noqa: F811
    """«Мои задачи» и «Главная» берут слово шага из строки списка: код причины там же, где `sent_to_client`."""
    contract = contract_in(pw, S.DRAFT)

    def code():
        rows = api(pw.accountant).get("/api/v1/crm/projects/").json()["results"]
        return rows[0]["documents"]["contract"]["send_blocker_code"]

    assert code() == "visas_not_requested"
    collect_visas(contract, _visas("approved", "pending"))
    assert code() == "visas_pending"
    CommercialSigningRequest.objects.update(visas=VISAS_APPROVED)
    assert code() is None


def test_contract_already_at_the_client_has_no_blocker(pw):  # noqa: F811
    contract_in(pw, S.PENDING_CLIENT)
    card = api(pw.accountant).get(f"/api/v1/crm/projects/{pw.deal.pk}/").json()["contract"]
    assert card["send_blocker"] is None


# ── Создание договора «сразу у клиента» ───────────────────────────────────────────────────────────


def test_generate_from_quote_by_default_no_longer_sends_the_contract(pw):  # noqa: F811
    response = api(pw.accountant).post(
        "/api/v1/crm/contracts/generate-from-quote/", {"quote_id": pw.quote.id}, format="json"
    )

    assert response.status_code == 201, response.content
    contract = Contract.objects.get(pk=response.json()["id"])
    assert contract.status.code == S.DRAFT
    assert not bus_support.published("document.created"), "в кабинет договор не публикуется"
    assert bus_support.only("contract.status_changed")["data"]["payload"]["sent_to_client"] is False


def test_the_contract_born_after_the_client_accepted_the_quote_waits_for_visas(pw):  # noqa: F811
    """Акцепт КП клиентом создаёт договор (актор — система): раньше он сразу уходил клиенту без единой визы."""
    contract, error = crm_services.generate_contract_from_quote(pw.quote.id, actor=None)

    assert error is None
    assert contract.status.code == S.DRAFT
    assert not bus_support.published("document.created")


def test_contract_with_collected_visas_may_be_created_at_the_client(pw):  # noqa: F811
    """Визы собраны к существующему проекту — повторное «сформировать» по умолчанию отправляет его, как раньше."""
    draft, _ = crm_services.generate_contract_from_quote(pw.quote.id, actor=pw.director, send_to_client=False)
    collect_visas(draft)

    contract, error = crm_services.generate_contract_from_quote(pw.quote.id, actor=pw.director)

    assert error is None and contract.pk == draft.pk
    assert contract.status.code == S.PENDING_CLIENT


# ── Маршрут «визы → клиенту → подпись» без тупиков (ADR-0025) ──────────────────────────────────────


def _director_signs(contract, code="DOG0000001"):
    from unittest.mock import patch

    from integration.services.eds_inbound import apply_signing_decided

    event = {
        "object": {"kind": "contract", "object_id": contract.pk, "number": contract.number, "version": None},
        "decision": "signed",
        "signer": {"full_name": "Директор", "position": "Директор"},
        "verification_code": code,
        "signed_at": timezone.now().isoformat(),
        "basis": "charter",
    }
    with patch("crm.services.contracts._render_contract_pdf"):
        return apply_signing_decided(event)


def test_signature_after_sending_to_the_client_is_still_applied(pw):  # noqa: F811
    """Визы собраны, шаг «Подписать» открыт, договор ушёл клиенту: подпись директора применяется, визы не пропадают."""
    contract = contract_in(pw, S.DRAFT)
    collect_visas(contract)
    assert _send(pw.accountant, contract).status_code == 200

    outcome = _director_signs(contract)

    assert (outcome.applied, outcome.reason) == (True, "contract_signed")
    contract.refresh_from_db()
    assert contract.verification_code == "DOG0000001"
    assert CommercialSigningRequest.objects.get().status == "signed"


def test_rejected_by_the_client_after_the_signature_can_go_through_the_route_again(pw):  # noqa: F811
    """Директор подписал до отправки, клиент отклонил, «Доработать»: новая редакция — визы и подпись с начала, путь есть."""
    contract = contract_in(pw, S.DRAFT)
    collect_visas(contract)
    assert _send(pw.accountant, contract).status_code == 200
    _director_signs(contract)
    for action, extra in (("reject", {"reason": "Не устраивает срок"}), ("revise", {})):
        _, error = contract_flow.apply_transition(contract.pk, action, pw.accountant, **extra)
        assert error is None, error

    contract.refresh_from_db()
    assert contract.status.code == S.DRAFT and contract.verification_code == ""
    blocker = contract_flow.send_blocker(contract)
    assert blocker["code"] == contract_visas.NOT_REQUESTED, "новая редакция снова идёт через визы"
    from integration.models import CrmUserMapping

    from crm.services.signing_outbound import request_commercial_signing

    CrmUserMapping.objects.create(crm_user_id=7001, user=pw.accountant)
    request_commercial_signing(kind="contract", doc=contract, user=pw.accountant)  # больше не ALREADY_SIGNED

    CommercialSigningRequest.objects.filter(status="pending").update(visas=VISAS_APPROVED)
    assert contract_flow.send_blocker(contract) is None
    assert _send(pw.accountant, contract).status_code == 200


def test_status_change_does_not_change_the_edition_of_a_contract(pw):  # noqa: F811
    from crm.services.signing_outbound import fingerprint

    contract = contract_in(pw, S.DRAFT)
    before = fingerprint("contract", contract)
    contract.status = contract_flow._status_row(S.PENDING_CLIENT)
    contract.save()
    assert fingerprint("contract", contract) == before


# ── Проекция события EDS ──────────────────────────────────────────────────────────────────────────


def _event(contract, request, visas, *, at=None):
    return {
        "object": {
            "kind": "contract",
            "object_id": contract.pk,
            "number": contract.number,
            "version": int(request.fingerprint[:7], 16),
        },
        "visas": visas,
        "all_approved": all(v["status"] == "approved" for v in visas),
        "changed_at": (at or timezone.now()).isoformat(),
        "actor": {"type": "staff", "crm_user_id": 5},
    }


def test_event_of_eds_is_stored_at_the_request_of_the_same_edition(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    request = collect_visas(contract, [])
    assert contract_visas.send_blocker(contract)["code"] == contract_visas.PENDING

    applied, why = contract_visas.apply_visas_changed(_event(contract, request, _visas("approved", "approved")))

    assert (applied, why) == (True, "applied")
    request.refresh_from_db()
    assert [v["status"] for v in request.visas] == ["approved", "approved"]
    assert contract_visas.send_blocker(contract) is None


def test_late_event_does_not_roll_the_state_back(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    request = collect_visas(contract, [])
    now = timezone.now()
    contract_visas.apply_visas_changed(_event(contract, request, _visas("approved", "approved"), at=now))

    applied, why = contract_visas.apply_visas_changed(
        _event(contract, request, _visas("pending", "pending"), at=now - timezone.timedelta(minutes=5))
    )

    assert (applied, why) == (False, "stale_event")
    assert contract_visas.send_blocker(contract) is None
    # повтор того же события — один эффект
    assert (
        contract_visas.apply_visas_changed(_event(contract, request, _visas("approved", "approved"), at=now))[0]
        is False
    )


def test_event_for_another_edition_or_unknown_request_changes_nothing(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    request = collect_visas(contract, [])
    other = _event(contract, request, _visas("approved", "approved"))
    other["object"]["version"] += 1

    assert contract_visas.apply_visas_changed(other) == (False, "no_request")
    other["object"]["object_id"] = 10**9
    assert contract_visas.apply_visas_changed(other) == (False, "no_request")
    request.refresh_from_db()
    assert request.visas == []


def test_event_with_an_unknown_field_is_accepted(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    request = collect_visas(contract, [])
    event = _event(contract, request, _visas("approved", "approved"))
    event["new_field"] = "из будущей версии"

    assert contract_visas.apply_visas_changed(event)[0] is True
