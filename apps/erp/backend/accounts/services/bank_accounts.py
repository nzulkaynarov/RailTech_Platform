"""Банковские счета компании (решение владельца 2026-11-11; `docs/research/2026-11-11-documents-templates/README.md` §1).

Один основной счёт на валюту (ограничение в базе): назначение основного снимает флаг с прежнего в той же транзакции.
Печать и проверка выпуска счёта берут основной счёт валюты документа, а без него — основной в сумах. Текстовых реквизитов
карточки компании нет (ADR-0028 п. 3): их перенос — миграция `parties/0029`; поля счёта и проверки — ADR-0029.
"""

from typing import Any, Optional, Tuple

from django.db import IntegrityError, transaction
from parties import banking
from parties.models import Company, CompanyBankAccount

from core.currency import BASE_CURRENCY
from core.models import Country, Currency

DEFAULT_CURRENCY = BASE_CURRENCY
_TEXT_FIELDS = (
    "holder_name",
    "holder_name_latin",
    "bank_name",
    "bank_address",
    "mfo",
    "account",
    "swift",
    "intermediary_swift",
    "intermediary_account",
    "correspondent_bank",
)
_LIMITS = {
    "holder_name": 255,
    "holder_name_latin": 140,
    "bank_name": 255,
    "bank_address": 255,
    "mfo": 15,
    "account": 50,
    "swift": 11,
    "intermediary_swift": 11,
    "intermediary_account": 50,
    "correspondent_bank": 2000,
}
# Коды и номера хранятся без пробелов и в верхнем регистре (ADR-0029): «DE89 3704…» и «de8937 04…» — один счёт.
_CODES = ("mfo", "account", "swift", "intermediary_swift", "intermediary_account")
_CHECKED = ("bank_country", "currency", "account", "mfo", "swift", "intermediary_swift", "intermediary_account")


def default_account(company: Optional[Company], currency_code: Optional[str] = None) -> Optional[CompanyBankAccount]:
    """Основной действующий счёт валюты; нет — основной в сумах; нет и его — `None`."""
    if company is None or company.pk is None:
        return None
    active = CompanyBankAccount.objects.filter(company=company, is_active=True).select_related(
        "currency", "bank_country"
    )
    for code in dict.fromkeys([currency_code or DEFAULT_CURRENCY, DEFAULT_CURRENCY]):
        found = active.filter(currency__code=code, is_default=True).first()
        if found is not None:
            return found
    return None


def bank_details_text(company: Optional[Company], currency_code: Optional[str] = None) -> str:
    """Реквизиты для печати строкой; пусто — платить не по чему."""
    account = default_account(company, currency_code)
    return account.as_text() if account is not None else ""


def _clean(data: dict[str, Any], *, partial: bool) -> Tuple[dict[str, Any], dict[str, str]]:
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name in _TEXT_FIELDS:
        if name in data:
            text = banking.compact(data.get(name)) if name in _CODES else str(data.get(name) or "").strip()
            if len(text) > _LIMITS[name]:
                errors[name] = "too_long"
            values[name] = text
    if "bank_country" in data:
        code = str(data.get("bank_country") or "").strip().upper()
        country = Country.objects.filter(code=code).first() if code else None
        if code and country is None:
            errors["bank_country"] = "unknown"
        else:
            values["bank_country"] = country
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
    if account is None and "bank_country" not in values:
        values["bank_country"] = Country.objects.filter(code=banking.UZ).first()  # прежние клиенты API — счёт в UZ
    merged = {name: getattr(row, name, None) for name in (*_TEXT_FIELDS, *_CHECKED) if name != "currency"}
    merged["currency"] = getattr(row, "currency", None) if row.currency_id else None
    merged.update(values)
    if any(name in values for name in _CHECKED):
        banking.fill_codes(merged)
        errors = banking.check(merged)
        if errors:
            return None, errors
    for name, value in merged.items():
        if name in values or (value and not getattr(row, name, None)):
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


# Поля счёта, которые клиент задаёт в кабинете (ADR-0029 п. 6): без флагов и порядка — это решает сотрудник.
PORTAL_FIELDS = (
    "bank_country",
    "currency",
    "holder_name",
    "holder_name_latin",
    "account",
    "mfo",
    "swift",
    "bank_name",
    "bank_address",
    "intermediary_swift",
    "intermediary_account",
)


def validate_account(data: dict[str, Any]) -> Tuple[dict[str, Any], dict[str, str]]:
    """Проверить новый счёт без сохранения: значения по кодам (`bank_country`, `currency` — коды) и ошибки `{поле: причина}`.

    Пустые код банка, SWIFT и название подставляются (из IBAN или справочника «Банки»), как при сохранении.
    """
    values, errors = _clean({k: data.get(k) for k in PORTAL_FIELDS if k in data}, partial=False)
    if errors:
        return {}, errors
    if values.get("bank_country") is None:
        values["bank_country"] = Country.objects.filter(code=banking.UZ).first()
    banking.fill_codes(values)
    errors = banking.check(values)
    if errors:
        return {}, errors
    payload = {k: v for k, v in values.items() if k in PORTAL_FIELDS and k not in ("bank_country", "currency")}
    payload["bank_country"] = getattr(values.get("bank_country"), "code", "") or ""
    payload["currency"] = values["currency"].code
    return payload, {}


def account_text(payload: dict[str, Any]) -> str:
    """Строка счёта для показа и журнала — та же, что в снимке выпущенного документа."""
    row = CompanyBankAccount(
        **{k: v for k, v in payload.items() if k not in ("bank_country", "currency")},
        bank_country=Country.objects.filter(code=payload.get("bank_country") or "").first(),
        currency=Currency.objects.filter(code=payload.get("currency") or "").first(),
    )
    return row.as_text()


def same_as_default(company: Company, payload: dict[str, Any]) -> bool:
    """Запрошен тот же счёт, что основной в его валюте: смены нет."""
    current = default_account(company, payload.get("currency"))
    if current is None or current.currency.code != payload.get("currency"):
        return False
    return all(
        (getattr(current, k) or "") == (payload.get(k) or "")
        for k in PORTAL_FIELDS
        if k not in ("bank_country", "currency")
    ) and (getattr(current.bank_country, "code", "") or "") == (payload.get("bank_country") or "")


def make_default(company: Company, payload: dict[str, Any]) -> Tuple[Optional[CompanyBankAccount], dict[str, str]]:
    """Подтверждённый счёт — основной в своей валюте: тот же номер у компании обновляется, иначе заводится новый."""
    existing = CompanyBankAccount.objects.filter(company=company, account=payload.get("account") or "").first()
    data = {**payload, "is_default": True, "is_active": True}
    return save_account(company, data, existing)


def set_uzs_account(company: Company, account: str, mfo: str = "", **extra: Any) -> dict[str, str]:
    """Основной счёт в сумах банка Узбекистана — для прежних полей «Расчётный счёт» и «МФО» (API карточки компании, мастер,
    служебные команды). Тот же номер обновляется, иначе заводится. Ошибки — `{поле: причина}`."""
    number = banking.compact(account)
    if not number:
        return {}
    payload = {"bank_country": banking.UZ, "currency": DEFAULT_CURRENCY, "account": number, "mfo": mfo, **extra}
    _row, errors = make_default(company, payload)
    return errors
