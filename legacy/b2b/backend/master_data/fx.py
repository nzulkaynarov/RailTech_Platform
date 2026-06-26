"""FX rates — Central Bank of Uzbekistan (free, no key, UZS-base) + conversion helpers.

CBU JSON returns one row per ISO currency: {"Ccy": "USD", "Rate": "12013.52", "Date": "26.06.2026", ...}
where Rate = сум за 1 единицу валюты. UZS is the platform base (rate = 1).
"""

import datetime
import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

CBU_URL = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/"
# Currencies the business actually transacts in (UZS is the base = 1, not stored).
TRACKED_CURRENCIES = {"USD", "EUR", "RUB"}


def fetch_cbu_rates(timeout: int = 15) -> int:
    """Pull the latest CBU rates and upsert ExchangeRate rows. Returns the count upserted."""
    import httpx

    from .models import Currency, ExchangeRate

    response = httpx.get(CBU_URL, timeout=timeout)
    response.raise_for_status()
    upserted = 0
    for row in response.json():
        code = (row.get("Ccy") or "").upper()
        if code not in TRACKED_CURRENCIES:
            continue
        try:
            rate = Decimal(str(row.get("Rate")))
        except (InvalidOperation, TypeError):
            logger.warning("FX: bad rate for %s: %r", code, row.get("Rate"))
            continue
        try:
            rate_date = datetime.datetime.strptime(row.get("Date"), "%d.%m.%Y").date()
        except (ValueError, TypeError):
            rate_date = datetime.date.today()
        currency = Currency.objects.filter(code=code).first()
        if not currency:
            continue
        ExchangeRate.objects.update_or_create(
            currency=currency, rate_date=rate_date, defaults={"rate_to_uzs": rate, "source": "CBU"}
        )
        upserted += 1
    return upserted


def get_rate_to_uzs(currency_code: str, on_date=None):
    """Latest known UZS rate for a currency at/<=on_date (UZS=1). Returns Decimal or None."""
    from .models import ExchangeRate

    code = (currency_code or "").upper()
    if code in ("UZS", ""):
        return Decimal("1")
    queryset = ExchangeRate.objects.filter(currency__code=code)
    if on_date:
        queryset = queryset.filter(rate_date__lte=on_date)
    rate = queryset.order_by("-rate_date").first()
    return rate.rate_to_uzs if rate else None


def convert_to_uzs(amount, currency_code: str, rate=None):
    """Convert `amount` (in `currency_code`) to UZS. `rate` (a manual override) wins over lookup.

    Returns Decimal, or None if the currency is unknown and no rate was given.
    """
    amount = Decimal(str(amount))
    if rate is None:
        rate = get_rate_to_uzs(currency_code)
    if rate is None:
        return None
    return amount * Decimal(str(rate))
