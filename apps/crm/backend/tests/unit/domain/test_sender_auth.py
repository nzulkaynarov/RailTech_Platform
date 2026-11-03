"""Подтверждение отправителя по Authentication-Results (MAIL-TYPES)."""

from collections.abc import Iterable

import pytest

from app.domain.sender_auth import (
    aligned,
    effective_trusted,
    is_trusted,
    provider_trusted,
    server_id,
)
from app.domain.sender_auth import verdict as _verdict

# Ящик на Яндекс 360: доверяем серверам Яндекса, выведенным из хоста IMAP.
YANDEX_BOX = effective_trusted("imap.yandex.ru", [])


def verdict(headers: list[str], sender: str, trusted: Iterable[str] = YANDEX_BOX) -> str:
    return _verdict(headers, sender, trusted)


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
            [
                "mx.yandex.ru; spf=pass smtp.mailfrom=bounce.soliq.example; "
                "dkim=pass header.d=soliq.example"
            ],
            "a@soliq.example",
            "verified",
        ),
        # SPF и DKIM прошли, но оба для чужого домена (From подделан)
        (
            ["mx.yandex.ru; spf=pass smtp.mailfrom=spam.example; dkim=pass header.d=spam.example"],
            "a@soliq.example",
            "unverified",
        ),
        # только SPF — мало
        (["mx.yandex.ru; spf=pass smtp.mailfrom=soliq.example"], "a@soliq.example", "unverified"),
        (
            ["mx.yandex.ru; dmarc=fail header.from=soliq.example; spf=pass; dkim=pass"],
            "a@soliq.example",
            "unverified",
        ),
        (["mx.yandex.ru; none"], "a@soliq.example", "unknown"),
        ([], "a@soliq.example", "unknown"),
        ([YANDEX_OK], "", "unknown"),
        # верхний заголовок — тот, что поставил наш MX; нижний (от отправителя) не считается
        (
            ["mx.yandex.ru; dmarc=fail header.from=soliq.example", YANDEX_OK],
            "a@soliq.example",
            "unverified",
        ),
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


OURS = "mx.yandex.ru"
FORGED = "attacker.example; dmarc=pass header.from=soliq.example"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        # чужой authserv-id сверху: верить нельзя
        ([FORGED], "unknown"),
        # нашего нет вовсе, есть поддельный ниже чужого
        ([FORGED, "other.example; dmarc=pass header.from=soliq.example"], "unknown"),
        # наш сверху, поддельный ниже — решает наш
        ([YANDEX_OK, FORGED], "verified"),
        (["mx.yandex.ru; dmarc=fail header.from=soliq.example", FORGED], "unverified"),
        # поддельный сверху, наш ниже: наш MX кладёт заголовок выше письма — верхний чужой
        ([FORGED, YANDEX_OK], "unknown"),
        # id без точки-границы не подходит: evil-yandex.ru — чужой домен
        (["evil-yandex.ru; dmarc=pass header.from=soliq.example"], "unknown"),
        # заголовок без id
        (["; dmarc=pass header.from=soliq.example"], "unknown"),
        # Яндекс: поддомен `mx…mail.yandex.net`
        (["mxback12g.mail.yandex.net; dmarc=pass header.from=soliq.example"], "verified"),
        # ящик на Яндексе: заголовок Google или Microsoft в письме не наш — его можно подделать
        (["mx.google.com; dmarc=pass header.from=soliq.example"], "unknown"),
        (["eur.protection.outlook.com; dmarc=pass header.from=soliq.example"], "unknown"),
    ],
)
def test_only_a_trusted_authserv_id_counts(headers: list[str], expected: str) -> None:
    assert verdict(headers, "a@soliq.example") == expected


def test_explicit_list_overrides_the_provider_derived_from_the_host() -> None:
    header = "mx.corp.example; dmarc=pass header.from=soliq.example"
    assert verdict([header], "a@soliq.example") == "unknown"
    own = effective_trusted("imap.yandex.ru", ["corp.example"])
    assert own == ("corp.example",)
    assert verdict([header], "a@soliq.example", own) == "verified"
    # заданный список перекрывает вывод: серверы Яндекса в нём не названы — им не верим
    assert verdict([YANDEX_OK], "a@soliq.example", own) == "unknown"


def test_unknown_imap_host_trusts_nobody() -> None:
    """Сервер компании не ставит Authentication-Results: подделка «от Google» не проходит."""
    ours = effective_trusted("mail.company.example", [])
    assert ours == ()
    forged = "mx.google.com; dmarc=pass header.from=soliq.example"
    assert verdict([forged], "a@soliq.example", ours) == "unknown"
    assert verdict([YANDEX_OK], "a@soliq.example", ours) == "unknown"


def test_yandex_box_trusts_the_real_mx_and_not_a_forged_google_header() -> None:
    real = "mxback12o.mail.yandex.net; dmarc=pass header.from=soliq.example"
    forged = "mx.google.com; dmarc=pass header.from=soliq.example"
    assert verdict([real], "a@soliq.example") == "verified"
    assert verdict([forged, real], "a@soliq.example") == "unknown"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("imap.yandex.ru", ("yandex.ru", "yandex.net")),
        ("IMAP.YANDEX.COM:993", ("yandex.ru", "yandex.net")),
        ("imap.gmail.com", ("google.com",)),
        ("outlook.office365.com", ("protection.outlook.com",)),
        ("imap.mail.ru", ("mail.ru",)),
        ("imap.zoho.com", ("zoho.com", "zoho.eu")),
        ("imaps://imap.yandex.ru", ("yandex.ru", "yandex.net")),
        ("evil-yandex.ru", ()),
        ("mail.company.example", ()),
        ("", ()),
    ],
)
def test_provider_is_derived_from_the_imap_host(host: str, expected: tuple[str, ...]) -> None:
    assert provider_trusted(host) == expected


def test_yandex_writes_smtp_mail_for_the_envelope_sender() -> None:
    header = (
        "mx.yandex.ru; spf=pass smtp.mail=bounce@soliq.example; dkim=pass header.d=soliq.example"
    )
    assert verdict([header], "a@soliq.example") == "verified"
    spoofed = (
        "mx.yandex.ru; spf=pass smtp.mail=bounce@spam.example; dkim=pass header.d=spam.example"
    )
    assert verdict([spoofed], "a@soliq.example") == "unverified"


def test_nested_comments_do_not_break_the_parse() -> None:
    header = (
        "mx.yandex.ru; spf=pass (mx.yandex.ru: domain of a@soliq.example (ok (really)) "
        "designates 1.2.3.4) "
        "smtp.mailfrom=a@soliq.example; dkim=pass (signature ok (rsa)) header.d=soliq.example; "
        "dmarc=pass (policy=none) header.from=soliq.example"
    )
    assert verdict([header], "a@soliq.example") == "verified"
    assert server_id("mx.yandex.ru (comment (nested)) 1; spf=pass") == "mx.yandex.ru"


@pytest.mark.parametrize(
    ("ident", "expected"),
    [
        ("mx.yandex.ru", True),
        ("yandex.ru", True),
        ("evilyandex.ru", False),
        ("yandex.ru.evil.example", False),
        ("", False),
    ],
)
def test_is_trusted(ident: str, expected: bool) -> None:
    assert is_trusted(ident, ["yandex.ru"]) is expected
