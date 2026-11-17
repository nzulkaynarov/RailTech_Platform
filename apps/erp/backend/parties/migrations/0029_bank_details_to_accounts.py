"""Реквизиты — только список счетов (ADR-0028 п. 3, ADR-0029).

1. Счетам без страны банка — Узбекистан (все счета прода в сумах; номер — 20 цифр); номер и коды — без пробелов.
2. Текстовые «Расчётный счёт» и «МФО» карточки компании → счёт в сумах, если такого номера у компании ещё нет (основной —
   если основного в сумах нет). Свободный текст «Банковские реквизиты» без номера не разбирается и остаётся в базе до
   удаления колонок. Текстовые поля, перенесённые в счёт, очищаются.

Откат возвращает текст из основного счёта в сумах; счета остаются.
"""

import re

from django.db import migrations


def _compact(value) -> str:
    return re.sub(r"[\s\-.]", "", str(value or "")).upper()


def forwards(apps, schema_editor):
    Company = apps.get_model("parties", "Company")
    Account = apps.get_model("parties", "CompanyBankAccount")
    Country = apps.get_model("core", "Country")
    Currency = apps.get_model("core", "Currency")
    uz = Country.objects.filter(code="UZ").first()
    for row in Account.objects.all():
        row.account = _compact(row.account)[:50]
        row.mfo = _compact(row.mfo)[:15]
        row.swift = _compact(row.swift)[:11]
        if row.bank_country_id is None and uz is not None:
            row.bank_country_id = uz.pk
        row.save(update_fields=["account", "mfo", "swift", "bank_country"])
    uzs = Currency.objects.filter(code="UZS").first()
    for company in Company.objects.exclude(bank_account="").iterator():
        number = _compact(company.bank_account)[:50]
        if number and uzs is not None:
            if not Account.objects.filter(company_id=company.pk, account=number).exists():
                has_default = Account.objects.filter(
                    company_id=company.pk, currency_id=uzs.pk, is_default=True
                ).exists()
                Account.objects.create(
                    company_id=company.pk,
                    account=number,
                    mfo=_compact(company.mfo)[:15],
                    currency_id=uzs.pk,
                    bank_country_id=uz.pk if uz is not None else None,
                    is_default=not has_default,
                )
        Company.objects.filter(pk=company.pk).update(bank_account="", mfo="")


def backwards(apps, schema_editor):
    Company = apps.get_model("parties", "Company")
    Account = apps.get_model("parties", "CompanyBankAccount")
    for row in Account.objects.filter(currency__code="UZS", is_default=True, is_active=True):
        Company.objects.filter(pk=row.company_id, bank_account="").update(bank_account=row.account, mfo=row.mfo[:10])


class Migration(migrations.Migration):
    dependencies = [("parties", "0028_bank_account_iso_fields"), ("core", "0011_telegram_bot_projection")]

    operations = [migrations.RunPython(forwards, backwards)]
