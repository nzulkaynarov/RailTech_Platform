"""Правила профиля сотрудника (W15-H6): телефон, пояс, подпись, фото, замещение."""

from datetime import UTC, date, datetime

import pytest

from app.domain.staff_profile import (
    AVATAR_MAX_BYTES,
    DeputyPeriod,
    ProfileValueError,
    avatar_key,
    checked_avatar,
    checked_deputy,
    checked_signature,
    checked_timezone,
    local_today,
    normalize_phone,
    sniff_image,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16
TODAY = date(2026, 10, 27)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+998 90 123-45-67", "+998901234567"),
        ("(99) 123 45 67", "991234567"),
        ("  ", None),
        ("", None),
    ],
)
def test_normalize_phone(raw: str, expected: str | None) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "12", "+" + "1" * 16, "12-ab-34567"])
def test_phone_invalid(raw: str) -> None:
    with pytest.raises(ProfileValueError) as exc:
        normalize_phone(raw)
    assert exc.value.reason == "phone_invalid"


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("Asia/Tashkent", True),
        ("UTC", True),
        ("Mars/Base", False),
        ("asia/tashkent", False),
        ("", False),
    ],
)
def test_timezone(name: str, ok: bool) -> None:
    if ok:
        assert checked_timezone(name) == name
    else:
        with pytest.raises(ProfileValueError):
            checked_timezone(name)


def test_signature_trims_clears_and_limits() -> None:
    assert checked_signature("  С уважением,\r\nАзиз ") == "С уважением,\nАзиз"
    assert checked_signature("   ") is None
    with pytest.raises(ProfileValueError):
        checked_signature("x" * 1001)
    with pytest.raises(ProfileValueError):
        checked_signature("a\x00b")


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (WEBP, "image/webp"),
        (b"<svg></svg>", None),
        (b"GIF89a", None),
    ],
)
def test_sniff_image(data: bytes, mime: str | None) -> None:
    assert sniff_image(data) == mime


def test_avatar_checks() -> None:
    assert checked_avatar(PNG, "image/png") == "image/png"
    assert checked_avatar(PNG, None) == "image/png"
    assert checked_avatar(JPEG, "image/jpeg; charset=x") == "image/jpeg"
    for data, claimed, reason in [
        (b"", "image/png", "avatar_empty"),
        (PNG + b"0" * AVATAR_MAX_BYTES, "image/png", "avatar_too_large"),
        (b"<svg onload=alert(1)>", "image/svg+xml", "avatar_unsupported_type"),
        (PNG, "image/jpeg", "avatar_type_mismatch"),
    ]:
        with pytest.raises(ProfileValueError) as exc:
            checked_avatar(data, claimed)
        assert exc.value.reason == reason


def test_avatar_key_layout() -> None:
    assert avatar_key(7, "abc", "image/webp") == "staff-avatars/7/abc.webp"


@pytest.mark.parametrize(
    ("deputy", "start", "end", "reason"),
    [
        (5, date(2026, 11, 1), date(2026, 11, 10), None),
        (5, TODAY, TODAY, None),
        (7, date(2026, 11, 1), date(2026, 11, 10), "deputy_is_self"),
        (5, date(2026, 11, 10), date(2026, 11, 1), "deputy_period_reversed"),
        (5, date(2026, 10, 1), date(2026, 10, 20), "deputy_period_past"),
        (5, date(2026, 11, 1), date(2028, 1, 1), "deputy_period_too_long"),
    ],
)
def test_checked_deputy(deputy: int, start: date, end: date, reason: str | None) -> None:
    if reason is None:
        assert checked_deputy(7, deputy, start, end, TODAY) == DeputyPeriod(deputy, start, end)
    else:
        with pytest.raises(ProfileValueError) as exc:
            checked_deputy(7, deputy, start, end, TODAY)
        assert exc.value.reason == reason


def test_deputy_active_includes_both_ends() -> None:
    period = DeputyPeriod(5, date(2026, 11, 1), date(2026, 11, 10))
    assert [period.active_on(date(2026, 11, d)) for d in (1, 5, 10)] == [True] * 3
    assert not period.active_on(date(2026, 10, 31))
    assert not period.active_on(date(2026, 11, 11))


def test_every_profile_reason_is_a_known_error_reason() -> None:
    """`ProfileValueError.reason` отдаётся в `details.reason`: каждое значение есть в `Reason`."""
    from app.domain.errors import Reason

    known = {r.value for r in Reason}
    produced = {
        "name_required", "phone_invalid", "timezone_unknown", "signature_invalid", "avatar_empty",
        "avatar_too_large", "avatar_unsupported_type", "avatar_type_mismatch",
        "deputy_is_self", "deputy_period_reversed", "deputy_period_past", "deputy_period_too_long",
    }  # fmt: skip
    assert produced <= known


@pytest.mark.parametrize(
    ("tz", "expected"),
    [
        ("Asia/Tashkent", date(2026, 11, 1)),  # UTC+5: уже следующие сутки
        ("UTC", date(2026, 10, 31)),
        ("Pacific/Honolulu", date(2026, 10, 31)),
        ("Nowhere/Nothing", date(2026, 11, 1)),  # битый пояс — как у компании
    ],
)
def test_local_today_uses_employee_calendar(tz: str, expected: date) -> None:
    assert local_today(tz, datetime(2026, 10, 31, 20, 0, tzinfo=UTC)) == expected


def test_timezone_list_is_read_once() -> None:
    from app.domain import staff_profile as module

    assert checked_timezone("Asia/Tashkent") == "Asia/Tashkent"
    assert module._known_zones() is module._known_zones()
