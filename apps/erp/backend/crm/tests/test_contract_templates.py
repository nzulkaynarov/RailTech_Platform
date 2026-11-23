"""ДОК-10: договор — только из утверждённых шаблонов (DECISIONS 2026-11-23).

Каждый тест проверяет факт, из которого выводится статус: строка шаблона (`approval_status`, кто, когда), строка договора
(шаблон, редакция, замороженный текст, статус) и записи журнала. Защиты, без которых тест краснеет (мутационная проверка в PR):
фильтр «утверждён» в `offered_templates`, `is_approver`, `is_locked`, `unfilled_variables`, `send_blocker`.
"""

import pytest
from documents.models.documents import DocumentTemplate, DocumentTemplateKind, TemplateApproval
from parties.models.company_settings import CompanySettings

from crm.constants import ContractStatusCode as S
from crm.models import ActivityLog, Contract
from crm.services import contract_templates as svc
from crm.services.contracts import generate_contract_from_quote
from crm.tests.projects_world import api, pw  # noqa: F401

pytestmark = pytest.mark.django_db

BODY = "<p>1. Предмет договора: поставка.</p>{{doc.spec_table}}{{doc.totals}}{{doc.requisites_and_signatures}}"
TPL = "/api/v1/crm/document-templates/"
CT = "/api/v1/crm/contracts/{id}/{action}/"


@pytest.fixture
def approver(pw, grant):  # noqa: F811
    grant(pw.director, "contract.approve_template", "settings.edit")
    return pw.director


def make_template(
    pw,  # noqa: F811
    *,
    status=TemplateApproval.APPROVED,
    body=BODY,
    edition=1,
    name="Договор с клиентом · поставка",
    subject="supply",
):
    return DocumentTemplate.objects.create(
        company=pw.own,
        name=name,
        kind=DocumentTemplateKind.objects.get(code="CONTRACT"),
        body_html=body,
        approval_status=status,
        edition=edition,
        counterparty_kind="client",
        subject=subject,
        is_active=status == TemplateApproval.APPROVED,
    )


def rules(pw, **values):  # noqa: F811
    row, _ = CompanySettings.objects.get_or_create(company=pw.own)
    for key, value in values.items():
        setattr(row, key, value)
    row.save()


def generate(pw, **kw):  # noqa: F811
    return generate_contract_from_quote(pw.quote.id, actor=None, **kw)


def post(user, contract, action, body=None):
    return api(user).post(CT.format(id=contract.id, action=action), body or {}, format="json")


# ── предлагаются только утверждённые ──────────────────────────────────────────────────────────────────────────────


def test_unapproved_template_is_not_offered_and_cannot_be_chosen(pw):  # noqa: F811
    draft = make_template(pw, status=TemplateApproval.DRAFT, name="Черновик")
    pending = make_template(pw, status=TemplateApproval.ON_APPROVAL, name="На утверждении")
    approved = make_template(pw, name="Утверждённый")
    # действующий шаблон прежнего пути (is_active) без утверждения всё равно не предлагается
    DocumentTemplate.objects.filter(pk__in=[draft.pk, pending.pk]).update(is_active=True)
    ids = [t.id for t in svc.offered_templates(pw.own, "client")]
    assert ids == [approved.id]

    response = api(pw.director).get(f"{TPL}offered/?deal_id={pw.deal.id}")
    assert [row["id"] for row in response.json()["items"]] == [approved.id]

    for rejected in (draft, pending):
        contract, error = generate(pw, template_id=rejected.id)
        assert (contract, error) == (None, "CONTRACT_TEMPLATE_NOT_OFFERED")
    assert not Contract.objects.filter(deal=pw.deal).exists()


def test_partner_template_is_not_offered_for_a_client_deal(pw):  # noqa: F811
    template = make_template(pw)
    template.counterparty_kind = "partner"
    template.save()
    assert list(svc.offered_templates(pw.own, "client")) == []


# ── утверждение — по праву, не по роли ───────────────────────────────────────────────────────────────────────────


