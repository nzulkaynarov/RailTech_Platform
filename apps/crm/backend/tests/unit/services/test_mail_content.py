"""Тело письма ERP/EDS шифртекстом ключа пары (W18A-P1): формат общий для ERP, EDS и CRM."""

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import hmac as crypto_hmac

from app.services.mail_content import (
    ContentUnreadableError,
    MailContent,
    MailLink,
    content_key,
    open_content,
    seal,
)

# Тест-вектор формата `fernet-pair-v1`: тот же токен расшифровывают тесты ERP и EDS.
VECTOR_SECRET = "test-pair-secret-erp-crm"
VECTOR_TOKEN = (
    "gAAAAABq4eM8WhS2WIUSMWplzbr_UITssK3O1At4Ygmar1FG4W1-lZDUAIXhWsbPRFdrbcTSRM5FmFIkITYaVwH76wglyj"
    "XDzwB1w3Ygfrd_ZOwsmf6o1XEbCMobtTyVu-1UXnDuOv6p6l1bPk2YPTNf8pnLAeyIg8RQvF9kqBPYhUl01NvN6GyyU2dc"
    "qlManzgcyDP9vpMnMqrLppPr-GlBNJnIfOaY3G7qS8BJ3krVXIjcUCxwF2i97pqVQtvaIQUIQuXfq5TB4Kl-BXmbtsVZRqs"
    "FD7X1CXHjBwbVnOxoZH0TiujuQhA0CggQu9rKIckB6F0mrUvDkLycaOPgSfr0ZaU-qoVZIgk9RKtIAf94qgZCSXA-KdAgk5"
    "uJDkIt-_0ZpsU-Lm_4ImHieR0YrjvLdo9XDvTwrA=="
)


def reference_key(secret: str) -> bytes:
    """Эталон ключа формата `fernet-pair-v1` — независимой реализацией HMAC (`cryptography`),
    а не строкой в тесте: urlsafe_b64(HMAC-SHA256(секрет пары, "rt-mail/v1/content"))."""
    mac = crypto_hmac.HMAC(secret.encode("utf-8"), hashes.SHA256())
    mac.update(b"rt-mail/v1/content")
    return base64.urlsafe_b64encode(mac.finalize())


def test_cross_service_vector_opens() -> None:
    assert content_key(VECTOR_SECRET) == reference_key(VECTOR_SECRET)
    opened = open_content("fernet-pair-v1", VECTOR_TOKEN, ["other-secret", VECTOR_SECRET])
    assert opened.text.startswith("Здравствуйте! Ссылка: https://cabinet.example.com/auth/magic")
    assert opened.html == "<p>Здравствуйте!</p>"
    assert opened.links == (
        MailLink(
            "http://rustfs:9000/erp-temp/mail/x.pdf?X-Amz-Signature=00", "2026-10-29T09:15:00Z"
        ),
    )


def test_round_trip_and_rotation() -> None:
    content = MailContent("текст", None, ())
    token = seal("new-secret", content)
    assert open_content("fernet-pair-v1", token, ["old-secret", "new-secret"]) == content


@pytest.mark.parametrize(
    ("alg", "token", "secrets"),
    [
        ("fernet-pair-v1", VECTOR_TOKEN, ["wrong-secret"]),
        ("fernet-pair-v1", VECTOR_TOKEN, []),
        ("plain", VECTOR_TOKEN, [VECTOR_SECRET]),
        ("fernet-pair-v1", "не-токен", [VECTOR_SECRET]),
    ],
)
def test_unreadable_content_is_a_clear_error(alg: str, token: str, secrets: list[str]) -> None:
    with pytest.raises(ContentUnreadableError):
        open_content(alg, token, secrets)
