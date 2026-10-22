"""Доказательство первого сопряжения без кода (M3-CRM-10, CONTRACTS §2, ADR-0009).

CRM доказывает ERP владение общим `PLATFORM_SSO_SECRET`: заголовок
`X-Pairing-Proof: v1.<unix-время>.<jti>.<hex>`. Ключ = HKDF-SHA256(ikm=секрет, info="rt-pairing-v1",
32 байта): сам SSO-секрет напрямую не используется. Подпись = HMAC-SHA256(ключ,
"<время>.<jti>.<sha256-hex тела>"). Окно метки — 300 с, `jti` одноразов (помнит ERP). Секрет, ключ
и доказательство нигде не логируются.
"""

import hashlib
import hmac
import time
import uuid
from typing import Final

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

LABEL: Final = b"rt-pairing-v1"
VERSION: Final = "v1"
HEADER: Final = "X-Pairing-Proof"


def derive_key(secret: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=LABEL).derive(secret.encode())


def sign(secret: str, body: bytes, timestamp: int | None = None, jti: str | None = None) -> str:
    """Значение заголовка `X-Pairing-Proof` для данного тела запроса."""
    ts = int(time.time()) if timestamp is None else timestamp
    nonce = jti or uuid.uuid4().hex
    message = f"{ts}.{nonce}.{hashlib.sha256(body).hexdigest()}"
    digest = hmac.new(derive_key(secret), message.encode(), hashlib.sha256).hexdigest()
    return f"{VERSION}.{ts}.{nonce}.{digest}"