def test_only_the_holder_of_the_permission_approves(pw, approver, grant):  # noqa: F811
    template = make_template(pw, status=TemplateApproval.ON_APPROVAL)
    # у бухгалтера есть contract.manage и contract.sign, но не право «Право»
    denied = api(pw.accountant).post(f"{TPL}{template.id}/approve/", {}, format="json")
    assert denied.status_code == 403
    template.refresh_from_db()
    assert template.approval_status == TemplateApproval.ON_APPROVAL and template.approved_by_id is None

    ok = api(approver).post(f"{TPL}{template.id}/approve/", {}, format="json")
    assert ok.status_code == 200, ok.content
    template.refresh_from_db()
    assert template.approval_status == TemplateApproval.APPROVED
    assert template.approved_by_id == approver.pk and template.approved_at is not None and template.is_active
    assert ActivityLog.objects.filter(event_code="contract_template.approved", entity_id=template.id).exists()


def test_service_refuses_a_user_without_the_permission(pw):  # noqa: F811
    template = make_template(pw, status=TemplateApproval.ON_APPROVAL)
    assert svc.approve(template, pw.accountant) == (None, "TEMPLATE_APPROVAL_FORBIDDEN")
    assert svc.approve(template, None) == (None, "TEMPLATE_APPROVAL_FORBIDDEN")


def test_submit_needs_required_blocks_and_counterparty(pw):  # noqa: F811
    broken = make_template(pw, status=TemplateApproval.DRAFT, body="<p>Только текст</p>")
    assert svc.submit_for_approval(broken, pw.accountant) == (None, "TEMPLATE_MISSING_REQUIRED_BLOCKS")
    good = make_template(pw, status=TemplateApproval.DRAFT)
    template, error = svc.submit_for_approval(good, pw.accountant)
    assert error is None and template.approval_status == TemplateApproval.ON_APPROVAL and template.submitted_at


# ── закреплённый текст и редакции ────────────────────────────────────────────────────────────────────────────────


def test_approved_text_is_locked_and_edition_is_a_draft_copy(pw, approver):  # noqa: F811
    template = make_template(pw)
    patch = api(pw.director).patch(f"{TPL}{template.id}/", {"body_html": BODY + "<p>свой пункт</p>"}, format="json")
    assert patch.status_code == 400 and patch.json()["detail"] == "TEMPLATE_LOCKED"
    template.refresh_from_db()
    assert template.body_html == BODY

    created = api(pw.accountant).post(f"{TPL}{template.id}/new-edition/", {}, format="json")
    assert created.status_code == 201, created.content
    edition = DocumentTemplate.objects.get(pk=created.json()["id"])
    assert (edition.edition, edition.approval_status, edition.previous_edition_id) == (
        2,
        TemplateApproval.DRAFT,
        template.id,
    )
    assert edition.body_html == BODY and not edition.is_active
    changed = api(pw.director).patch(f"{TPL}{edition.id}/", {"body_html": BODY + "<p>новый пункт</p>"}, format="json")
    assert changed.status_code == 200, changed.content


def test_old_contract_keeps_its_edition_after_a_new_one_is_approved(pw, approver):  # noqa: F811
    rules(pw, contract_sign_before_send=False)
    first = make_template(pw)
    contract, error = generate(pw)
    assert error is None and contract.template_id == first.id and contract.template_edition == 1

    second, _ = svc.new_edition(first, pw.accountant)
    second.body_html = BODY + "<p>2. Новый пункт редакции 2.</p>"
    second.save()
    svc.submit_for_approval(second, pw.accountant)
    approved, error = svc.approve(second, approver)
    assert error is None
    first.refresh_from_db()
    assert not first.is_active and [t.id for t in svc.offered_templates(pw.own, "client")] == [approved.id]

    contract.refresh_from_db()
    assert contract.template_edition == 1 and contract.frozen_template_body == BODY


def test_text_of_a_contract_in_a_deal_cannot_be_edited(pw):  # noqa: F811
    make_template(pw)
    contract, _ = generate(pw)
    response = api(pw.director).patch(
        f"/api/v1/crm/contracts/{contract.id}/",
        {"frozen_template_body": "<p>подмена</p>", "template_edition": 9},
        format="json",
    )
    contract.refresh_from_db()
    assert contract.frozen_template_body == BODY and contract.template_edition == 1, response.content


