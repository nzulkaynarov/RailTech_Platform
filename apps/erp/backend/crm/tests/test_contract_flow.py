"""Статусы договора вместо подписи кликом (D2-5, SPEC-v3 §2.4): допустимые и недопустимые переходы, права, объект, скан, события.

Покрыто:
* вся цепочка Проект → На согласовании → Согласован клиентом → Выставлен у оператора → Подписан (скан) → сделка `CLOSED_WON`;
* таблица недопустимых переходов: любое действие из любого статуса, где оно не разрешено, — 409 `CONTRACT_TRANSITION_NOT_ALLOWED`;
* права домена: прямой вызов без `contract.manage` / `contract.sign` — 403 `ROLE_NOT_PERMITTED`; менеджер и снабженец не действуют;
  посторонний (участник компании клиента) — 403, чужого договора не видит;
* скан: PDF и изображения, сигнатура байтов, лимит, пустой файл; договор остаётся «Выставлен у оператора» при отказе;
* журнал (кто, когда, причина) и событие `contract.status_changed` по схеме контракта в той же транзакции.
"""

import pytest
from django.db import transaction
from integration.tests import bus_support

from crm import services as crm_services
from crm.constants import ContractStatusCode as S
from crm.constants import DealStageCode
from crm.models import ActivityLog, Contract, Deal
from crm.services import contract_flow
from crm.tests.projects_world import PDF, PNG, api, contract_in, pw, scan  # noqa: F401

pytestmark = pytest.mark.django_db

URL = "/api/v1/crm/contracts/{id}/{action}/"

# (действие, URL-имя, тело, разрешённые статусы)
CASES = [
    ("send_to_client", "send-to-client", {}, {S.DRAFT}),
    ("client_agreed", "client-agreed", {}, {S.PENDING_CLIENT}),
    (
        "reject",
        "reject",
        {"reason": "Не устраивает срок оплаты"},
        {S.PENDING_CLIENT, S.PENDING_MANAGER, S.ISSUED_EXTERNAL},
    ),
    ("revise", "revise", {}, {S.REJECTED}),
    ("mark_issued", "mark-issued", {"note": "Didox"}, {S.PENDING_MANAGER}),
]
ALL = [S.DRAFT, S.PENDING_CLIENT, S.PENDING_MANAGER, S.ISSUED_EXTERNAL, S.SIGNED, S.REJECTED, S.CANCELLED]


def _post(user, contract, action, body=None, **kw):
    return api(user).post(URL.format(id=contract.id, action=action), body or {}, format=kw.pop("format", "json"))


def _status(contract) -> str:
    contract.refresh_from_db()
    return contract.status.code


