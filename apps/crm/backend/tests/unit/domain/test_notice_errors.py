"""Причины сбоя приглашения и подтверждения — словами для менеджера (D1-9)."""

import pytest

from app.domain.notice_errors import ERRORS, error_text

#: Коды ERP из `HandoffResponse.invite.error` / `InviteResponse.error` (erp-integration.yaml 0.8.0).
ERP_CODES = (
    "CONTACT_EMAIL_REQUIRED",
    "CONTACT_TELEGRAM_REQUIRED",
    "EMAIL_DELIVERY_FAILED",
    "INVALID_CHANNEL",
    "CONTACT_WITHOUT_COMPANY",
    "COMPANY_ARCHIVED",
    "CONTACT_ARCHIVED",
    "CONTACT_CHANNEL_REQUIRED",
    "COMPANY_LINKED_BY_INN",
    "CONTACT_NOT_FOUND",
)


@pytest.mark.parametrize("code", ERP_CODES)
def test_every_erp_code_has_words(code: str) -> None:
    text = error_text(code)
    assert text
    assert code not in text, "менеджер читает слова, а не код"


def test_no_error_no_text() -> None:
    assert error_text(None) is None
    assert error_text("") is None


def test_unknown_code_is_shown_not_hidden() -> None:
    text = error_text("SOMETHING_NEW")
    assert text is not None
    assert "SOMETHING_NEW" in text
    assert "не определена" in text


def test_phone_only_message_tells_what_to_do() -> None:
    assert "позвон" in ERRORS["CONTACT_CHANNEL_REQUIRED"].lower()
    assert "позвон" in ERRORS["no_channel"].lower()
