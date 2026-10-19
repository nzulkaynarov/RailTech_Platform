"""WP-8 (P2-7): Russian pluralization of ActivityLog detail strings.

The plural helper is pure (no DB). The submit-RFQ event test left with the buyer path (FIX-13):
the client submits requests in the portal, not in ERP.
"""

import pytest

from crm.services._plural import pluralize_ru

# ── P2-7: standard Slavic plural rule — one / few / many ──────────────────────────────────


def _positions(count):
    return pluralize_ru(count, "позиция", "позиции", "позиций")


def _sellers(count):
    # Dative case — «заявка адресована N продавцу/продавцам».
    return pluralize_ru(count, "продавцу", "продавцам", "продавцам")


@pytest.mark.parametrize(
    "count,expected",
    [
        (1, "позиция"),
        (2, "позиции"),
        (3, "позиции"),
        (4, "позиции"),
        (5, "позиций"),
        (0, "позиций"),
        (11, "позиций"),
        (12, "позиций"),
        (14, "позиций"),
        (21, "позиция"),
        (22, "позиции"),
        (25, "позиций"),
        (101, "позиция"),
        (111, "позиций"),
    ],
)
def test_pluralize_positions(count, expected):
    assert _positions(count) == expected


@pytest.mark.parametrize(
    "count,expected",
    [
        (1, "продавцу"),
        (2, "продавцам"),
        (5, "продавцам"),
        (11, "продавцам"),
        (21, "продавцу"),
    ],
)
def test_pluralize_sellers(count, expected):
    assert _sellers(count) == expected


def test_pluralize_negative_uses_absolute_value():
    # Defensive: a negative count must not fall through the modulo branches into `many`.
    assert _positions(-1) == "позиция"
    assert _positions(-2) == "позиции"
