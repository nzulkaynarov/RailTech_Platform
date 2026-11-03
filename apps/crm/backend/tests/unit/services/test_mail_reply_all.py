"""«Ответить всем» (W18A-P2-3): копия доходит до собранного письма и получателей конверта SMTP.

Проверяется то, что уходит в SMTP, а не строка журнала: расшифровка строки → `send` → письмо
транспорта (`build_message`) → список RCPT TO.
"""

from email.message import EmailMessage

import pytest

from app.integrations.smtp import SmtpConnection, SmtplibTransport, envelope_recipients
from app.models.email import EmailLog
from app.security.secrets_store import SecretCipher
from app.services import mail_outgoing

CIPHER = SecretCipher("k" * 64)
CONNECTION = SmtpConnection("smtp.test", 465, "ssl", "u", "p", "info@company.test", "Компания")


class CapturingTransport(SmtplibTransport):
    """Настоящая сборка письма, без сети: что дошло бы до `smtplib`."""

    def __init__(self) -> None:
        super().__init__()
        self.message: EmailMessage | None = None

    def _send(self, connection: SmtpConnection, message: EmailMessage) -> None:
        self.message = message


def _row(thread_headers: dict[str, str] | None) -> EmailLog:
    return EmailLog(
        to_email="buyer@example.test",
        subject="Re: Запрос",
        template="inbound_reply",
        lang="ru",
        status="queued",
        body_ciphertext=CIPHER.encrypt("Принято."),
        thread_headers=thread_headers,
    )


async def _sent(row: EmailLog) -> EmailMessage:
    transport = CapturingTransport()
    outgoing = mail_outgoing.decode(row, CIPHER)
    await mail_outgoing.send(transport, CONNECTION, outgoing, ())
    assert transport.message is not None
    return transport.message


async def test_cc_reaches_header_and_envelope() -> None:
    message = await _sent(
        _row({"In-Reply-To": "<a@x.test>", "Cc": "boss@example.test, petrov@railtech.uz"})
    )

    assert message["To"] == "buyer@example.test"
    assert message["Cc"] == "boss@example.test, petrov@railtech.uz"
    assert message["In-Reply-To"] == "<a@x.test>"
    assert envelope_recipients(message) == [
        "buyer@example.test",
        "boss@example.test",
        "petrov@railtech.uz",
    ]


async def test_plain_reply_has_no_copy() -> None:
    message = await _sent(_row({"In-Reply-To": "<a@x.test>"}))
    assert message["Cc"] is None
    assert envelope_recipients(message) == ["buyer@example.test"]


@pytest.mark.parametrize(
    "raw",
    ["", "не адрес", "a@x.test\r\nBcc: spy@evil.test", "<a@x.test>, b@x.test;c@x.test"],
)
async def test_copy_drops_anything_that_is_not_an_address(raw: str) -> None:
    message = await _sent(_row({"Cc": raw}))
    assert "spy@evil.test" not in str(envelope_recipients(message))
    assert message["Bcc"] is None
