"""Токен привязки Telegram контактом (NOTIFY-1): форма, подпись, срок — чистые функции без базы."""

import base64
import hashlib
import hmac
import struct
from datetime import UTC, datetime, timedelta

import pytest

from app.domain import contact_link
from app.domain.start_link import parse_start_payload

PAIR_SECRET = "pair" + "-secret-for-tests"  # из частей: gitleaks сканирует литералы
#: Тот же вектор выпускает ERP (`apps/erp/backend/portal/tests/test_portal_telegram_link.py`).
VECTOR = "tg_AQEAAAAAADpq6tt0AAECAwQFBgcIK3Hc6WPbHUmSl6UdUxw_"
EXPIRES = datetime(2026, 11, 4, 7, 15, tzinfo=UTC)
BEFORE = EXPIRES - timedelta(minutes=1)


def token(
    secret: str = PAIR_SECRET,
    *,
    contact: int = 58,
    language: int = 1,
    expires: datetime = EXPIRES,
    version: int = 1,
    nonce: bytes = bytes(range(9)),
) -> str:
    data = struct.pack(
        ">BB6sI9s", version, language, contact.to_bytes(6, "big"), int(expires.timestamp()), nonce
    )
    key = hmac.new(secret.encode(), b"rt-telegram-link/v1", hashlib.sha256).digest()
    mac = hmac.new(key, data, hashlib.sha256).digest()[:15]
    return "tg_" + base64.urlsafe_b64encode(data + mac).decode().rstrip("=")


def test_erp_vector_is_accepted_with_contact_language_expiry_and_nonce() -> None:
    assert token() == VECTOR
    link = contact_link.verify(VECTOR, [PAIR_SECRET], BEFORE)
    assert link == contact_link.ContactLink(58, "uz", EXPIRES, bytes(range(9)).hex())


def test_any_active_pair_secret_verifies_rotation_without_downtime() -> None:
    assert contact_link.verify(VECTOR, ["new" + "-secret", PAIR_SECRET], BEFORE) is not None


@pytest.mark.parametrize(
    "raw",
    [
        token(expires=BEFORE - timedelta(seconds=1)),  # просрочен
        token("other" + "-secret"),  # чужой секрет
        VECTOR[:-1] + ("A" if VECTOR[-1] != "A" else "B"),  # подпись подделана
        VECTOR[:5] + ("B" if VECTOR[5] != "B" else "C") + VECTOR[6:],  # данные подделаны
        token(version=2),  # неизвестная версия
        token(contact=0),
        VECTOR + "x",  # длиннее
        VECTOR.replace("tg_", "tl_"),
        "tg_" + "!" * 48,
        "",
        "lead_1_2_0123456789abcdef",
    ],
)
def test_unfit_tokens_are_refused_without_a_reason(raw: str) -> None:
    assert contact_link.verify(raw, [PAIR_SECRET], BEFORE) is None


def test_without_a_pair_secret_nothing_verifies() -> None:
    assert contact_link.verify(VECTOR, [], BEFORE) is None


def test_start_payload_recognises_the_contact_link_and_keeps_older_links() -> None:
    assert parse_start_payload(VECTOR).kind == "contact"
    assert parse_start_payload(VECTOR).raw == VECTOR
    assert parse_start_payload("web").kind == "web"
    assert parse_start_payload("deal_12").kind == "deal"
    assert parse_start_payload("tg_short").kind == "unknown"
