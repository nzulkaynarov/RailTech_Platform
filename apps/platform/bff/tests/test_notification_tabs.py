"""УВ-2: уведомления «действие за вами» лежат во вкладке «Решения»."""

import pytest

from app.feeds.notification_text import localized_title
from app.feeds.notifications import tab_of


@pytest.mark.parametrize(
    "code",
    [
        "contract.email_failed",
        "invoice.email_failed",
        "act.email_failed",
        "invitation.email_failed",
        "supplier_order.email_failed",
        "contract.signed_client",
    ],
)
def test_actionable_mail_and_contract_events_are_decisions(code: str) -> None:
    assert tab_of(code) == "decisions"


def test_informational_document_events_stay_with_clients() -> None:
    assert tab_of("invoice.issued") == "clients"
    assert tab_of("integration.pairing_code_issued") == "system"


@pytest.mark.parametrize("language", ["en", "uz"])
@pytest.mark.parametrize(
    "code",
    [
        "contract.email_failed",
        "invoice.email_failed",
        "act.email_failed",
        "invitation.email_failed",
        "supplier_order.email_failed",
    ],
)
def test_mail_failure_titles_are_translated_and_keep_the_number(code: str, language: str) -> None:
    title = localized_title(code, {"number": "N-7", "to": "a@b.c", "reason": "x"}, language)
    assert title is not None
    assert "N-7" in title
    assert localized_title(code, {"number": "N-7"}, "ru") is None