# ── документ с незаполненным местом не регистрируется ────────────────────────────────────────────────────────────


def test_contract_with_an_unfilled_variable_is_not_registered(pw):  # noqa: F811
    make_template(pw, body=BODY + "<p>Срок: {{deal.unknown_term}}</p>")
    contract, error = generate(pw)
    assert (contract, error) == (None, "CONTRACT_TEMPLATE_UNFILLED")
    assert not Contract.objects.filter(deal=pw.deal).exists()
    entry = ActivityLog.objects.get(event_code="contract.template_unfilled")
    assert "deal.unknown_term" in entry.event_params["missing"]


# ── авто-отправка и отступления ──────────────────────────────────────────────────────────────────────────────────


def test_without_deviation_contract_goes_to_cabinet_by_itself(pw):  # noqa: F811
    rules(pw, contract_auto_send=True, contract_sign_before_send=False)
    make_template(pw)
    contract, error = generate(pw)
    assert error is None and contract.status.code == S.PENDING_CLIENT


def test_auto_send_off_keeps_the_draft(pw):  # noqa: F811
    rules(pw, contract_auto_send=False, contract_sign_before_send=False)
    make_template(pw)
    contract, _ = generate(pw)
    assert contract.status.code == S.DRAFT


def test_our_signature_comes_first_and_then_it_goes(pw):  # noqa: F811
    rules(pw, contract_auto_send=True, contract_sign_before_send=True)
    make_template(pw)
    contract, _ = generate(pw)
    assert contract.status.code == S.DRAFT and svc.send_blocker(contract) == "CONTRACT_NEEDS_OUR_SIGNATURE"
    assert post(pw.accountant, contract, "send-to-client").status_code == 409

    assert post(pw.director, contract, "sign-ours").status_code == 200
    contract.refresh_from_db()
    assert contract.manager_signed_at is not None and contract.status.code == S.PENDING_CLIENT


def test_deviation_blocks_until_decision_and_visas_apply_only_to_it(pw, approver):  # noqa: F811
    rules(pw, contract_auto_send=True, contract_sign_before_send=True)
    make_template(pw)
    contract, _ = generate(pw)
    assert not svc.visas_required(contract)  # по шаблону без отступлений виз нет

    assert post(pw.accountant, contract, "request-deviation", {"text": "Оплата 30 дней"}).status_code == 200
    contract.refresh_from_db()
    assert svc.deviation_state(contract) == "requested" and svc.visas_required(contract)

    assert post(pw.accountant, contract, "sign-ours").status_code == 200  # подпись есть, а отправки нет
    contract.refresh_from_db()
    assert contract.status.code == S.DRAFT
    blocked = post(pw.accountant, contract, "send-to-client")
    assert blocked.status_code == 409 and blocked.json()["detail"] == "CONTRACT_DEVIATION_PENDING"

    # решает только держатель права
    assert post(pw.accountant, contract, "decide-deviation", {"approve": True}).status_code == 403
    assert post(approver, contract, "decide-deviation", {"approve": True}).status_code == 200
    contract.refresh_from_db()
    assert contract.deviation_decision == "approved" and "Оплата 30 дней" in contract.notes
    assert contract.status.code == S.DRAFT  # с отступлением сам не уходит: дальше визы
    assert svc.visas_required(contract)
    assert post(pw.accountant, contract, "send-to-client").status_code == 200


def test_rejected_deviation_returns_the_contract_to_the_normal_path(pw, approver):  # noqa: F811
    rules(pw, contract_auto_send=True, contract_sign_before_send=False)
    make_template(pw)
    contract, _ = generate(pw)  # без подписи до отправки уходит сразу, отступление не успеть — проверим запрет
    assert post(pw.accountant, contract, "request-deviation", {"text": "x"}).status_code == 409

    rules(pw, contract_sign_before_send=True)
    Contract.objects.filter(pk=contract.pk).delete()
    contract, _ = generate(pw)
    post(pw.accountant, contract, "request-deviation", {"text": "Особый пункт"})
    post(pw.director, contract, "sign-ours")
    assert post(approver, contract, "decide-deviation", {"approve": False}).status_code == 200
    contract.refresh_from_db()
    assert contract.deviation_decision == "rejected" and "Особый пункт" not in contract.notes
    assert contract.status.code == S.PENDING_CLIENT and not svc.visas_required(contract)


