"""ДС-1: срок договора — расчёт при подписании, продление ночной задачей, отказ, окончание срока.

Каждый тест проверяет факт, из которого выводится состояние: строки договора (`valid_until`, `last_notice_date`,
`renewals_count`, `renewal_declined_*`), журнал, уведомления. Защиты, без которых тест краснеет (мутационная проверка в
PR): `apply_at_signing` в `contract_flow.apply_transition`, проверка `valid_until < today` и метка в `term_reminders`,
срок отказа в `decline_renewal`, `new_work_error` в `_run_draft_quote_gates` и пропуск сделок с КП.
"""

import datetime as dt

import pytest
from documents.models.documents import DocumentTemplate, DocumentTemplateKind, TemplateApproval
from parties.models.company_settings import CompanySettings

from core.models import Country
from crm.constants import ContractStatusCode as S
from crm.models import ActivityLog, Contract
from crm.services import contract_term as svc
from crm.services import draft_quote
from crm.tests.projects_world import api, contract_in, pw, scan  # noqa: F401

pytestmark = pytest.mark.django_db

D = dt.date


def signed(pw, signed_on=D(2026, 3, 10), **fields):  # noqa: F811
    """Подписанный договор со сроком, вычисленным из правила на `signed_on`."""
    contract = contract_in(pw, S.SIGNED, **fields)
    svc.apply_at_signing(contract, signed_on=signed_on)
    contract.refresh_from_db()
    return contract


def rules(pw, **values):  # noqa: F811
    row, _ = CompanySettings.objects.get_or_create(company=pw.own)
    for key, value in values.items():
        setattr(row, key, value)
    row.save()


# ── срок при подписании ────────────────────────────────────────────────────────────────────────────────────────────


def test_signing_sets_term_from_the_company_rule(pw):  # noqa: F811
    contract = signed(pw, D(2026, 3, 10))
    assert (contract.valid_from, contract.valid_until) == (D(2026, 3, 10), D(2026, 12, 31))
    assert contract.last_notice_date == D(2026, 12, 1)
    assert (contract.term_rule, contract.renewal_mode, contract.notice_days) == ("calendar_year", "auto", 30)
    assert ActivityLog.objects.filter(event_code="contract.term_set", entity_id=contract.pk).exists()


def test_signing_on_the_december_boundary_gives_next_year(pw):  # noqa: F811
    contract = signed(pw, D(2026, 12, 1))
    assert contract.valid_until == D(2027, 12, 31)


def test_template_overrides_the_company_rule(pw):  # noqa: F811
    template = DocumentTemplate.objects.create(
        company=pw.own,
        name="NDA",
        kind=DocumentTemplateKind.objects.get(code="CONTRACT"),
        approval_status=TemplateApproval.APPROVED,
        term_rule="twelve_months",
        renewal_mode="none",
        notice_days=10,
        confidentiality_years=3,
    )
    contract = signed(pw, D(2026, 3, 10), template=template)
    assert (contract.valid_until, contract.renewal_mode, contract.last_notice_date) == (
        D(2027, 3, 9),
        "none",
        D(2027, 2, 27),
    )


def test_foreign_counterparty_is_renewed_by_agreement_not_automatically(pw):  # noqa: F811
    pw.client.country = Country.objects.get_or_create(code="DE", defaults={"name": "Germany"})[0]
    pw.client.save()
    contract = signed(pw)
    assert contract.renewal_mode == "by_agreement" and contract.term_foreign
    svc.run_daily(D(2027, 1, 5))
    contract.refresh_from_db()
    assert contract.valid_until == D(2026, 12, 31) and contract.renewals_count == 0  # сам не продлился


def test_signing_twice_keeps_the_first_term(pw):  # noqa: F811
    contract = signed(pw, D(2026, 3, 10))
    svc.apply_at_signing(contract, signed_on=D(2026, 9, 1))
    contract.refresh_from_db()
    assert contract.valid_from == D(2026, 3, 10)


def test_attach_scan_sets_the_term(pw):  # noqa: F811
    contract = contract_in(pw, S.ISSUED_EXTERNAL)
    response = api(pw.accountant).post(
        f"/api/v1/crm/contracts/{contract.id}/attach-scan/", {"file": scan()}, format="multipart"
    )
    assert response.status_code == 200, response.content
    contract.refresh_from_db()
    assert contract.valid_until is not None and contract.last_notice_date is not None


