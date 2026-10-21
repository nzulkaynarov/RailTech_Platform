"""Секреты шва CRM ↔ ERP: БД (после сопряжения) → `.env` (запасной путь) (M3-ERP-05, CONTRACTS §0, §2).

Источник по каждому секрету:
- токены направления CRM→ERP: активны текущий и (на время ротации) прежний, пока `expires_at` не вышел; в БД пусто —
  `SERVICE_TOKEN_CRM_TO_ERP` из окружения (до двух значений через запятую, как раньше);
- секрет подписи вебхуков: строка `webhook_secret` в БД, иначе первое значение `ERP_WEBHOOK_SECRET`.

Значения шифруются в БД (Fernet, ключ — из `SECRET_KEY`, как у секрета 2FA). Нечитаемое значение (сменили `SECRET_KEY`) —
ошибка в лог без значения и возврат к `.env`: шов не должен падать 500-ми. В логи, ответы и аудит значения не попадают;
наружу — только `last4` и состояние.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone

from ..models import CredentialSlot, ServiceCredential

logger = logging.getLogger(__name__)

#: Метка домена ключа: производный ключ отличается от ключа 2FA, хотя оба берутся из `SECRET_KEY`.
_KEY_CONTEXT = b"integration.service-credentials:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(_KEY_CONTEXT + settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def last4(value: str) -> str:
    return value[-4:] if len(value) >= 8 else "****"


def _decrypt(row: ServiceCredential) -> Optional[str]:
    try:
        return _fernet().decrypt(row.ciphertext.encode()).decode()
    except InvalidToken:
        logger.error("integration credential %s is undecryptable (SECRET_KEY changed?); using .env fallback", row.slot)
        return None


def _rows() -> dict[str, ServiceCredential]:
    return {row.slot: row for row in ServiceCredential.objects.all()}


def _env_list(raw) -> list[str]:
    if isinstance(raw, (list, tuple)):
        values: Iterable[str] = (str(item) for item in raw)
    else:
        values = str(raw or "").split(",")
    return [value.strip() for value in values if value.strip()]


def env_crm_tokens() -> list[str]:
    return _env_list(getattr(settings, "SERVICE_TOKEN_CRM_TO_ERP", []))


def env_webhook_secret() -> str:
    return next(iter(_env_list(getattr(settings, "ERP_WEBHOOK_SECRET", ""))), "")


def stored_crm_token(rows: Optional[dict[str, ServiceCredential]] = None) -> Optional[str]:
    """Текущий токен CRM→ERP из БД; None — нет сопряжения или значение нечитаемо."""
    rows = _rows() if rows is None else rows
    row = rows.get(CredentialSlot.CRM_TO_ERP)
    return _decrypt(row) if row else None


def stored_previous_token(rows: Optional[dict[str, ServiceCredential]] = None) -> Optional[str]:
    """Прежний токен, если переходный срок ещё не вышел."""
    rows = _rows() if rows is None else rows
    row = rows.get(CredentialSlot.CRM_TO_ERP_PREVIOUS)
    if row is None or (row.expires_at is not None and row.expires_at <= timezone.now()):
        return None
    return _decrypt(row)


def active_crm_tokens() -> list[str]:
    """Токены, которыми CRM сейчас может входить в integration: БД, иначе `.env`."""
    rows = _rows()
    current = stored_crm_token(rows)
    if current:
        tokens = [current]
        previous = stored_previous_token(rows)
        if previous:
            tokens.append(previous)
        return tokens
    return env_crm_tokens()


def token_is_active(token: str) -> bool:
    """Сравнение без утечки по времени с каждым действующим токеном."""
    return any(secrets.compare_digest(token, expected) for expected in active_crm_tokens() if expected)


def webhook_secret() -> str:
    """Секрет, которым ERP подписывает вебхуки сейчас: БД, иначе `.env`. Пусто — секрета нет."""
    row = _rows().get(CredentialSlot.WEBHOOK_SECRET)
    stored = _decrypt(row) if row else None
    return stored or env_webhook_secret()


def erp_to_crm_token() -> str:
    """Токен направления ERP→CRM (его предъявляет ERP при обращениях к CRM, M3-CRM-11); пусто — не выдан."""
    row = _rows().get(CredentialSlot.ERP_TO_CRM)
    return (_decrypt(row) if row else None) or ""


@dataclass(frozen=True)
class CredentialStatus:
    """Состояние шва для экрана ERP «Интеграция с CRM» (только чтение): без значений секретов."""

    state: str  # paired | env | none
    paired_at: Optional[datetime]
    rotated_at: Optional[datetime]
    crm_to_erp_last4: str
    previous_token_valid_until: Optional[datetime]
    erp_to_crm_configured: bool
    webhook_secret_source: str  # db | env | none
    webhook_secret_last4: str
    token_source: str  # db | env | none


def status() -> CredentialStatus:
    rows = _rows()
    current_row = rows.get(CredentialSlot.CRM_TO_ERP)
    current = _decrypt(current_row) if current_row else None
    webhook_row = rows.get(CredentialSlot.WEBHOOK_SECRET)
    stored_webhook = _decrypt(webhook_row) if webhook_row else None
    env_tokens = env_crm_tokens()
    env_secret = env_webhook_secret()
    previous_row = rows.get(CredentialSlot.CRM_TO_ERP_PREVIOUS)
    previous_active = bool(stored_previous_token(rows))
    if current:
        state, token_source = "paired", "db"
    elif env_tokens:
        state, token_source = "env", "env"
    else:
        state, token_source = "none", "none"
    if stored_webhook:
        webhook_source, webhook_last4 = "db", last4(stored_webhook)
    elif env_secret:
        webhook_source, webhook_last4 = "env", ""  # значения `.env` на экран не выводятся, даже хвост
    else:
        webhook_source, webhook_last4 = "none", ""
    if current:
        token_last4 = last4(current)
    else:
        token_last4 = ""
    return CredentialStatus(
        state=state,
        paired_at=current_row.created_at if current else None,
        rotated_at=current_row.rotated_at if current else None,
        crm_to_erp_last4=token_last4,
        previous_token_valid_until=previous_row.expires_at if previous_active and previous_row else None,
        erp_to_crm_configured=bool(erp_to_crm_token()),
        webhook_secret_source=webhook_source,
        webhook_secret_last4=webhook_last4,
        token_source=token_source,
    )