def test_deviations_can_be_switched_off(pw):  # noqa: F811
    rules(pw, contract_deviations_allowed=False)
    make_template(pw)
    contract, _ = generate(pw)
    response = post(pw.accountant, contract, "request-deviation", {"text": "Особый пункт"})
    assert response.status_code == 409 and response.json()["detail"] == "CONTRACT_DEVIATIONS_DISABLED"


# ── переходный режим и настройки ─────────────────────────────────────────────────────────────────────────────────


def test_without_approved_templates_the_old_path_still_works(pw):  # noqa: F811
    make_template(pw, status=TemplateApproval.DRAFT)
    contract, error = generate(pw)
    assert error is None and contract.template_id is None and contract.status.code == S.PENDING_CLIENT


def test_default_template_comes_from_settings(pw):  # noqa: F811
    make_template(pw, name="А первый")
    chosen = make_template(pw, name="Я по умолчанию")
    rules(pw, default_client_contract_template=chosen, contract_sign_before_send=False)
    contract, _ = generate(pw)
    assert contract.template_id == chosen.id


def test_settings_accept_only_approved_templates_of_the_kind(pw):  # noqa: F811
    from accounts.services.company_settings import update_company_settings

    draft = make_template(pw, status=TemplateApproval.DRAFT)
    assert update_company_settings(pw.admin, pw.own, {"default_client_contract_template": draft.id})[1] == (
        "BAD_CONTRACT_TEMPLATE"
    )
    approved = make_template(pw)
    row, error = update_company_settings(
        pw.admin,
        pw.own,
        {"default_client_contract_template": approved.id, "contract_auto_send": False},
    )
    assert error is None and row.default_client_contract_template_id == approved.id and not row.contract_auto_send


# ── ревью: настройка переживает новую редакцию, запасной порядок, замки, враждебные входы ─────────────────────────


def test_default_template_survives_a_new_edition(pw, approver):  # noqa: F811
    first = make_template(pw)
    rules(pw, default_client_contract_template=first, contract_sign_before_send=False)
    second, _ = svc.new_edition(first, pw.accountant)
    svc.submit_for_approval(second, pw.accountant)
    approved, error = svc.approve(second, approver)
    assert error is None
    assert CompanySettings.objects.get(company=pw.own).default_client_contract_template_id == approved.id
    contract, _ = generate(pw)
    assert contract.template_id == approved.id and contract.template_edition == 2


def test_default_follows_the_whole_edition_chain(pw, approver):  # noqa: F811
    first = make_template(pw)
    rules(pw, default_client_contract_template=first)
    current = first
    for _ in range(2):
        nxt, _ = svc.new_edition(current, pw.accountant)
        svc.submit_for_approval(nxt, pw.accountant)
        current, error = svc.approve(nxt, approver)
        assert error is None
    assert CompanySettings.objects.get(company=pw.own).default_client_contract_template_id == current.id


def test_fallback_picks_supply_before_services(pw):  # noqa: F811
    make_template(pw, name="Договор с клиентом · услуги", subject="services")
    supply = make_template(pw, name="Договор с клиентом · поставка", subject="supply")
    rules(pw, contract_sign_before_send=False)
    contract, _ = generate(pw)  # настройки по умолчанию нет — запасной порядок явный, не по алфавиту кода
    assert contract.template_id == supply.id


def test_approved_template_cannot_be_deleted(pw, approver):  # noqa: F811
    template = make_template(pw)
    response = api(pw.director).delete(f"{TPL}{template.id}/")
    assert response.status_code == 400 and response.json()["detail"] == "TEMPLATE_LOCKED"
    assert DocumentTemplate.objects.filter(pk=template.pk).exists()


