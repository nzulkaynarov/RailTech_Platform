"""Строка здоровья приёма почты (W18A-P2): итог опроса ящика словами."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.external_mail_inbound import InboundFacts, mail_inbound

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("facts", "status", "cause"),
    [
        (InboundFacts(configured=False), "off", "not_configured"),
        (
            InboundFacts(True, NOW, None, "auth_failed", "LOGIN rejected"),
            "fail",
            "imap_auth_failed",
        ),
        (
            InboundFacts(True, NOW - timedelta(minutes=30), NOW - timedelta(minutes=30)),
            "warn",
            "queue_stuck",
        ),
        (InboundFacts(True, NOW, NOW, waiting=3), "ok", None),
    ],
)
def test_mail_inbound_row(facts: InboundFacts, status: str, cause: str | None) -> None:
    result = mail_inbound(facts, NOW)
    assert (result.status, result.cause) == (status, cause)
    if status == "fail":
        assert result.hint is not None
        assert "пароль приложения" in result.hint
