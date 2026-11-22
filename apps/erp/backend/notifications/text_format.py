"""One text rule for e-mails and bell messages (СЦ-7): money, dates, quantities, channels as screens show them.

Mails show money like screens («1 500 000,00 UZS»: thousands separator, currency code); PDFs keep accounting
style through the same `money` filter. Dates are ДД.ММ.ГГГГ, never ISO. No business logic here.
"""

from datetime import date, datetime
from typing import Any, Iterable, Optional

from core.currency import BASE_CURRENCY

CHANNEL_LABELS_RU = {"cabinet": "в Кабинет", "email": "на почту", "telegram": "в Telegram"}


def text_money(amount: Any, currency: Optional[str] = None) -> str:
    """`1500000` → `«1 500 000,00 UZS»`; empty → empty (the template hides the line)."""
    from crm.templatetags.document_format import money

    if amount is None or amount == "":
        return ""
    return money(amount, currency or BASE_CURRENCY)


def text_date(value: Any) -> str:
    """date / datetime / ISO string → ДД.ММ.ГГГГ; empty → empty."""
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return str(value)


def text_qty(value: Any, unit: Optional[str] = None) -> str:
    """`20000` → `«20 000»`; with unit `«20 000 шт.»`."""
    from crm.templatetags.document_format import qty

    return qty(value, unit)


def channel_words(codes: Iterable[str]) -> str:
    """`["cabinet", "email"]` → `«в Кабинет, на почту»`; an unknown code is printed as is."""
    return ", ".join(CHANNEL_LABELS_RU.get(code, code) for code in codes)


def deal_ref(deal: Any) -> str:
    """Human deal reference for texts: the deal number («ЗВ-2026-0042»), never the database id."""
    return (getattr(deal, "number", "") or "").strip() or str(getattr(deal, "title", "") or "").strip() or "—"