# ── ночная задача ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_auto_renewal_moves_the_term_and_is_idempotent(pw):  # noqa: F811
    contract = signed(pw)
    assert svc.run_daily(D(2026, 12, 31))["renewed"] == 0  # последний день срока ещё действует
    assert svc.run_daily(D(2027, 1, 2))["renewed"] == 1
    contract.refresh_from_db()
    assert (contract.valid_from, contract.valid_until, contract.renewals_count) == (
        D(2027, 1, 1),
        D(2027, 12, 31),
        1,
    )
    assert svc.run_daily(D(2027, 1, 2))["renewed"] == 0  # повтор в тот же день ничего не меняет
    contract.refresh_from_db()
    assert contract.renewals_count == 1
    assert ActivityLog.objects.filter(event_code="contract.term_renewed", entity_id=contract.pk).count() == 1


def test_declined_contract_is_not_renewed(pw):  # noqa: F811
    contract = signed(pw)
    _, error = svc.decline_renewal(contract.pk, "client", today=D(2026, 11, 1))
    assert error is None
    svc.run_daily(D(2027, 1, 2))
    contract.refresh_from_db()
    assert contract.valid_until == D(2026, 12, 31) and contract.renewals_count == 0
    assert svc.state_of(contract, D(2027, 1, 2)) == "expired"


def test_reminders_go_once_at_30_and_7_days_before_the_last_notice_day(pw):  # noqa: F811
    contract = signed(pw)  # последний день отказа 1.12
    pw.deal.assigned_to = pw.manager
    pw.deal.save()
    assert svc.run_daily(D(2026, 10, 30))["reminded"] == 0
    assert svc.run_daily(D(2026, 11, 1))["reminded"] == 1  # за 30 дней
    assert svc.run_daily(D(2026, 11, 1))["reminded"] == 0  # повтор — метка уже стоит
    assert svc.run_daily(D(2026, 11, 20))["reminded"] == 0
    assert svc.run_daily(D(2026, 11, 24))["reminded"] == 1  # за 7 дней
    assert svc.run_daily(D(2026, 12, 2))["reminded"] == 0  # последний день отказа прошёл
    assert ActivityLog.objects.filter(event_code="contract.term_reminder", entity_id=contract.pk).count() == 2
    from notifications.models import Notification

    assert Notification.objects.filter(user=pw.manager, event_code="contract.term_reminder").count() == 2


def test_late_job_sends_only_the_most_urgent_reminder(pw):  # noqa: F811
    signed(pw)
    assert svc.run_daily(D(2026, 11, 28))["reminded"] == 1
    assert svc.run_daily(D(2026, 11, 29))["reminded"] == 0


def test_foreign_reminder_goes_45_days_before_the_end(pw):  # noqa: F811
    pw.client.country = Country.objects.get_or_create(code="DE", defaults={"name": "Germany"})[0]
    pw.client.save()
    signed(pw)
    assert svc.run_daily(D(2026, 11, 15))["reminded"] == 0
    assert svc.run_daily(D(2026, 11, 16))["reminded"] == 1  # 31.12 − 45 = 16.11
    assert svc.run_daily(D(2026, 11, 16))["reminded"] == 0


def test_declined_contract_gets_no_reminders(pw):  # noqa: F811
    contract = signed(pw)
    svc.decline_renewal(contract.pk, "client", today=D(2026, 10, 1))
    assert svc.run_daily(D(2026, 11, 5))["reminded"] == 0


# ── отказ от продления ─────────────────────────────────────────────────────────────────────────────────────────────


def test_decline_is_allowed_until_the_last_notice_day_only(pw):  # noqa: F811
    contract = signed(pw)
    assert svc.decline_renewal(contract.pk, "client", today=D(2026, 12, 2)) == (None, "TERM_NOTICE_PASSED")
    contract, error = svc.decline_renewal(contract.pk, "client", today=D(2026, 12, 1))
    assert error is None and contract.renewal_declined_by == "client"
    assert svc.decline_renewal(contract.pk, "client", today=D(2026, 12, 1)) == (None, "TERM_ALREADY_DECLINED")


