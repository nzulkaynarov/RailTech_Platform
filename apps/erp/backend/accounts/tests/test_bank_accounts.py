"""Банковские счета компании (решение владельца 2026-11-11): список, основной на валюту, печать и бланк EDS."""

import pytest
from parties.models import CompanyBankAccount
from rest_framework.test import APIClient
from rt_bus.django.models import Outbox

from accounts.models import Company
from accounts.services.bank_accounts import bank_details_text, default_account, save_account
from accounts.services.letterhead_event import LETTERHEAD_UPDATED
from accounts.testing import make_own_company
from accounts.tests.test_document_profile import _member, _owner
from core.models import Currency


@pytest.fixture
def own(db):
    company = Company.objects.create(name="РемПуть", inn="305123456")
    make_own_company(company)
    for code in ("UZS", "USD"):
        Currency.objects.get_or_create(code=code, defaults={"name": code})
    return company, _owner(company, "head@own.test")


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _url(company, tail=""):
    return f"/api/v1/accounts/companies/{company.id}/bank-accounts/{tail}"


@pytest.mark.django_db
def test_first_account_of_a_currency_is_default_and_switching_default_keeps_one(own):
    company, _ = own
    first, errors = save_account(company, {"account": "20208000900001234567", "mfo": "00873", "currency": "UZS"})
    assert errors == {} and first.is_default
    second, _ = save_account(company, {"account": "20208000900007654321", "currency": "UZS", "is_default": True})
    first.refresh_from_db()
    assert second.is_default and not first.is_default
    usd, _ = save_account(company, {"account": "20208840900001111111", "currency": "USD", "swift": "NBFAUZ2X"})
    assert usd.is_default  # первый в долларах — основной для долларов
    assert default_account(company, "USD") == usd
    assert default_account(company, "EUR") == second  # нет счёта в валюте — основной в сумах
    assert bank_details_text(company, "USD") == "р/с: 20208840900001111111, SWIFT: NBFAUZ2X"


@pytest.mark.django_db
def test_validation_errors_name_fields(own):
    company, _ = own
    _, errors = save_account(company, {"currency": "XXX"})
    assert errors == {"account": "required", "currency": "unknown"}
    save_account(company, {"account": "1", "currency": "UZS"})
    _, errors = save_account(company, {"account": "1", "currency": "UZS"})
    assert errors == {"account": "taken"}


@pytest.mark.django_db
def test_api_crud_for_settings_editor_only(own):
    company, head = own
    api = _client(head)
    created = api.post(
        _url(company), {"account": "20208000900001234567", "mfo": "00873", "currency": "UZS"}, format="json"
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert (body["currency"], body["is_default"]) == ("UZS", True)
    listed = api.get(_url(company))
    assert [row["account"] for row in listed.json()] == ["20208000900001234567"]
    patched = api.patch(_url(company, f"{body['id']}/"), {"bank_name": "Банк Демо"}, format="json")
    assert patched.status_code == 200 and patched.json()["bank_name"] == "Банк Демо"
    bad = api.post(_url(company), {"currency": "UZS"}, format="json")
    assert bad.status_code == 400 and bad.json() == {"account": ["required"]}
    plain = _client(_member(company, "member@own.test"))
    assert plain.get(_url(company)).status_code == 403
    assert api.delete(_url(company, f"{body['id']}/")).status_code == 204
    assert not CompanyBankAccount.objects.filter(company=company).exists()


@pytest.mark.django_db
def test_default_account_reaches_documents_and_the_eds_letterhead(own):
    company, _ = own
    before = Outbox.objects.filter(type=LETTERHEAD_UPDATED).count()
    save_account(company, {"account": "20208000900001234567", "mfo": "00873", "currency": "UZS"})
    envelopes = list(Outbox.objects.filter(type=LETTERHEAD_UPDATED).order_by("created_at", "id"))
    assert len(envelopes) == before + 1
    assert envelopes[-1].envelope["data"]["letterhead"]["bank_details"] == "р/с: 20208000900001234567, МФО: 00873"


@pytest.mark.django_db
def test_company_without_accounts_list_keeps_card_fields(db):
    client_company = Company.objects.create(name="Клиент", bank_account="20208000000000000001", mfo="00440")
    assert bank_details_text(client_company) == "р/с: 20208000000000000001, МФО: 00440"
