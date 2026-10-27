"""Параметр `/start` бота (D1-9): разбор и подписанная ссылка на запрос с сайта."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.start_link import (
    LEAD_LINK_TTL,
    issue_lead_link,
    link_key,
    parse_start_payload,
    verify_lead_link,
)

KEY = b"unit-start-link-key-0123456789"
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "kind", "deal_id"),
    [
        (None, "none", None),
        ("", "none", None),
        ("   ", "none", None),
        ("web", "web", None),
        ("deal_42", "deal", 42),
        ("deal_0", "deal", 0),
        ("deal_", "unknown", None),
        ("deal_4x", "unknown", None),
        ("deal_-5", "unknown", None),
        ("deal_1234567890123", "unknown", None),
        ("WEB", "unknown", None),
        ("quote_5", "unknown", None),
        ("invite_abc", "unknown", None),
        ("lead_1_2", "unknown", None),
        ("../../etc", "unknown", None),
    ],
)
def test_parse_start_payload(raw: str | None, kind: str, deal_id: int | None) -> None:
    link = parse_start_payload(raw)
    assert (link.kind, link.deal_id) == (kind, deal_id)


def test_issued_link_is_a_valid_telegram_start_parameter() -> None:
    link = issue_lead_link(KEY, 987654, NOW)
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", link)
    assert parse_start_payload(link).kind == "lead"


def test_issued_link_verifies_to_the_lead_id() -> None:
    link = issue_lead_link(KEY, 987654, NOW)
    assert verify_lead_link(KEY, link, NOW + timedelta(days=1)) == 987654


def test_link_expires_after_ttl() -> None:
    link = issue_lead_link(KEY, 7, NOW)
    assert verify_lead_link(KEY, link, NOW + LEAD_LINK_TTL - timedelta(minutes=1)) == 7
    assert verify_lead_link(KEY, link, NOW + LEAD_LINK_TTL + timedelta(minutes=1)) is None


def test_link_with_other_key_is_rejected() -> None:
    link = issue_lead_link(KEY, 7, NOW)
    assert verify_lead_link(b"another-key-another-key-another-key", link, NOW) is None


def test_tampered_lead_id_is_rejected() -> None:
    """Чужой запрос по подделанной ссылке не привязать: подпись покрывает id и срок."""
    link = issue_lead_link(KEY, 7, NOW)
    _, lead, expires, signature = link.split("_")
    forged = f"lead_{int(lead, 36) + 1:x}_{expires}_{signature}"
    assert verify_lead_link(KEY, forged, NOW) is None
    assert verify_lead_link(KEY, f"lead_{lead}_{expires}_{'0' * 16}", NOW) is None


def test_prolonged_expiry_is_rejected() -> None:
    link = issue_lead_link(KEY, 7, NOW)
    _, lead, _, signature = link.split("_")
    far = format(int((NOW + timedelta(days=3650)).timestamp()), "x")
    assert verify_lead_link(KEY, f"lead_{lead}_{far}_{signature}", NOW) is None


@pytest.mark.parametrize(
    "raw", ["", "lead_", "lead_a_b_c", "deal_5", "web", "lead_1_2_zzzzzzzzzzzzzzzz"]
)
def test_garbage_is_not_a_lead_link(raw: str) -> None:
    assert verify_lead_link(KEY, raw, NOW) is None


def test_link_key_is_a_separate_derived_key() -> None:
    secret = b"application-secret-0123456789abcdef"
    derived = link_key(secret)
    assert derived != secret
    assert len(derived) == 32
    assert link_key(secret) == derived, "детерминирован"
    assert link_key(b"another-application-secret-0123456789") != derived
    # Ссылка, подписанная самим секретом приложения (как токен другого назначения), не принимается.
    assert verify_lead_link(derived, issue_lead_link(secret, 7, NOW), NOW) is None
    assert verify_lead_link(derived, issue_lead_link(derived, 7, NOW), NOW) == 7
