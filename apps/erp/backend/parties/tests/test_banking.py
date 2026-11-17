"""Банковский счёт по международным стандартам (ADR-0029): IBAN, SWIFT/BIC, счёт Узбекистана, печать, перенос прода."""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps
from parties.banking import check, grouped, masked, print_rows, uses_iban
from parties.models import Company, CompanyBankAccount

from accounts.services.bank_accounts import bank_details_text, save_account, validate_account
from core.models import Bank, Country, Currency

pytestmark = pytest.mark.django_db

migration = importlib.import_module("parties.migrations.0029_bank_details_to_accounts")


@pytest.fixture
def world():
    for code, name in (("UZ", "Узбекистан"), ("DE", "Германия"), ("US", "США")):
        Country.objects.get_or_create(code=code, defaults={"name": name})
    for code, numeric in (("UZS", "860"), ("USD", "840"), ("EUR", "978")):
        Currency.objects.update_or_create(code=code, defaults={"name": code, "iso_numeric": numeric})
    return Company.objects.create(name="ООО Пример", inn="300100500")


def _values(**kw):
    values = {"bank_country": Country.objects.get(code=kw.pop("country", "UZ"))}
    values["currency"] = Currency.objects.get(code=kw.pop("currency", "UZS"))
    return {**values, **kw}


def test_uzbek_account_twenty_digits_with_currency_code(world):
    assert check(_values(account="20208000900001234567", mfo="00873")) == {}
    assert check(_values(account="2020800090000123456", mfo="00873")) == {"account": "uz_format"}
    assert check(_values(account="20208840900001234567", mfo="00873")) == {"account": "currency_mismatch"}
    assert check(_values(account="20208840900001234567", mfo="00873", currency="USD")) == {}
    assert check(_values(account="20208000900001234567", mfo="873")) == {"mfo": "uz_format"}


def test_iban_checked_by_registry_and_country(world):
    good = "DE89370400440532013000"
    assert uses_iban("DE") and not uses_iban("UZ") and not uses_iban("US")
    assert check(_values(country="DE", currency="EUR", account=good, swift="COBADEFFXXX")) == {}
    assert check(_values(country="DE", currency="EUR", account=good[:-1] + "1", swift="COBADEFFXXX")) == {
        "account": "iban_invalid"
    }
    assert check(_values(country="DE", currency="EUR", account=good, swift="NBFAUZ2X")) == {"swift": "country_mismatch"}
    assert check(_values(country="DE", currency="EUR", account=good)) == {"swift": "required"}


def test_other_country_account_and_swift_rules(world):
    assert check(_values(country="US", currency="USD", account="000123456789", swift="CHASUS33")) == {}
    assert check(_values(country="US", currency="USD", account="12-ab", swift="CHASUS33")) == {"account": "format"}
    errors = check(
        _values(
            country="US",
            currency="USD",
            account="000123456789",
            swift="CHASUS33",
            holder_name_latin="ООО Пример",
            intermediary_account="890-0360-968",
        )
    )
    assert errors == {"holder_name_latin": "latin_charset", "intermediary_swift": "required"}


def test_save_fills_codes_from_iban_and_directory(world):
    row, errors = save_account(
        world, {"bank_country": "DE", "currency": "EUR", "account": "de89 3704 0044 0532 0130 00"}
    )
    assert errors == {}
    assert (row.account, row.mfo, row.swift) == ("DE89370400440532013000", "37040044", "COBADEFF")
    assert row.bank_name
    Bank.objects.create(code="00873", name="АКБ Образец", swift="ABCDUZ22")
    row, errors = save_account(world, {"account": "20208000900001234567", "mfo": "00873", "currency": "UZS"})
    assert errors == {} and row.bank_country.code == "UZ"
    assert (row.bank_name, row.swift) == ("АКБ Образец", "ABCDUZ22")


def test_validate_account_returns_codes_payload(world):
    payload, errors = validate_account({"bank_country": "uz", "currency": "UZS", "account": "2020 8000 9000 0123 4567"})
    assert payload == {} and errors == {"mfo": "required"}
    payload, errors = validate_account(
        {"bank_country": "UZ", "currency": "UZS", "account": "2020 8000 9000 0123 4567", "mfo": "00873"}
    )
    assert errors == {}
    assert payload["bank_country"] == "UZ" and payload["currency"] == "UZS"
    assert payload["account"] == "20208000900001234567"


def test_print_rows_by_bank_country(world):
    uz, _ = save_account(world, {"account": "20208000900001234567", "mfo": "00873", "currency": "UZS"})
    uz.bank_name = "АКБ Образец"
    assert print_rows(uz, holder="ООО Пример", inn="300100500") == [
        ("Получатель", "ООО Пример"),
        ("ИНН", "300100500"),
        ("Расчётный счёт", "2020 8000 9000 0123 4567"),
        ("Банк", "АКБ Образец"),
        ("МФО", "00873"),
    ]
    de, _ = save_account(
        world,
        {
            "bank_country": "DE",
            "currency": "EUR",
            "account": "DE89370400440532013000",
            "holder_name_latin": "Primer LLC",
            "bank_name": "Commerzbank",
            "intermediary_swift": "IRVTUS3N",
            "intermediary_account": "8900360968",
        },
    )
    rows = dict(print_rows(de, holder="ООО Пример"))
    assert rows["Beneficiary"] == "Primer LLC"
    assert rows["IBAN"] == "DE89 3704 0044 0532 0130 00"
    assert rows["SWIFT/BIC"] == "COBADEFF"  # BIC8 из IBAN — то же, что BIC11 с XXX
    assert rows["Intermediary bank"] == "IRVTUS3N" and rows["Account with intermediary"] == "8900360968"
    assert bank_details_text(world, "EUR").startswith("IBAN: DE89 3704")
    assert masked(de.account) == "…3000" and grouped("20208000900001234567") == "2020 8000 9000 0123 4567"


def test_migration_moves_card_text_and_sets_country(world):
    legacy = CompanyBankAccount.objects.create(
        company=world, account="2020 8000 1111 2222 3333", mfo="00440", currency=Currency.objects.get(code="UZS")
    )
    Company.objects.filter(pk=world.pk).update(bank_account="20208000111122223333", mfo="00440")
    other = Company.objects.create(name="Другая", inn="300100501", bank_account="2020 8000 4444 5555 6666", mfo="00441")

    migration.forwards(apps, None)

    legacy.refresh_from_db()
    assert legacy.account == "20208000111122223333" and legacy.bank_country.code == "UZ"
    assert CompanyBankAccount.objects.filter(company=world).count() == 1  # тот же номер — без копии
    created = CompanyBankAccount.objects.get(company=other)
    assert (created.account, created.mfo, created.is_default) == ("20208000444455556666", "00441", True)
    other.refresh_from_db()
    assert (other.bank_account, other.mfo) == ("", "")

    migration.backwards(apps, None)

    other.refresh_from_db()
    assert other.bank_account == "20208000444455556666"
