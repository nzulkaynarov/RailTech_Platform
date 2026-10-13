"""Presentation filters for the seller-issued document PDFs (КП / договор / инвойс / акт).

`django.contrib.humanize` is not in INSTALLED_APPS and `USE_THOUSAND_SEPARATOR` is unset, so
there is no built-in thousands grouping for these templates. These filters give the documents
international B2B money formatting without touching global L10N: a non-breaking thousands
separator, comma decimals, an explicit currency code, and «сумма прописью».

Rule 8: no business logic here — `money_words` delegates to crm.services.money_words. Load in a
template with `{% load document_format %}`.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template

from crm.services.money_words import money_in_words, money_in_words_en

register = template.Library()

NBSP = " "  # non-breaking space — keeps "20 608 000,00 UZS" from wrapping mid-number
_DASH = "—"


def _to_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


@register.filter
def money(value, currency=None):
    """`20608000` → `«20 608 000,00»`; `money:"UZS"` → `«20 608 000,00 UZS»`. None/unparseable → «—».

    NBSP thousands separator, comma decimal, 2 fixed places. Negative amounts keep their sign.
    """
    amount = _to_decimal(value)
    if amount is None:
        return _DASH
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    whole, frac = divmod(abs(amount), 1)
    integer_digits = f"{int(whole):,}".replace(",", NBSP)
    kopecks = f"{int((frac * 100).to_integral_value(rounding=ROUND_HALF_UP)):02d}"
    formatted = f"{sign}{integer_digits},{kopecks}"
    if currency:
        return f"{formatted}{NBSP}{currency}"
    return formatted


@register.filter
def money_words(value, currency_code="UZS"):
    """«Сумма прописью» на языке документа: `{{ total|money_words:"UZS" }}`.

    M1: документ печатается на языке ПОЛУЧАТЕЛЯ, и пропись обязана следовать за ним — иначе
    в английском акте посреди страницы стояла бы русская строка. Для языка без собственного
    конвертера печатаем русскую пропись: это денежный реквизит, машинный перевод здесь
    недопустим.
    """
    from django.utils import translation

    if (translation.get_language() or "").startswith("en"):
        return money_in_words_en(value, currency_code or "UZS")
    return money_in_words(value, currency_code or "UZS")


@register.filter
def qty(value, unit=None):
    """`{{ item.quantity|qty:item.unit }}` → `«10 шт.»` with a non-breaking space; bare number if
    no unit. Integers print without a trailing «.0»; fractional quantities keep their decimals."""
    amount = _to_decimal(value)
    if amount is None:
        number = _DASH
    elif amount == amount.to_integral_value():
        number = f"{int(amount)}"
    else:
        number = format(amount.normalize(), "f")
    if unit:
        return f"{number}{NBSP}{unit}"
    return number