def test_full_chain_from_project_to_signed_scan(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    assert contract_flow.contract_v3_status(contract) == "project" and not contract_flow.contract_sent_to_client(
        contract
    )

    assert _post(pw.accountant, contract, "send-to-client").status_code == 200
    assert _status(contract) == S.PENDING_CLIENT
    assert _post(pw.accountant, contract, "client-agreed").status_code == 200
    assert _status(contract) == S.PENDING_MANAGER and contract.client_signed_at is not None
    assert _post(pw.accountant, contract, "mark-issued", {"note": "Didox, № 77"}).status_code == 200
    assert _status(contract) == S.ISSUED_EXTERNAL

    response = _post(pw.accountant, contract, "attach-scan", {"file": scan()}, format="multipart")
    assert response.status_code == 200, response.content
    contract.refresh_from_db()
    assert contract.status.code == S.SIGNED and contract.signed_file and contract.is_fully_signed
    assert (
        Deal.objects.get(pk=pw.deal.pk).stage.code == DealStageCode.CLOSED_WON
    ), "договор подписан — сделка закрыта как выигранная"


def test_journal_and_events_follow_every_transition(pw):  # noqa: F811
    contract = contract_in(pw, S.PENDING_MANAGER, client_signed_at=pw.deal.created_at)
    _post(pw.accountant, contract, "mark-issued", {"note": "Didox, № 77"})
    entry = ActivityLog.objects.get(event_code="contract.issued_external")
    assert entry.user_id == pw.accountant.pk and entry.entity_type == "contract" and entry.entity_id == contract.id
    assert entry.event_params["note"] == "Didox, № 77" and entry.deal_id == pw.deal.pk

    event = bus_support.only("contract.status_changed")
    bus_support.assert_matches_contract(event)
    assert event["data"]["payload"] == {
        "erp_contract_id": contract.id,
        "number": contract.number,
        "status": "issued_at_operator",
        "sent_to_client": True,
        "amount": "5000000.00",
        "currency": "UZS",
    }
    assert event["data"]["actor"]["type"] == "staff"


def test_reject_needs_a_reason_and_revise_returns_the_draft(pw):  # noqa: F811
    contract = contract_in(pw, S.PENDING_CLIENT)
    assert _post(pw.accountant, contract, "reject").json() == {"detail": "REASON_REQUIRED"}
    assert _post(pw.accountant, contract, "reject", {"reason": "  "}).status_code == 400
    assert _status(contract) == S.PENDING_CLIENT
    assert _post(pw.accountant, contract, "reject", {"reason": "Неустойка слишком большая"}).status_code == 200
    assert _status(contract) == S.REJECTED
    assert ActivityLog.objects.get(event_code="contract.rejected").reason == "Неустойка слишком большая"
    assert (
        bus_support.published("contract.status_changed")[-1]["data"]["payload"]["reason"] == "Неустойка слишком большая"
    )

    assert _post(pw.accountant, contract, "revise").status_code == 200
    contract.refresh_from_db()
    assert (
        contract.status.code == S.DRAFT and contract.client_signed_at is None
    ), "новая редакция — согласие клиента сброшено"


@pytest.mark.parametrize(("action", "slug", "body", "allowed"), CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("status", ALL)
def test_transition_only_from_allowed_statuses(pw, action, slug, body, allowed, status):  # noqa: F811
    contract = contract_in(pw, status)
    response = _post(pw.accountant, contract, slug, body)
    if status in allowed:
        assert response.status_code == 200, response.content
    else:
        assert response.status_code == 409 and response.json() == {"detail": "CONTRACT_TRANSITION_NOT_ALLOWED"}
        assert _status(contract) == status, "недопустимый переход не меняет договор"
        assert not bus_support.published("contract.status_changed")


@pytest.mark.parametrize("status", [s for s in ALL if s != S.ISSUED_EXTERNAL])
def test_scan_only_from_issued_at_operator(pw, status):  # noqa: F811
    contract = contract_in(pw, status)
    response = _post(pw.accountant, contract, "attach-scan", {"file": scan()}, format="multipart")
    assert response.status_code == 409
    contract.refresh_from_db()
    assert contract.status.code == status and not contract.signed_file


def test_signed_contract_is_final(pw):  # noqa: F811
    contract = contract_in(pw, S.SIGNED)
    for _action, slug, body, _ in CASES:
        assert _post(pw.director, contract, slug, body).status_code == 409
    assert _post(pw.director, contract, "attach-scan", {"file": scan()}, format="multipart").status_code == 409


@pytest.mark.parametrize(
    ("name", "content", "content_type", "ok"),
    [
        ("scan.pdf", PDF, "application/pdf", True),
        ("scan.png", PNG, "image/png", True),
        ("scan.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 16, "image/jpeg", True),
        ("fake.pdf", b"MZ\x90\x00 not a pdf", "application/pdf", False),  # сигнатура не совпала с расширением
        ("scan.png", PDF, "image/png", False),
        ("virus.exe", b"MZ\x90\x00", "application/octet-stream", False),
        ("scan.svg", b"<svg onload='x'/>", "image/svg+xml", False),
        ("scan.pdf", PDF, "text/html", False),  # заявленный тип не из списка
        ("empty.pdf", b"", "application/pdf", False),
    ],
)
def test_scan_is_checked_by_signature_and_type(pw, name, content, content_type, ok):  # noqa: F811
    contract = contract_in(pw, S.ISSUED_EXTERNAL)
    response = _post(
        pw.accountant, contract, "attach-scan", {"file": scan(name, content, content_type)}, format="multipart"
    )
    if ok:
        assert response.status_code == 200, response.content
        assert _status(contract) == S.SIGNED
    else:
        assert response.status_code == 400 and response.json()["detail"] in ("SCAN_INVALID", "NO_FILE_PROVIDED")
        contract.refresh_from_db()
        assert contract.status.code == S.ISSUED_EXTERNAL and not contract.signed_file, "отказ не меняет договор"
        assert not ActivityLog.objects.filter(event_code="contract.scan_attached").exists()


def test_scan_over_the_limit_is_rejected(pw, settings):  # noqa: F811
    contract = contract_in(pw, S.ISSUED_EXTERNAL)
    big = scan("big.pdf", PDF + b"\x00" * (20 * 1024 * 1024 + 1))
    response = _post(pw.accountant, contract, "attach-scan", {"file": big}, format="multipart")
    assert response.status_code == 400 and response.json()["detail"] == "SCAN_INVALID"
    assert _status(contract) == S.ISSUED_EXTERNAL


def test_scan_is_required(pw):  # noqa: F811
    contract = contract_in(pw, S.ISSUED_EXTERNAL)
    assert _post(pw.accountant, contract, "attach-scan", {}, format="multipart").status_code == 400
    assert _status(contract) == S.ISSUED_EXTERNAL


# ── Права домена и объектная проверка ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("who", ["manager", "supply", "outsider", "stranger"])
@pytest.mark.parametrize(("action", "slug", "body", "allowed"), CASES, ids=[c[0] for c in CASES])
def test_no_permission_means_403_in_the_domain(pw, who, action, slug, body, allowed):  # noqa: F811
    """Прямой вызов домена ERP без права роли: менеджер и снабженец (`eds.projects` — чтение) и посторонний — 403."""
    status = sorted(allowed)[0]
    contract = contract_in(pw, status)
    response = _post(getattr(pw, who), contract, slug, body)
    assert response.status_code == 403, (who, response.content)
    assert _status(contract) == status
    assert not bus_support.published("contract.status_changed")


@pytest.mark.parametrize("who", ["manager", "supply", "outsider", "stranger"])
def test_scan_without_permission_is_403(pw, who):  # noqa: F811
    contract = contract_in(pw, S.ISSUED_EXTERNAL)
    response = _post(getattr(pw, who), contract, "attach-scan", {"file": scan()}, format="multipart")
    assert response.status_code == 403
    contract.refresh_from_db()
    assert contract.status.code == S.ISSUED_EXTERNAL and not contract.signed_file


def test_manage_without_sign_cannot_issue_or_attach(pw, grant):  # noqa: F811
    """`contract.manage` готовит договор, но выставить у оператора и приложить скан — только `contract.sign`."""
    from accounts.models import CompanyMember
    from crm.tests.projects_world import _staff

    owner = CompanyMember.objects.get(user=pw.accountant).role
    preparer = _staff(pw.own, "prep@own.test", owner)
    grant(preparer, "contract.manage")
    contract = contract_in(pw, S.PENDING_MANAGER)
    assert _post(preparer, contract, "mark-issued").status_code == 403
    contract = contract_in(pw, S.PENDING_CLIENT)
    assert _post(preparer, contract, "client-agreed").status_code == 200


def test_a_stranger_does_not_see_the_contract_nor_acts_on_it(pw):  # noqa: F811
    contract = contract_in(pw, S.PENDING_CLIENT)
    assert api(pw.stranger).get(f"/api/v1/crm/contracts/{contract.id}/").status_code in (403, 404)
    assert _post(pw.stranger, contract, "client-agreed").status_code in (403, 404)
    assert _status(contract) == S.PENDING_CLIENT


def test_service_checks_the_right_even_without_the_view_gate(pw):  # noqa: F811
    """Сервис не полагается на вьюху: вызов напрямую от менеджера без `contract.manage` — отказ."""
    contract = contract_in(pw, S.DRAFT)
    updated, error = contract_flow.apply_transition(contract.id, "send_to_client", pw.manager)
    assert updated is None and error == "MEMBER_REQUIRED_FOR_ACTION"
    updated, error = contract_flow.apply_transition(contract.id, "send_to_client", pw.director)
    assert error is None and updated.status.code == S.PENDING_CLIENT
    assert contract_flow.apply_transition(10**9, "send_to_client", pw.director) == (None, "CONTRACT_NOT_FOUND")
    assert contract_flow.apply_transition(contract.id, "no_such_action", pw.director) == (
        None,
        "CONTRACT_TRANSITION_NOT_ALLOWED",
    )


def test_allowed_actions_follow_status_and_rights(pw):  # noqa: F811
    contract = contract_in(pw, S.PENDING_MANAGER)
    assert contract_flow.allowed_actions(contract, pw.accountant) == ["reject", "mark_issued"]
    assert contract_flow.allowed_actions(contract, pw.manager) == []
    assert contract_flow.allowed_actions(contract, pw.outsider) == []
    assert set(contract_flow.allowed_actions(contract, pw.admin)) == {"reject", "mark_issued"}


# ── Создание проекта договора и события ───────────────────────────────────────────────────────────────


def test_generate_from_quote_without_sending_keeps_the_draft(pw):  # noqa: F811
    response = api(pw.accountant).post(
        "/api/v1/crm/contracts/generate-from-quote/", {"quote_id": pw.quote.id, "send_to_client": False}, format="json"
    )
    assert response.status_code == 201, response.content
    contract = Contract.objects.get(pk=response.json()["id"])
    assert contract.status.code == S.DRAFT
    assert not bus_support.published("document.created"), "клиенту проект не виден — документа в портале нет"
    event = bus_support.only("contract.status_changed")
    assert event["data"]["payload"]["status"] == "project" and event["data"]["payload"]["sent_to_client"] is False
    bus_support.assert_matches_contract(event)

    assert _post(pw.accountant, contract, "send-to-client").status_code == 200
    assert bus_support.published("contract.status_changed")[-1]["data"]["payload"]["sent_to_client"] is True
    assert len(bus_support.published("document.created")) == 1, "договор стал виден клиенту — один раз"


def test_generate_from_quote_default_keeps_the_old_behaviour(pw):  # noqa: F811
    contract, error = crm_services.generate_contract_from_quote(pw.quote.id, actor=pw.director)
    assert error is None and contract.status.code == S.PENDING_CLIENT


def test_generate_from_quote_requires_staff_rights(pw):  # noqa: F811
    for user in (pw.manager, pw.supply):
        response = api(user).post(
            "/api/v1/crm/contracts/generate-from-quote/",
            {"quote_id": pw.quote.id, "send_to_client": False},
            format="json",
        )
        assert response.status_code == 403
    assert Contract.objects.filter(deal=pw.deal).count() == 0


def test_status_event_is_not_published_when_the_transaction_rolls_back(pw):  # noqa: F811
    contract = contract_in(pw, S.PENDING_MANAGER)
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            contract_flow.apply_transition(contract.id, "mark_issued", pw.accountant)
            assert bus_support.types() == ["contract.status_changed"]
            raise RuntimeError("позже в той же транзакции что-то упало")
    assert bus_support.published() == []
    assert _status(contract) == S.PENDING_MANAGER


def test_portal_client_signature_reads_as_client_agreed(pw):  # noqa: F811
    """Клиент в портале «подписывает» — для сотрудника это «Согласован клиентом»; событие статуса публикуется."""
    contract = contract_in(pw, S.PENDING_CLIENT)
    from parties.models import Contact

    contact = Contact.objects.filter(company=pw.client).first()
    updated, error = crm_services.sign_contract_by_client(contract.id, portal_contact=contact)
    assert error is None and updated.status.code == S.PENDING_MANAGER
    assert contract_flow.contract_v3_status(updated) == "client_agreed"
    assert bus_support.only("contract.status_changed")["data"]["payload"]["status"] == "client_agreed"
