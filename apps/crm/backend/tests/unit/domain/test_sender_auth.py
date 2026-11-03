"""Подтверждение отправителя по Authentication-Results (MAIL-TYPES)."""

import pytest

from app.domain.sender_auth import aligned, verdict

YANDEX_OK = (
    "mx.yandex.net; spf=pass (mx.yandex.net: domain of soliq.example designates 1.2.3.4) "
    "smtp.mailfrom=soliq.example; dkim=pass header.i=@soliq.example; "
    "dmarc=pass header.from=soliq.example"
)


@pytest.mark.parametrize(
    ("headers", "sender", "expected"),
    [
        ([YANDEX_OK], "info@soliq.example", "verified"),
        # DMARC прошёл, но для чужого домена: подделанный From не подтверждается
        ([YANDEX_OK], "info@evil.example", "unverified"),
        # SPF и DKIM прошли, выровнены по поддомену
        (
            ["mx; spf=pass smtp.mailfrom=bounce.soliq.example; dkim=pass header.d=soliq.example"],
            "a@soliq.example",
            "verified",
        ),
        # SPF и DKIM прошли, но оба для чужого домена (From подделан)
        (
            ["mx; spf=pass smtp.mailfrom=spam.example; dkim=pass header.d=spam.example"],
            "a@soliq.example",
            "unverified",
        ),
        # только SPF — мало
        (["mx; spf=pass smtp.mailfrom=soliq.example"], "a@soliq.example", "unverified"),
        (
            ["mx; dmarc=fail header.from=soliq.example; spf=pass; dkim=pass"],
            "a@soliq.example",
            "unverified",
        ),
        (["mx; none"], "a@soliq.example", "unknown"),
        ([], "a@soliq.example", "unknown"),
        ([YANDEX_OK], "", "unknown"),
        # верхний заголовок — тот, что поставил наш MX; нижний (от отправителя) не считается
        (["mx; dmarc=fail header.from=soliq.example", YANDEX_OK], "a@soliq.example", "unverified"),
    ],
)
def test_verdict(headers: list[str], sender: str, expected: str) -> None:
    assert verdict(headers, sender) == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("soliq.uz", "soliq.uz", True),
        ("mail.soliq.uz", "soliq.uz", True),
        ("@Soliq.UZ", "x@soliq.uz", True),
        ("evil-soliq.uz", "soliq.uz", False),
        ("", "soliq.uz", False),
    ],
)
def test_aligned(a: str, b: str, expected: bool) -> None:
    assert aligned(a, b) is expected