def test_company_side_decline_needs_the_contract_manage_permission(pw):  # noqa: F811
    contract = signed(pw, timezone_today())  # «сегодня» API — настоящий день: срок отказа ещё не вышел
    denied = api(pw.outsider).post(f"/api/v1/crm/contracts/{contract.id}/decline-renewal/", {}, format="json")
    assert denied.status_code in (403, 404)
    ok = api(pw.accountant).post(f"/api/v1/crm/contracts/{contract.id}/decline-renewal/", {}, format="json")
    assert ok.status_code == 200, ok.content
    contract.refresh_from_db()
    assert contract.renewal_declined_by == "company"


def test_manual_renewal_of_an_expired_contract_starts_a_new_term_today(pw):  # noqa: F811
    contract = signed(pw)
    svc.decline_renewal(contract.pk, "client", today=D(2026, 11, 1))
    renewed, error = svc.renew_by_agreement(contract.pk, pw.accountant, today=D(2027, 2, 10), agreement_number="DS-1")
    assert error is None
    assert (renewed.valid_from, renewed.valid_until) == (D(2027, 2, 10), D(2027, 12, 31))
    assert renewed.renewal_declined_at is None and renewed.renewals_count == 1


# ── после окончания срока ──────────────────────────────────────────────────────────────────────────────────────────


def test_expired_counterparty_is_blocked_for_a_new_quote_but_started_deals_are_not(pw):  # noqa: F811
    contract = signed(pw)
    Contract.objects.filter(pk=contract.pk).update(valid_until=D(2020, 1, 1), renewal_mode="none")
    assert svc.expired_state(pw.client)["number"] == contract.number
    from integration.tests import world as w

    _, _, _, error = draft_quote._run_draft_quote_gates(pw.deal.pk, pw.admin)  # у сделки уже есть КП
    assert error != svc.EXPIRED_CODE
    fresh = w.make_deal(pw.client)  # новая заявка того же контрагента
    _, _, _, error = draft_quote._run_draft_quote_gates(fresh.pk, pw.admin)
    assert error == svc.EXPIRED_CODE


def test_warn_mode_does_not_block(pw):  # noqa: F811
    contract = signed(pw)
    Contract.objects.filter(pk=contract.pk).update(valid_until=D(2020, 1, 1), renewal_mode="none")
    rules(pw, contract_expired_action="warn")
    assert svc.new_work_error(pw.client, pw.own) is None


def test_company_without_signed_terms_is_never_blocked(pw):  # noqa: F811
    contract_in(pw, S.SIGNED)  # подписан до ДС-1: срока нет
    assert svc.expired_state(pw.client) is None and svc.new_work_error(pw.client) is None


def test_active_contract_is_not_blocking(pw):  # noqa: F811
    signed(pw, timezone_today())
    assert svc.expired_state(pw.client) is None


def timezone_today():
    from django.utils import timezone

    return timezone.localdate()


# ── новая редакция шаблона ─────────────────────────────────────────────────────────────────────────────────────────


def _template(pw, edition, previous=None, status=TemplateApproval.APPROVED):  # noqa: F811
    return DocumentTemplate.objects.create(
        company=pw.own,
        name="Договор",
        kind=DocumentTemplateKind.objects.get(code="CONTRACT"),
        body_html="<p>1. Предмет договора: поставка.</p>{{doc.spec_table}}{{doc.totals}}{{doc.requisites_and_signatures}}",
        approval_status=status,
        edition=edition,
        previous_edition=previous,
        counterparty_kind="client",
        subject="supply",
        is_active=status == TemplateApproval.APPROVED,
    )


def test_contract_stays_on_the_old_edition_and_renews_until_the_client_signs_the_new_one(pw):  # noqa: F811
    old = _template(pw, 1)
    contract = signed(pw, template=old, template_edition=1)
    _template(pw, 2, previous=old)
    assert svc.newest_edition(old).edition == 2
    assert [c.pk for c, _ in svc.on_old_edition(pw.own, D(2026, 6, 1))] == [contract.pk]
    svc.run_daily(D(2027, 1, 2))
    contract.refresh_from_db()
    assert contract.template_edition == 1 and contract.valid_until == D(2027, 12, 31)  # продлился на старой


def test_draft_edition_is_not_offered(pw):  # noqa: F811
    old = _template(pw, 1)
    signed(pw, template=old, template_edition=1)
    _template(pw, 2, previous=old, status=TemplateApproval.DRAFT)
    assert svc.on_old_edition(pw.own, D(2026, 6, 1)) == []


# ── API карточки, настройки, шаблон, контрагент ─────────────────────────────────────────────────────────────────────


