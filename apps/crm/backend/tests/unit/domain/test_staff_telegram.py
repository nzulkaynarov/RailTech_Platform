"""Одноразовый код привязки Telegram сотрудником (W15-H6)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import staff_telegram as tg

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)


def test_codes_are_random_and_fit_deep_link() -> None:
    codes = {tg.new_code() for _ in range(50)}
    assert len(codes) == 50
    for code in codes:
        assert tg.staff_code_of(tg.start_payload(code)) == code
        assert len(tg.start_payload(code)) <= 64  # предел Telegram для параметра start


def test_hash_is_stable_and_not_the_code() -> None:
    code = tg.new_code()
    assert tg.hash_code(code) == tg.hash_code(code)
    assert code not in tg.hash_code(code)
    assert tg.same_code(code, tg.hash_code(code))
    assert not tg.same_code(tg.new_code(), tg.hash_code(code))


@pytest.mark.parametrize(
    "args",
    [
        None,
        "",
        "ref_abc",
        "staff_",
        "staff_short",
        "staff_" + "a" * 17,
        "staff_" + "a b" * 5,
        "Staff_" + "a" * 16,
        "x" * 16,
    ],
)
def test_client_start_arguments_are_not_staff_codes(args: str | None) -> None:
    assert tg.staff_code_of(args) is None


def test_staff_code_extracted() -> None:
    code = tg.new_code()
    assert tg.staff_code_of(f"staff_{code}") == code


def test_expiry_boundary() -> None:
    expires = NOW + tg.CODE_TTL
    assert not tg.is_expired(expires, NOW)
    assert not tg.is_expired(expires, expires - timedelta(seconds=1))
    assert tg.is_expired(expires, expires)


def test_deep_link_and_username() -> None:
    assert tg.deep_link("@rt_bot", "c" * 16) == "https://t.me/rt_bot?start=staff_" + "c" * 16
    assert tg.clean_username(" @aziz ") == "aziz"
    assert tg.clean_username("") is None
    assert tg.clean_username(None) is None


def test_texts_fall_back_to_russian() -> None:
    assert tg.text(tg.LINKED, "uz") != tg.text(tg.LINKED, "ru")
    assert tg.text(tg.LINKED, "de") == tg.LINKED["ru"]
    assert tg.text(tg.INVALID, None) == tg.INVALID["ru"]


def test_freshly_self_linked_telegram_is_not_trusted_for_24_hours() -> None:
    assert tg.telegram_trusted(None, NOW)  # привязал админ или привязка старая
    assert not tg.telegram_trusted(NOW - timedelta(hours=23, minutes=59), NOW)
    assert tg.telegram_trusted(NOW - tg.TRUST_AFTER, NOW)
    assert tg.telegram_trusted(NOW - timedelta(days=3), NOW)


def test_bot_confirmation_tells_how_to_undo() -> None:
    assert "отвяжите" in tg.LINKED["ru"]
    assert "Telegramni uzing" in tg.LINKED["uz"]
    assert "unlink" in tg.LINKED["en"]
