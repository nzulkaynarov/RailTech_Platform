"""One phone normaliser in CRM: the bus snapshot, the client card and the web intake agree."""

import pytest

from app.bus.snapshots import clean_phone
from app.domain.contacts import contact_phone
from app.domain.errors import ValidationFailedError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("90 123 45 67", "+998901234567"),
        ("+998 (90) 123-45-67", "+998901234567"),
        ("+998901234567", "+998901234567"),
        ("+7 495 123-45-67", "+74951234567"),
    ],
)
def test_snapshot_and_card_give_the_same_e164(raw: str, expected: str) -> None:
    assert clean_phone(raw) == expected
    assert contact_phone(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "8 90 123 45 67", "+998 90 123"])
def test_unparseable_phone_is_none_in_the_snapshot_and_an_error_on_the_card(raw: str) -> None:
    assert clean_phone(raw) is None
    with pytest.raises(ValidationFailedError):
        contact_phone(raw)
