"""Delivery status notifications: real DSN samples (Yandex, Gmail, Mail.ru, delay, plain MTA)."""

from pathlib import Path

import pytest

from app.domain.bounce import parse_bounce

SAMPLES = Path(__file__).resolve().parents[2] / "fixtures" / "bounces"


def sample(name: str) -> bytes:
    return (SAMPLES / f"{name}.eml").read_bytes()


def test_yandex_domain_not_found() -> None:
    bounce = parse_bounce(sample("yandex_domain_not_found"))
    assert bounce is not None
    assert bounce.recipients == ("em@tvorog.io",)
    assert bounce.severity == "permanent"
    assert bounce.reason == "domain_not_found"
    assert bounce.status == "5.4.4"
    assert "Host or domain name not found" in bounce.diagnostic
    assert bounce.original_message_id == "20261124101500.1234.5678@railtech.example"


def test_gmail_mailbox_not_found_links_by_rfc822_headers() -> None:
    bounce = parse_bounce(sample("gmail_mailbox_not_found"))
    assert bounce is not None
    assert bounce.recipients == ("nobody.here@gmail.com",)
    assert (bounce.severity, bounce.reason, bounce.status) == (
        "permanent",
        "mailbox_not_found",
        "5.1.1",
    )
    assert bounce.original_message_id == "20261124110000.1.2@railtech.example"
    assert "20261124110000.1.2@railtech.example" in bounce.reply_ids


def test_mailru_user_not_found_status_without_detail() -> None:
    bounce = parse_bounce(sample("mailru_user_unknown"))
    assert bounce is not None
    assert bounce.recipients == ("ivanov@mail.ru",)
    assert bounce.severity == "permanent"
    assert bounce.reason == "mailbox_not_found"
    assert bounce.original_message_id == "20261124120000.9.9@railtech.example"


def test_delay_is_soft() -> None:
    bounce = parse_bounce(sample("delay_4xx"))
    assert bounce is not None
    assert (bounce.severity, bounce.status) == ("soft", "4.4.1")
    assert bounce.recipients == ("sales@partner.example",)
    assert bounce.original_message_id == "20261124125000.7.7@railtech.example"


def test_plain_mailer_daemon_without_dsn_part() -> None:
    bounce = parse_bounce(sample("exim_plain_no_dsn"))
    assert bounce is not None
    assert bounce.recipients == ("gone@old.example",)
    assert (bounce.severity, bounce.reason, bounce.status) == (
        "permanent",
        "mailbox_not_found",
        "5.1.1",
    )


@pytest.mark.parametrize("name", ["normal_letter", "out_of_office"])
def test_ordinary_letters_are_not_bounces(name: str) -> None:
    assert parse_bounce(sample(name)) is None


def test_unknown_charset_does_not_raise_for_any_letter() -> None:
    """`unknown-8bit` / `x-bogus` must not break recognition (it runs for every inbound letter)."""
    for charset in ("unknown-8bit", "x-bogus"):
        raw = (
            "From: Petrov <petrov@client.example>\r\nTo: crm@railtech.example\r\n"
            "Subject: q\r\nMessage-ID: <odd@client.example>\r\n"
            f"Content-Type: text/plain; charset={charset}\r\n"
            "Content-Transfer-Encoding: 8bit\r\n\r\nПривет\r\n"
        ).encode()
        assert parse_bounce(raw) is None


def test_unknown_charset_in_a_real_report_still_parses() -> None:
    raw = sample("exim_plain_no_dsn").replace(b"charset=utf-8", b"charset=unknown-8bit")
    bounce = parse_bounce(raw)
    assert bounce is not None
    assert bounce.recipients == ("gone@old.example",)


def test_huge_recipient_header_is_bounded_in_time() -> None:
    import time

    junk = "a" * 60_000
    raw = sample("yandex_domain_not_found").replace(
        b"Final-Recipient: rfc822; em@tvorog.io", f"Final-Recipient: rfc822; {junk}".encode()
    )
    started = time.monotonic()
    parse_bounce(raw)
    assert time.monotonic() - started < 1.0


def test_exim_text_message_id_links_and_is_not_a_report() -> None:
    raw = sample("exim_plain_no_dsn") + b"\nMessage-ID: <ours.42@railtech.example>\n"
    bounce = parse_bounce(raw)
    assert bounce is not None
    assert bounce.original_message_id == "ours.42@railtech.example"
    assert bounce.is_report is False
    assert parse_bounce(sample("gmail_mailbox_not_found")).is_report is True  # type: ignore[union-attr]
