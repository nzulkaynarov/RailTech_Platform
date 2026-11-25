"""УВ-2: уведомления «действие за вами» лежат во вкладке «Решения»."""

import pytest

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