def test_replaced_edition_cannot_be_switched_back_on(pw, approver):  # noqa: F811
    first = make_template(pw)
    second, _ = svc.new_edition(first, pw.accountant)
    svc.submit_for_approval(second, pw.accountant)
    svc.approve(second, approver)
    response = api(pw.director).patch(f"{TPL}{first.id}/", {"is_active": True}, format="json")
    assert response.status_code == 400 and response.json()["detail"] == "TEMPLATE_LOCKED"
    assert [t.id for t in svc.offered_templates(pw.own, "client")] == [second.id]
    # и действующую нельзя выключить в обход утверждения: договоры ушли бы в переходный режим без блокировок
    off = api(pw.director).patch(f"{TPL}{second.id}/", {"is_active": False}, format="json")
    assert off.status_code == 400 and off.json()["detail"] == "TEMPLATE_LOCKED"


def test_draft_template_can_still_be_deleted(pw, approver):  # noqa: F811
    draft = make_template(pw, status=TemplateApproval.DRAFT)
    assert api(pw.director).delete(f"{TPL}{draft.id}/").status_code == 204


def test_card_does_not_promise_send_without_our_signature(pw):  # noqa: F811
    from crm.services import contract_flow

    rules(pw, contract_auto_send=False, contract_sign_before_send=True)
    make_template(pw)
    contract, _ = generate(pw)
    assert "send_to_client" not in contract_flow.allowed_actions(contract, pw.accountant)
    post(pw.director, contract, "sign-ours")
    contract.refresh_from_db()
    assert "send_to_client" in contract_flow.allowed_actions(contract, pw.accountant)


def test_card_hides_send_while_deviation_is_requested(pw, approver):  # noqa: F811
    from crm.services import contract_flow

    rules(pw, contract_auto_send=True, contract_sign_before_send=True)
    make_template(pw)
    contract, _ = generate(pw)
    assert post(pw.accountant, contract, "request-deviation", {"text": "Оплата 30 дней"}).status_code == 200
    post(pw.director, contract, "sign-ours")
    contract.refresh_from_db()
    assert svc.deviation_state(contract) == "requested"
    assert "send_to_client" not in contract_flow.allowed_actions(contract, pw.accountant)
    post(approver, contract, "decide-deviation", {"approve": True})
    contract.refresh_from_db()
    assert "send_to_client" in contract_flow.allowed_actions(contract, pw.accountant)


def test_hostile_ids_give_400_or_404_not_500(pw, approver):  # noqa: F811
    make_template(pw)
    bad = api(pw.director).post(
        "/api/v1/crm/contracts/generate-from-quote/", {"quote_id": pw.quote.id, "template_id": "abc"}, format="json"
    )
    assert bad.status_code == 400 and bad.json()["detail"] == "BAD_ID"
    bad_quote = api(pw.director).post("/api/v1/crm/contracts/generate-from-quote/", {"quote_id": "x"}, format="json")
    assert bad_quote.status_code == 400

    missing = Contract(id=999999)
    for action, body in (
        ("sign-ours", {}),
        ("request-deviation", {"text": "x"}),
        ("decide-deviation", {"approve": True}),
    ):
        assert post(approver, missing, action, body).status_code == 404

    assert api(approver).get(f"{TPL}offered/?deal_id=abc").status_code == 400
    assert api(approver).get(f"{TPL}offered/?deal_id=999999").status_code == 404


def test_template_actions_respect_the_contract_scope(pw):  # noqa: F811
    rules(pw, contract_sign_before_send=True)
    make_template(pw)
    contract, _ = generate(pw)
    for action, body in (
        ("sign-ours", {}),
        ("request-deviation", {"text": "x"}),
        ("decide-deviation", {"approve": True}),
    ):
        assert post(pw.stranger, contract, action, body).status_code in (403, 404)
    contract.refresh_from_db()
    assert contract.manager_signed_at is None and svc.deviation_state(contract) == "none"
    assert api(pw.stranger).get(f"{TPL}offered/?deal_id={pw.deal.id}").status_code in (403, 404)
