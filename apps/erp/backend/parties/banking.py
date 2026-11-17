"""Банковский счёт по международным стандартам (ADR-0029).

Номер счёта зависит от страны банка: страна из реестра IBAN — IBAN (ISO 13616), Узбекистан — 20 цифр с кодом валюты в
цифрах 6–8, иная страна — до 34 латинских букв и цифр. SWIFT/BIC — ISO 9362. IBAN и BIC проверяет `schwifty`; здесь —
правила Узбекистана, подстановка из IBAN и справочника «Банки», строки для печати.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from schwifty import BIC, IBAN
from schwifty.exceptions import SchwiftyException
from schwifty.registry import get_iban_spec

UZ = "UZ"
UZ_ACCOUNT = re.compile(r"\d{20}")
UZ_MFO = re.compile(r"\d{5}")
UZS_IN_ACCOUNT = "000"  # национальная валюта в номере счёта Узбекистана
OTHER_ACCOUNT = re.compile(r"[A-Z0-9]{1,34}")
# Набор символов SWIFT (MT, поле 59): латиница, цифры и / - ? : ( ) . , ' + пробел.
SWIFT_CHARS = re.compile(r"[A-Za-z0-9/\-?:().,'+ ]*")


def compact(value: Any) -> str:
    """Номер без пробелов, дефисов и точек, в верхнем регистре: так он хранится и сравнивается."""
    return re.sub(r"[\s\-.]", "", str(value or "")).upper()


def uses_iban(country_code: Optional[str]) -> bool:
    if not country_code:
        return False
    try:
        get_iban_spec(country_code.upper())
    except (KeyError, SchwiftyException):
        return False
    return True


def grouped(account: str) -> str:
    """Номер группами по 4 знака — для печати и экрана (IBAN по ISO 13616, счёт Узбекистана — так же)."""
    value = compact(account)
    return " ".join(value[i : i + 4] for i in range(0, len(value), 4))


def masked(account: str) -> str:
    """Номер для журнала и уведомлений: последние 4 знака."""
    value = compact(account)
    return f"…{value[-4:]}" if len(value) > 4 else value


def _currency_digits(currency) -> str:
    code = getattr(currency, "code", "")
    if code == "UZS":
        return UZS_IN_ACCOUNT
    return (getattr(currency, "iso_numeric", "") or "").strip()


def check(values: dict[str, Any]) -> dict[str, str]:
    """Ошибки счёта `{поле: причина}` по итоговым значениям (новые поверх сохранённых).

    `values`: `bank_country` (Country или None), `currency`, `account`, `mfo`, `swift`, `intermediary_swift`,
    `holder_name_latin`. Счёт без страны банка (старые записи) проверяется только на заполненность номера.
    """
    errors: dict[str, str] = {}
    country = getattr(values.get("bank_country"), "code", "") or ""
    account = values.get("account") or ""
    if country == UZ:
        if not UZ_ACCOUNT.fullmatch(account):
            errors["account"] = "uz_format"
        else:
            digits = _currency_digits(values.get("currency"))
            if digits and account[5:8] != digits:
                errors["account"] = "currency_mismatch"
        mfo = values.get("mfo") or ""
        if not UZ_MFO.fullmatch(mfo):
            errors["mfo"] = "uz_format" if mfo else "required"
    elif country and uses_iban(country):
        try:
            iban = IBAN(account)
        except SchwiftyException:
            errors["account"] = "iban_invalid"
        else:
            if iban.country_code != country:
                errors["account"] = "iban_country"
    elif country and not OTHER_ACCOUNT.fullmatch(account):
        errors["account"] = "format"
    for field in ("swift", "intermediary_swift"):
        code = values.get(field) or ""
        if not code:
            continue
        try:
            bic = BIC(code)
        except SchwiftyException:
            errors[field] = "invalid"
            continue
        if field == "swift" and country and bic.country_code != country:
            errors[field] = "country_mismatch"
    if country and country != UZ and not values.get("swift") and "swift" not in errors:
        errors["swift"] = "required"
    if not SWIFT_CHARS.fullmatch(values.get("holder_name_latin") or ""):
        errors["holder_name_latin"] = "latin_charset"
    if values.get("intermediary_account") and not values.get("intermediary_swift"):
        errors.setdefault("intermediary_swift", "required")
    return errors


def fill_codes(values: dict[str, Any]) -> None:
    """Подставить пустые код банка, SWIFT и название: из IBAN, а для Узбекистана — из справочника «Банки» по МФО."""
    country = getattr(values.get("bank_country"), "code", "") or ""
    account = values.get("account") or ""
    if country and uses_iban(country):
        try:
            iban = IBAN(account)
        except SchwiftyException:
            return
        if not values.get("mfo") and iban.bank_code:
            values["mfo"] = iban.bank_code[:15]
        bic = iban.bic
        if not values.get("swift") and bic is not None:
            values["swift"] = str(bic)
        if not values.get("bank_name") and iban.bank_name:
            values["bank_name"] = iban.bank_name[:255]
        return
    if country == UZ and values.get("mfo"):
        from core.models import Bank

        bank = Bank.objects.filter(code=values["mfo"], is_active=True).first()
        if bank is None:
            return
        if not values.get("bank_name"):
            values["bank_name"] = str(bank.name)[:255]
        if not values.get("swift") and bank.swift:
            values["swift"] = bank.swift


def print_rows(
    account, *, holder: str = "", inn: str = "", english: bool = False, with_party: bool = True
) -> list[tuple[str, str]]:
    """Строки «подпись — значение» блока реквизитов: Узбекистан — привычный блок, иначе — для SWIFT-перевода.

    `with_party=False` — без получателя и ИНН (бланк и стороны договора, где они уже напечатаны).
    """
    country = getattr(getattr(account, "bank_country", None), "code", "") or ""
    holder = (account.holder_name_latin if english or country not in ("", UZ) else "") or account.holder_name or holder
    bank = ", ".join(x for x in (account.bank_name, account.bank_address) if x)
    if country in ("", UZ) and not english:
        rows = [("Получатель", holder), ("ИНН", inn), ("Расчётный счёт", grouped(account.account))]
        rows += [("Банк", bank), ("МФО", account.mfo), ("SWIFT", account.swift)]
    else:
        number = "IBAN" if uses_iban(country) else "Account"
        rows = [("Beneficiary", holder), ("TIN", inn), (number, grouped(account.account))]
        rows += [("Beneficiary bank", bank), ("SWIFT/BIC", account.swift)]
        if country == UZ and account.mfo:
            rows.append(("Bank code (MFO)", account.mfo))
        elif account.mfo and not uses_iban(country):
            rows.append(("Bank code", account.mfo))
        rows += [("Intermediary bank", account.intermediary_swift)]
        rows += [("Account with intermediary", account.intermediary_account)]
    if not with_party:
        rows = rows[2:]
    return [(label, value) for label, value in rows if value]