def test_project_card_carries_the_term_and_its_actions(pw):  # noqa: F811
    contract = signed(pw, timezone_today())
    card = api(pw.accountant).get(f"/api/v1/crm/projects/{pw.deal.pk}/").json()["contract"]
    term = card["term"]
    assert term["state"] == "renews" and term["valid_until"] == str(contract.valid_until), card
    assert term["last_notice_date"] == str(contract.last_notice_date) and "decline_renewal" in term["actions"]
    assert term["last_notice_date"] == "2026-12-01"


def test_company_settings_take_and_reject_term_values(pw):  # noqa: F811
    url = f"/api/v1/accounts/companies/{pw.own.id}/settings/"
    ok = api(pw.admin).patch(
        url,
        {"contract_term_rule": "twelve_months", "contract_notice_days": 14, "contract_expired_action": "warn"},
        format="json",
    )
    assert ok.status_code == 200, ok.content
    row = CompanySettings.objects.get(company=pw.own)
    assert (row.contract_term_rule, row.contract_notice_days, row.contract_expired_action) == (
        "twelve_months",
        14,
        "warn",
    )
    for bad in ({"contract_term_rule": "forever"}, {"contract_notice_days": 9999}, {"contract_auto_renew": "yes"}):
        assert api(pw.admin).patch(url, bad, format="json").status_code == 400
    # правило компании меняет срок следующего договора
    contract = signed(pw, D(2026, 3, 10))
    assert contract.valid_until == D(2027, 3, 9) and contract.notice_days == 14


def test_template_term_fields_are_editable_in_draft_and_locked_after_approval(pw, grant):  # noqa: F811
    grant(pw.director, "settings.edit")
    draft = _template(pw, 1, status=TemplateApproval.DRAFT)
    url = f"/api/v1/crm/document-templates/{draft.id}/"
    ok = api(pw.director).patch(url, {"term_rule": "twelve_months", "confidentiality_years": 3}, format="json")
    assert ok.status_code == 200, ok.content
    draft.refresh_from_db()
    assert (draft.term_rule, draft.confidentiality_years) == ("twelve_months", 3)
    assert api(pw.director).patch(url, {"term_rule": "forever"}, format="json").status_code == 400
    DocumentTemplate.objects.filter(pk=draft.pk).update(approval_status=TemplateApproval.APPROVED)
    locked = api(pw.director).patch(url, {"notice_days": 5}, format="json")
    assert locked.status_code == 400 and locked.json()["detail"] == "TEMPLATE_LOCKED"


def test_counterparty_card_shows_term_and_whether_new_work_is_blocked(pw):  # noqa: F811
    contract = signed(pw)
    live = svc.counterparty_term(pw.client, D(2026, 6, 1))
    assert (live["number"], live["state"], live["blocks_new_work"]) == (contract.number, "renews", False)
    Contract.objects.filter(pk=contract.pk).update(valid_until=D(2020, 1, 1), renewal_mode="none")
    gone = svc.counterparty_term(pw.client, D(2026, 6, 1))
    assert gone["state"] == "expired" and gone["blocks_new_work"] is True
    assert svc.counterparty_term(pw.own) is None


def test_send_new_edition_creates_a_second_contract_and_closes_the_old_one_when_signed(pw):  # noqa: F811
    old = _template(pw, 1)
    contract = signed(pw, template=old, template_edition=1)
    _template(pw, 2, previous=old)
    assert svc.send_new_edition(contract.pk, pw.outsider) == (None, "MEMBER_REQUIRED_FOR_ACTION")
    new, error = svc.send_new_edition(contract.pk, pw.accountant)
    assert error is None and new.supersedes_id == contract.pk and new.template_edition == 2
    assert new.number != contract.number
    assert svc.send_new_edition(contract.pk, pw.accountant) == (None, "TERM_NEW_EDITION_ALREADY_SENT")
    # контрагент подписал: новая редакция получает свой срок, старый договор заканчивается накануне
    Contract.objects.filter(pk=new.pk).update(status=contract.status)
    new.refresh_from_db()
    svc.apply_at_signing(new, signed_on=D(2026, 9, 1))
    contract.refresh_from_db()
    assert contract.valid_until == D(2026, 8, 31) and contract.renewal_mode == "none"
    assert [c.pk for c, _ in svc.on_old_edition(pw.own, D(2026, 9, 2))] == []
