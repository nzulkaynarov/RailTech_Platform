"""ДС-1: срок договора в портале — `term` в ответе и отказ клиента от продления (`POST /contracts/{id}/decline-renewal`).

Факт, из которого выводится ответ: строки договора (`valid_until`, `last_notice_date`, `renewal_declined_*`) и журнал.
Защиты, без которых тест краснеет: срок отказа в `decline_renewal`, право `can_act`, чужая компания → 404.
"""

import datetime as dt

import pytest
from portal.tests.contract_support import check_response, response_schema

from crm.models import ActivityLog
from crm.services import contract_term

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"


def term_of(contract, signed_on=dt.date(2026, 3, 10)):
    contract_term.apply_at_signing(contract, signed_on=signed_on)
    contract.refresh_from_db()
    return contract


def post(client, contract):
    return client.post(f"{API}/contracts/{contract.pk}/decline-renewal", {}, format="json")


def test_signed_contract_carries_its_term_and_the_schema_accepts_it(contract_world, portal_client):
    contract = term_of(contract_world["contracts"]["signed"], dt.date.today())
    listed = {row["id"]: row for row in portal_client.get(f"{API}/contracts").json()}
    term = listed[contract.pk]["term"]
    assert (term["state"], term["valid_until"]) == ("renews", str(contract.valid_until))
    assert term["last_notice_date"] == str(contract.last_notice_date) and term["can_decline"] is True
    assert term["declined_by"] is None
    assert not check_response(listed[contract.pk], response_schema("/contracts/{id}/sign", "post", "200"))
    # договор без срока (не подписан сторонами) — `term: null`
    assert listed[contract_world["contracts"]["sent"].pk]["term"] is None


def test_client_declines_the_renewal_once_and_the_contract_is_not_renewed(contract_world, portal_client):
    contract = term_of(contract_world["contracts"]["signed"], dt.date.today())  # срок отказа ещё не вышел
    response = post(portal_client, contract)
    assert response.status_code == 200, response.content
    assert response.json()["term"]["declined_by"] == "client" and response.json()["term"]["state"] == "ends"
    contract.refresh_from_db()
    assert contract.renewal_declined_by == "client" and contract.renewal_declined_at is not None
    assert ActivityLog.objects.filter(event_code="contract.renewal_declined", entity_id=contract.pk).exists()
    assert post(portal_client, contract).json() == {"detail": "TERM_ALREADY_DECLINED"}
    contract_term.run_daily(contract.valid_until + dt.timedelta(days=1))
    contract.refresh_from_db()
    assert contract.renewals_count == 0  # отказавшийся договор не продлевается


def test_decline_after_the_last_notice_day_is_409(contract_world, portal_client):
    contract = term_of(contract_world["contracts"]["signed"], dt.date(2020, 3, 10))  # срок давно вышел
    response = post(portal_client, contract)
    assert response.status_code == 409 and response.json() == {"detail": "TERM_NOTICE_PASSED"}
    contract.refresh_from_db()
    assert contract.renewal_declined_at is None


def test_contract_without_a_term_has_nothing_to_decline(contract_world, portal_client):
    response = post(portal_client, contract_world["contracts"]["signed"])  # подписан до ДС-1: срока нет
    assert response.status_code == 409 and response.json() == {"detail": "TERM_NOT_AVAILABLE"}


def test_other_company_cannot_decline(contract_world, other_portal_client):
    contract = term_of(contract_world["contracts"]["signed"])
    response = post(other_portal_client, contract)
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}


def test_read_only_contact_cannot_decline(contract_world, readonly_portal_client):
    contract = term_of(contract_world["contracts"]["signed"])
    response = post(readonly_portal_client, contract)
    assert response.status_code == 403


def test_renewal_notice_links_to_contracts_lists_every_number_and_has_email_text(contract_world, client_contact):
    from django.template.loader import render_to_string
    from django.utils import translation
    from portal.models import PortalNotice
    from portal.services import notice_sources
    from portal.services.notices import email_context

    first = contract_world["contracts"]["signed"]
    second = contract_world["contracts"]["sent"]
    notice_sources.contract_renewed([first, second], first.deal.company, until="2027-12-31")
    notice_sources.contract_renewed(
        [first, second], first.deal.company, until="2027-12-31"
    )  # повтор — без новой строки
    rows = PortalNotice.objects.filter(kind="contract_renewed", contact=client_contact)
    assert rows.count() == 1
    row = rows.get()
    assert row.link == "/contracts" and f"{first.pk}-{second.pk}" in row.dedup_key
    assert first.number in row.params["number"] and second.number in row.params["number"]
    ctx = email_context(row)
    for lang, title, body in (
        ("ru", "Договор продлён", "Новый срок — до 31.12.2027"),
        ("en", "Contract renewed", "until 31.12.2027"),
        ("uz", "Şartnoma uzaytirildi", "31.12.2027gaça"),
    ):
        with translation.override(lang):
            assert title in render_to_string("emails/_portal_notice_title.txt", ctx)
            text = render_to_string("emails/_portal_notice_body.txt", ctx)
        assert body in text and first.number in text and second.number in text


def test_declined_notice_links_to_contracts(contract_world, client_contact):
    from portal.models import PortalNotice
    from portal.services import notice_sources

    contract = term_of(contract_world["contracts"]["signed"], dt.date.today())
    notice_sources.contract_renewal_declined(contract)
    row = PortalNotice.objects.get(kind="contract_renewal_declined", contact=client_contact)
    assert row.link == "/contracts" and row.params["until"] == str(contract.valid_until)
