"""ОСН-1: базовый документ компании — роль на шаблоне договора, одна утверждённая действующая редакция на роль.

Защиты, без которых тесты краснеют (мутационная проверка в PR): проверка «роль занята» в `contract_templates.approve`,
снятие прежних редакций той же цепочки, закрепление роли вместе с текстом (`is_locked` в `update_template`).
"""

import pytest
from django.core.exceptions import ValidationError
from documents.models.documents import DocumentTemplate, DocumentTemplateKind, TemplateApproval
from parties.models.company_settings import CompanySettings

from crm.services import contract_templates as svc
from crm.services.generated_documents import update_template
from crm.tests.projects_world import api, pw  # noqa: F401

pytestmark = pytest.mark.django_db

BODY = "<p>1. Предмет.</p>{{doc.spec_table}}{{doc.totals}}{{doc.requisites_and_signatures}}"
TPL = "/api/v1/crm/document-templates/"


@pytest.fixture
def approver(pw, grant):  # noqa: F811
    grant(pw.director, "contract.approve_template", "settings.edit")
    return pw.director


def draft(pw, role="", name="Соглашение о неразглашении", **extra):  # noqa: F811
    return DocumentTemplate.objects.create(
        company=pw.own,
        name=name,
        kind=DocumentTemplateKind.objects.get(code="CONTRACT"),
        body_html=BODY,
        approval_status=TemplateApproval.ON_APPROVAL,
        edition=extra.pop("edition", 1),
        counterparty_kind="partner",
        subject="supply",
        base_role=role,
        is_active=False,
        **extra,
    )


def test_second_active_template_of_the_same_role_is_refused(pw, approver):  # noqa: F811
    first = draft(pw, "nda", name="NDA 1")
    second = draft(pw, "nda", name="NDA 2")
    assert svc.approve(first, approver)[1] is None
    template, error = svc.approve(second, approver)
    assert (template, error) == (None, "TEMPLATE_BASE_ROLE_TAKEN")


def test_concurrent_approval_of_the_same_role_is_a_refusal_not_a_500(pw, approver, monkeypatch):  # noqa: F811
    """Параллельное утверждение двух шаблонов одной роли: уникальный индекс срабатывает после проверки — код отказа,
    и ничего не меняется (прежняя редакция остаётся действующей)."""
    from django.db import IntegrityError

    first = draft(pw, "nda", name="NDA 1")
    second = draft(pw, "nda", name="NDA 2")
    assert svc.approve(first, approver)[1] is None
    first_chain = svc.edition_chain_ids
    monkeypatch.setattr(svc, "edition_chain_ids", lambda tpl: {first.pk, *first_chain(tpl)})

    def boom(self, *args, **kwargs):
        raise IntegrityError("doctpl_one_active_base_role")

    monkeypatch.setattr(DocumentTemplate, "save", boom)
    template, error = svc.approve(second, approver)
    assert (template, error) == (None, "TEMPLATE_BASE_ROLE_TAKEN")
    monkeypatch.undo()
    first.refresh_from_db()
    assert first.is_active and first.approval_status == TemplateApproval.APPROVED
    second.refresh_from_db()
    assert second.approval_status == TemplateApproval.ON_APPROVAL
    assert svc.base_template(pw.own, "nda").pk == first.pk


def test_new_edition_replaces_the_previous_one_of_the_same_chain(pw, approver):  # noqa: F811
    first = draft(pw, "partnership", name="Договор о партнёрстве")
    svc.approve(first, approver)
    first.refresh_from_db()
    edition, error = svc.new_edition(first, approver)
    assert error is None and edition.base_role == "partnership"
    edition.name = "Договор о партнёрстве (новая редакция)"  # название другое — цепочка всё равно одна
    edition.approval_status = TemplateApproval.ON_APPROVAL
    edition.save()
    assert svc.approve(edition, approver)[1] is None
    first.refresh_from_db()
    assert first.is_active is False
    assert svc.base_template(pw.own, "partnership").pk == edition.pk
    active = DocumentTemplate.objects.filter(company=pw.own, base_role="partnership", is_active=True)
    assert active.count() == 1


def test_roles_do_not_clash_and_plain_templates_have_no_role(pw, approver):  # noqa: F811
    nda, partnership, plain = draft(pw, "nda", name="A"), draft(pw, "partnership", name="B"), draft(pw, "", name="C")
    plain2 = draft(pw, "", name="D")
    for template in (nda, partnership, plain, plain2):
        assert svc.approve(template, approver)[1] is None
    assert svc.base_template(pw.own, "offer") is None


def test_role_is_part_of_the_text_set_in_draft_locked_afterwards(pw, approver):  # noqa: F811
    template = draft(pw, "", name="NDA")
    template.approval_status = TemplateApproval.DRAFT
    template.save()
    update_template(template, term={"base_role": "nda"})
    template.refresh_from_db()
    assert template.base_role == "nda"
    with pytest.raises(ValidationError) as bad:
        update_template(template, term={"base_role": "contract"})
    assert bad.value.messages == ["TEMPLATE_BASE_ROLE_INVALID"]
    template.approval_status = TemplateApproval.ON_APPROVAL
    template.save()
    with pytest.raises(ValidationError) as locked:
        update_template(template, term={"base_role": "offer"})
    assert locked.value.messages == ["TEMPLATE_LOCKED"]


def test_role_is_written_through_the_api_and_listed(pw, approver):  # noqa: F811
    created = api(approver).post(
        f"{TPL}create-contract/",
        {"name": "Оферта", "counterparty_kind": "client", "subject": "supply", "base_role": "offer"},
        format="json",
    )
    assert created.status_code == 201 and created.json()["base_role"] == "offer"
    row = [r for r in api(approver).get(f"{TPL}contracts/").json() if r["id"] == created.json()["id"]][0]
    assert row["base_role"] == "offer"
    bad = api(approver).post(
        f"{TPL}create-contract/",
        {"name": "X", "counterparty_kind": "client", "subject": "supply", "base_role": "zzz"},
        format="json",
    )
    assert bad.status_code == 400


def test_partner_roles_are_a_company_setting_with_a_default(pw):  # noqa: F811
    assert svc.partner_base_roles(pw.own) == ["partnership", "nda"]
    row, _ = CompanySettings.objects.get_or_create(company=pw.own)
    row.partner_base_roles = ["offer", "nda"]
    row.save()
    assert svc.partner_base_roles(pw.own) == ["nda", "offer"]
