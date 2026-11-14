"""Supplier lead time typed as words («30 дн.», «2–3 недели», «45 kun») → whole days (plan 0.6, FR-15).

Price lists and the manual price form carry the term as text; calculation and orders read the numeric
`SupplierOffer.order_lead_time_days`. The text stays as typed; the days are derived from it so the term is not lost.
A text the rule cannot read (a calendar date, «по запросу») gives None and leaves the numeric fields alone.
"""

import math
import re
from typing import Optional

MAX_DAYS = 3650

_DATE = re.compile(r"\d{1,2}[./]\d{1,2}([./]\d{2,4})?")
_RANGE = re.compile(r"(\d+)\s*(?:-|–|—|до|to|gacha)\s*(\d+)")
_NUMBER = re.compile(r"\d+")
_WEEKS = re.compile(r"нед|week|hafta|wk")
_MONTHS = re.compile(r"мес|month|\boy")
_WORKING = re.compile(r"раб|working|business|ish\s*kun")


def lead_days_from_text(text: Optional[str]) -> Optional[int]:
    """Days for a lead time in words: the upper bound of a range, weeks ×7, months ×30, working days ×7/5."""
    value = (text or "").strip().lower()
    if not value or _DATE.search(value):
        return None
    found = _RANGE.search(value)
    if found:
        amount = max(int(found.group(1)), int(found.group(2)))
    else:
        first = _NUMBER.search(value)
        if first is None:
            return None
        amount = int(first.group(0))
    if _WEEKS.search(value):
        days = amount * 7
    elif _MONTHS.search(value):
        days = amount * 30
    elif _WORKING.search(value):
        days = math.ceil(amount * 7 / 5)
    else:
        days = amount
    if days <= 0 or days > MAX_DAYS:
        return None
    return days
