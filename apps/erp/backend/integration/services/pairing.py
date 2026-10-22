"""Сопряжение с CRM одним кодом (M3-ERP-05, CONTRACTS §2 «Сопряжение», ORCHESTRATOR §3.13).

Схема (паттерн «одноразовый ключ регистрации → обмен на постоянные учётные данные», как pre-auth key у Tailscale и
manifest-код у GitHub App):
1. `issue_code` — суперпользователь (или `manage.py pairing_code`) получает одноразовый код. В БД хеш, срок короткий,
   новый код гасит прежний.
2. CRM вызывает `accept` с кодом вместо токена и тремя секретами, которые сгенерировала сама. ERP сверяет код по хешу
   под блокировкой строки (гонка двух приёмов — один выигрывает), шифрованно сохраняет секреты и гасит код.
3. `rotate` — «Обновить ключи»: новая тройка под действующим токеном; прежний токен CRM→ERP остаётся активным на
   переходный срок (два активных), затем `credentials.active_crm_tokens` его не отдаёт.

Коды и секреты не логируются: исключения и журналы несут только состояние («погашен», «просрочен»).
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from ..exceptions import IntegrationConflict, IntegrationValidationError
from ..models import CredentialSlot, PairingCode, PairingState, ServiceCredential
from . import credentials

logger = logging.getLogger(__name__)

#: Алфавит без путаемых символов (0/O, 1/I/L): код вводят руками. 12 знаков = 59 бит энтропии.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
CODE_LENGTH = 12
_NOISE = re.compile(r"[\s\-_]")

DEFAULT_CODE_TTL_SECONDS = 15 * 60
DEFAULT_ROTATION_GRACE_SECONDS = 60 * 60


class PairingCodeError(APIException):
    """Код не принят: 401 `{"detail": "<PAIRING_CODE_…>"}` (контракт, `POST /pairing/accept`)."""

    status_code = 401
    default_detail = "PAIRING_CODE_INVALID"
    default_code = "pairing_code_invalid"

    def __init__(self, detail: str = "PAIRING_CODE_INVALID"):
        super().__init__(detail=detail, code=detail.lower())


@dataclass(frozen=True)
class IssuedCode:
    code: str  # открытый вид XXXX-XXXX-XXXX — показывается один раз
    expires_at: datetime
    ttl_seconds: int


@dataclass(frozen=True)
class Accepted:
    paired_at: datetime


@dataclass(frozen=True)
class Rotated:
    rotated_at: datetime
    previous_token_valid_until: datetime


def code_ttl_seconds() -> int:
    return int(getattr(settings, "PAIRING_CODE_TTL_SECONDS", DEFAULT_CODE_TTL_SECONDS))


def rotation_grace_seconds() -> int:
    return int(getattr(settings, "PAIRING_ROTATION_GRACE_SECONDS", DEFAULT_ROTATION_GRACE_SECONDS))


def normalize_code(raw: str) -> str:
    """Регистр, пробелы и дефисы не важны: `abcd efgh-jkmn` = `ABCDEFGHJKMN`."""
    return _NOISE.sub("", raw or "").upper()


def hash_code(normalized: str) -> str:
    return hashlib.sha256(normalized.encode()).hexdigest()


def _format_code(raw: str) -> str:
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def issue_code(*, created_by=None, now: Optional[datetime] = None) -> IssuedCode:
    """Новый код; прежние неиспользованные гасятся (одновременно жив один)."""
    now = now or timezone.now()
    ttl = code_ttl_seconds()
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    expires_at = now + timedelta(seconds=ttl)
    with transaction.atomic():
        PairingCode.objects.filter(used_at__isnull=True).update(used_at=now)
        PairingCode.objects.create(
            code_hash=hash_code(raw),
            expires_at=expires_at,
            created_by=created_by if getattr(created_by, "pk", None) else None,
        )
    logger.info("pairing code issued (expires %s)", expires_at.isoformat())
    return IssuedCode(code=_format_code(raw), expires_at=expires_at, ttl_seconds=ttl)


def _check_secrets(crm_to_erp: str, erp_to_crm: str, webhook: str) -> None:
    """Три значения различаются: иначе утечка одного открывает все три."""
    if len({crm_to_erp, erp_to_crm, webhook}) != 3:
        raise IntegrationValidationError()


def _put(
    slot: str, value: str, *, expires_at: Optional[datetime] = None, rotated_at: Optional[datetime] = None
) -> None:
    defaults = {"ciphertext": credentials.encrypt(value), "last4": credentials.last4(value), "expires_at": expires_at}
    if rotated_at is not None:
        defaults["rotated_at"] = rotated_at
    ServiceCredential.objects.update_or_create(slot=slot, defaults=defaults)


@transaction.atomic
def close_bootstrap_window(now: Optional[datetime] = None) -> None:
    """Первое сопряжение состоялось: «без кода» закрыто навсегда. Вызывается в транзакции записи секретов."""
    state, _ = PairingState.objects.select_for_update().get_or_create(pk=1)
    if state.bootstrap_used_at is None:
        state.bootstrap_used_at = now or timezone.now()
        state.save(update_fields=["bootstrap_used_at"])


def bootstrap_is_open() -> bool:
    state = PairingState.objects.filter(pk=1).first()
    return state is None or state.bootstrap_used_at is None


def _replace_credentials(crm_to_erp_token: str, erp_to_crm_token: str, webhook_secret: str) -> None:
    # Повторное сопряжение заменяет всё целиком: старые токены гаснут сразу, `created_at` = время нового сопряжения.
    ServiceCredential.objects.all().delete()
    for slot, value in (
        (CredentialSlot.CRM_TO_ERP, crm_to_erp_token),
        (CredentialSlot.ERP_TO_CRM, erp_to_crm_token),
        (CredentialSlot.WEBHOOK_SECRET, webhook_secret),
    ):
        _put(slot, value)


def accept_bootstrap(*, crm_to_erp_token: str, erp_to_crm_token: str, webhook_secret: str) -> Accepted:
    """Первое сопряжение без кода (доказательство уже проверено `services/bootstrap.verify`).

    Окно закрыто (первое сопряжение уже было — даже если токены потом очищены) → 409 `BOOTSTRAP_CLOSED`.
    """
    _check_secrets(crm_to_erp_token, erp_to_crm_token, webhook_secret)
    with transaction.atomic():
        state, _ = PairingState.objects.select_for_update().get_or_create(pk=1)
        if state.bootstrap_used_at is not None:
            raise IntegrationConflict("BOOTSTRAP_CLOSED")
        state.bootstrap_used_at = timezone.now()
        state.save(update_fields=["bootstrap_used_at"])
        _replace_credentials(crm_to_erp_token, erp_to_crm_token, webhook_secret)
    logger.info("crm paired (bootstrap)")
    return Accepted(paired_at=timezone.now())


def accept(raw_code: str, *, crm_to_erp_token: str, erp_to_crm_token: str, webhook_secret: str) -> Accepted:
    """Принять секреты CRM по одноразовому коду. Любая ошибка кода — `PairingCodeError` (401)."""
    _check_secrets(crm_to_erp_token, erp_to_crm_token, webhook_secret)
    normalized = normalize_code(raw_code)
    now = timezone.now()
    with transaction.atomic():
        row = (
            PairingCode.objects.select_for_update().filter(code_hash=hash_code(normalized)).first()
            if normalized
            else None
        )
        if row is None:
            raise PairingCodeError("PAIRING_CODE_INVALID")
        if row.used_at is not None:
            raise PairingCodeError("PAIRING_CODE_USED")
        if row.expires_at <= now:
            raise PairingCodeError("PAIRING_CODE_EXPIRED")
        row.used_at = now
        row.save(update_fields=["used_at"])
        _replace_credentials(crm_to_erp_token, erp_to_crm_token, webhook_secret)
        close_bootstrap_window(now)
    logger.info("crm paired")
    return Accepted(paired_at=timezone.now())


def _check_differs_from_effective(crm_to_erp: str, erp_to_crm: str, webhook: str) -> None:
    """Новая тройка не повторяет ни одного действовавшего значения (токены CRM→ERP — и переходный прежний, и из `.env`;
    токен ERP→CRM; секрет вебхуков): «обновить» ключ тем же значением — не ротация. Повтор УЖЕ применённой тройки
    сюда не доходит — он распознан раньше и идемпотентен."""
    if any(credentials.same_secret(crm_to_erp, token) for token in credentials.active_crm_tokens() if token):
        raise IntegrationValidationError()
    for new, effective in ((erp_to_crm, credentials.erp_to_crm_token()), (webhook, credentials.webhook_secret())):
        if effective and credentials.same_secret(new, effective):
            raise IntegrationValidationError()


def rotate(
    current_token: str,
    *,
    crm_to_erp_token: str,
    erp_to_crm_token: str,
    webhook_secret: str,
    now: Optional[datetime] = None,
) -> Rotated:
    """Ротация под действующим токеном: новая тройка, прежний токен CRM→ERP живёт ещё `rotation_grace_seconds`.

    Повтор той же тройки (CRM не получила ответ и зовёт снова — уже со старым токеном, он ещё действует) — тот же
    результат, переходный срок не продлевается. Новая тройка, которая совпадает с любым действовавшим значением
    (до первого применения), — 422. Токен из `.env` (сопряжения не было) тоже годится как «старый».
    """
    _check_secrets(crm_to_erp_token, erp_to_crm_token, webhook_secret)
    now = now or timezone.now()
    if credentials.same_secret(crm_to_erp_token, current_token):
        raise IntegrationValidationError()  # «новый» токен равен тому, под которым вызвана ротация
    with transaction.atomic():
        rows = {row.slot: row for row in ServiceCredential.objects.select_for_update().all()}
        stored_current = credentials.stored_crm_token(rows)
        if stored_current is not None and credentials.same_secret(crm_to_erp_token, stored_current):
            previous_row = rows.get(CredentialSlot.CRM_TO_ERP_PREVIOUS)
            previous = credentials.stored_previous_token(rows)
            if previous is not None and credentials.same_secret(current_token, previous) and previous_row is not None:
                # Повтор уже применённой ротации.
                _put(CredentialSlot.ERP_TO_CRM, erp_to_crm_token)
                _put(CredentialSlot.WEBHOOK_SECRET, webhook_secret)
                return Rotated(rotated_at=now, previous_token_valid_until=previous_row.expires_at)
            raise IntegrationValidationError()  # новый токен уже действует: менять нечего
        if stored_current is not None and not credentials.same_secret(current_token, stored_current):
            raise _unauthorized()
        _check_differs_from_effective(crm_to_erp_token, erp_to_crm_token, webhook_secret)
        valid_until = now + timedelta(seconds=rotation_grace_seconds())
        _put(CredentialSlot.CRM_TO_ERP_PREVIOUS, current_token, expires_at=valid_until)
        _put(CredentialSlot.CRM_TO_ERP, crm_to_erp_token, rotated_at=now)
        _put(CredentialSlot.ERP_TO_CRM, erp_to_crm_token)
        _put(CredentialSlot.WEBHOOK_SECRET, webhook_secret)
        close_bootstrap_window(now)
    logger.info("service credentials rotated (previous token valid until %s)", valid_until.isoformat())
    return Rotated(rotated_at=now, previous_token_valid_until=valid_until)


def _unauthorized():
    from rest_framework import exceptions

    return exceptions.AuthenticationFailed("UNAUTHORIZED")
