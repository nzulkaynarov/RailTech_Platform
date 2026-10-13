"""Контакты клиента (Q-011): телефон → E.164, почта, имя подсказки из Telegram."""

import pytest

from app.domain.contacts import contact_email, contact_phone, suggested_name
from app.domain.errors import Reason, ValidationFailedError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("+998 90 123-45-67", "+998901234567"),
        ("998901234567", "+998901234567"),
        ("(+7) 912.345.67.89", "+79123456789"),
    ],
)
def test_contact_phone_normalizes(raw: str | None, expected: str | None) -> None:
    assert contact_phone(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "+0123456789", "12345", "+99890123456789012"])
def test_contact_phone_rejects_garbage(raw: str) -> None:
    with pytest.raises(ValidationFailedError) as exc:
        contact_phone(raw)
    assert exc.value.details == {"reason": Reason.INVALID_PHONE, "field": "phone"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), (" ", None), (" Ivan@Example.UZ ", "ivan@example.uz")],
)
def test_contact_email_normalizes(raw: str | None, expected: str | None) -> None:
    assert contact_email(raw) == expected


@pytest.mark.parametrize("raw", ["ivan", "ivan@", "@example.uz", "ivan@example", "a b@c.uz"])
def test_contact_email_rejects(raw: str) -> None:
    with pytest.raises(ValidationFailedError) as exc:
        contact_email(raw)
    assert exc.value.details["field"] == "email"


@pytest.mark.parametrize(
    ("first", "username", "expected"),
    [
        ("  Алишер ", "ali", "Алишер"),
        (None, "ali", "@ali"),
        ("", None, "+998901234567"),
    ],
)
def test_suggested_name(first: str | None, username: str | None, expected: str) -> None:
    assert suggested_name(first, username, "+998901234567") == expected
