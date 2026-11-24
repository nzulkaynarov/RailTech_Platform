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
