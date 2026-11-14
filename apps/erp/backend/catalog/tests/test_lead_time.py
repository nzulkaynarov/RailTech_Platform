"""Plan 0.6 (FR-15): a supplier lead time typed as words becomes whole days."""

import pytest

from catalog.lead_time import lead_days_from_text


@pytest.mark.parametrize(
    ("text", "days"),
    [
        ("30", 30),
        ("30 дн.", 30),
        ("Срок поставки: 45 дней", 45),
        ("20-30 дней", 30),
        ("20–30 дн.", 30),
        ("от 10 до 14 дней", 14),
        ("2 недели", 14),
        ("2-3 нед.", 21),
        ("1 месяц", 30),
        ("10 рабочих дней", 14),
        ("45 kun", 45),
        ("2 hafta", 14),
        ("3 weeks", 21),
        ("14 days", 14),
    ],
)
def test_lead_time_words_become_days(text, days):
    assert lead_days_from_text(text) == days


@pytest.mark.parametrize("text", [None, "", "по запросу", "в наличии", "до 15.12.2026", "0 дней", "99999 дней"])
def test_unreadable_lead_time_gives_none(text):
    assert lead_days_from_text(text) is None
