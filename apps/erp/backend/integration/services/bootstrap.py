"""Первое сопряжение без кода — «bootstrap» (M3-ERP-05, CONTRACTS §2, ADR-0009).

Зачем: на свежем проде в ERP нет суперпользователя (сотрудники приходят провижинингом из CRM, а он требует сопряжения),
значит выпустить код некому, кроме как по ssh. Поэтому пока окно открыто, CRM вместо кода доказывает владение общим
`PLATFORM_SSO_SECRET`: обе системы читают один `.env`. Модель доверия: «владение общим секретом платформы = право первого
сопряжения» — тот, у кого он есть, и так может выпускать SSO-токены в ERP.

Доказательство — заголовок `X-Pairing-Proof: v1.<unix-время>.<jti>.<hex>`:
- ключ = HKDF-SHA256(ikm=PLATFORM_SSO_SECRET, info="rt-pairing-v1", 32 байта) — сам SSO-секрет напрямую не используется;
- подпись = HMAC-SHA256(ключ, "<время>.<jti>.<sha256-hex тела>"), тело привязано хешем (подмена тройки секретов — отказ);
- метка времени — окно 300 с в обе стороны; `jti` одноразов (ERP помнит 10 минут, общий кэш).
Окно закрывается НАВСЕГДА после первого успешного сопряжения любым способом (`PairingState.bootstrap_used_at`, см.
`services/pairing.py`): флаг переживает очистку токенов. Ни доказательства, ни ключи, ни `jti` в журналы не пишутся.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Iterable, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.cache import cache

from .pairing import PairingCodeError

LABEL = b"rt-pairing-v1"
VERSION = "v1"
WINDOW_SECONDS = 300
JTI_TTL_SECONDS = 600
_JTI = re.compile(r"^[A-Za-z0-9_\-]{16,64}$")
_HEX = re.compile(r"^[0-9a-f]{64}$")
_CACHE_PREFIX = "pairing-bootstrap-jti:"


def derive_key(secret: str) -> bytes:
    """HKDF-SHA256 с меткой назначения `rt-pairing-v1`: ключ доказательства отделён от остальных применений секрета."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=LABEL).derive(secret.encode())


def sign(secret: str, body: bytes, timestamp: int, jti: str) -> str:
    """Значение заголовка `X-Pairing-Proof` (эталон для тестов и тест-вектора контракта)."""
    message = f"{timestamp}.{jti}.{hashlib.sha256(body).hexdigest()}"
    digest = hmac.new(derive_key(secret), message.encode(), hashlib.sha256).hexdigest()
    return f"{VERSION}.{timestamp}.{jti}.{digest}"


def _secrets() -> Iterable[str]:
    raw = getattr(settings, "PLATFORM_SSO_SECRET", [])
    values = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    return [str(value).strip() for value in values if str(value).strip()]


def verify(header: str, body: bytes, *, now: Optional[float] = None) -> None:
    """Проверяет доказательство; любой изъян — `PairingCodeError` (401) с кодом `PAIRING_PROOF_*`.

    Порядок: формат и подпись → окно времени → одноразовость `jti` (только для подлинной подписи, чтобы чужие запросы
    не забивали кэш и не узнавали, истёк ли срок).
    """
    parts = (header or "").strip().split(".")
    if len(parts) != 4 or parts[0] != VERSION:
        raise PairingCodeError("PAIRING_PROOF_INVALID")
    _, ts_raw, jti, signature = parts
    if not ts_raw.isdigit() or len(ts_raw) > 12 or not _JTI.match(jti) or not _HEX.match(signature):
        raise PairingCodeError("PAIRING_PROOF_INVALID")
    timestamp = int(ts_raw)
    candidates = list(_secrets())
    if not candidates:  # общего секрета нет — bootstrap недоступен, сопрягаться кодом
        raise PairingCodeError("PAIRING_PROOF_INVALID")
    valid = False
    for secret in candidates:  # ротация SSO-секрета: подходит любой действующий
        expected = sign(secret, body, timestamp, jti).rsplit(".", 1)[1]
        valid = hmac.compare_digest(expected, signature) or valid
    if not valid:
        raise PairingCodeError("PAIRING_PROOF_INVALID")
    current = time.time() if now is None else now
    if abs(current - timestamp) > WINDOW_SECONDS:
        raise PairingCodeError("PAIRING_PROOF_EXPIRED")
    if not cache.add(_CACHE_PREFIX + jti, 1, JTI_TTL_SECONDS):
        raise PairingCodeError("PAIRING_PROOF_REPLAYED")
