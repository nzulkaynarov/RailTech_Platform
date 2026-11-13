"""Банковские счета компании (решение владельца 2026-11-11; `docs/research/2026-11-11-documents-templates/README.md` §1).

Один основной счёт на валюту (ограничение в базе): назначение основного снимает флаг с прежнего в той же транзакции.
Печать и проверка выпуска счёта берут основной счёт валюты документа, а без него — основной в сумах; у компании без
списка счетов (контрагенты) — прежние поля карточки «Расчётный счёт» и «МФО».
"""

from typing import Any, Optional, Tuple

from django.db import IntegrityError, transaction
from parties.models import Company, CompanyBankAccount

from core.currency import BASE_CURRENCY
from core.models import Currency

DEFAULT_CURRENCY = BASE_CURRENCY
_TEXT_FIELDS = ("bank_name", "mfo", "account", "swift", "correspondent_bank")
_LIMITS = {"bank_name": 255, "mfo": 10, "account": 50, "swift": 11, "correspondent_bank": 2000}


def default_account(company: Optional[Company], currency_code: Optional[str] = None) -> Optional[CompanyBankAccount]:
    """Основной действующий счёт валюты; нет — основной в сумах; нет и его — `None`."""
    if company is None or company.pk is None:
        return None
    active = CompanyBankAccount.objects.filter(company=company, is_active=True).select_related("currency")
    for code in dict.fromkeys([currency_code or DEFAULT_CURRENCY, DEFAULT_CURRENCY]):
        found = active.filter(currency__code=code, is_default=True).first()
        if found is not None:
            return found
    return None


def bank_details_text(company: Optional[Company], currency_code: Optional[str] = None) -> str:
    """Реквизиты для печати строкой; пусто — платить не по чему."""
    account = default_account(company, currency_code)
    if account is not None:
        return account.as_text()
    if company is None:
        return ""
    if company.pk is not None and company.bank_accounts.exists():
        return ""  # список счетов есть, но нет основного нужной валюты — печатать не из чего
    parts = []
    if getattr(company, "bank_account", ""):
        parts.append(f"р/с: {company.bank_account}")
    if getattr(company, "mfo", ""):
        parts.append(f"МФО: {company.mfo}")
    return ", ".join(parts)


def _clean(data: dict[str, Any], *, partial: bool) -> Tuple[dict[str, Any], dict[str, str]]:
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name in _TEXT_FIELDS:
        if name in data:
            text = str(data.get(name) or "").strip()
            if len(text) > _LIMITS[name]:
                errors[name] = "too_long"
            values[name] = text
    if "currency" in data:
        currency = Currency.objects.filter(code=str(data.get("currency") or "")).first()
        if currency is None:
            errors["currency"] = "unknown"
        else:
            values["currency"] = currency
    for flag in ("is_default", "is_active"):
        if flag in data:
            values[flag] = bool(data[flag])
    if "order" in data:
        try:
            values["order"] = max(0, int(data["order"]))
        except (TypeError, ValueError):
            errors["order"] = "invalid"
    if not partial:
        if not values.get("account"):
            errors["account"] = "required"
        if "currency" not in values and "currency" not in errors:
            errors["currency"] = "required"
    elif "account" in values and not values["account"]:
        errors["account"] = "required"
    return values, errors


@transaction.atomic
def save_account(
    company: Company, data: dict[str, Any], account: Optional[CompanyBankAccount] = None
) -> Tuple[Optional[CompanyBankAccount], dict[str, str]]:
    """Создать или изменить счёт. Ошибки — `{поле: причина}`; основной для валюты — единственный."""
    values, errors = _clean(data, partial=account is not None)
    if errors:
        return None, errors
    row = account or CompanyBankAccount(company=company)
    for name, value in values.items():
        setattr(row, name, value)
    if (
        account is None
        and not CompanyBankAccount.objects.filter(company=company, currency=row.currency, is_default=True).exists()
    ):
        row.is_default = True  # первый счёт валюты — основной
    if row.is_default:
        if not row.is_active:
            return None, {"is_default": "inactive"}
        CompanyBankAccount.objects.filter(company=company, currency=row.currency, is_default=True).exclude(
            pk=row.pk
        ).update(is_default=False)
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError:
        return None, {"account": "taken"}
    return row, {}
