"""Код входа из письма (B-MAIL-1): 6 цифр рядом со ссылкой входа и приглашения.

Зачем: письмо может идти несколько минут, а ссылка открыться на другом устройстве — клиент вводит код на экране
«Мы отправили письмо» (как Slack, Notion, Stripe). Код и ссылка — одна запись `MagicLinkToken`: погашение любым
гасит оба, срок один (вход — 60 минут, приглашение — 24 часа).

Защита: в базе только HMAC-SHA256 кода (ключ — `SECRET_KEY`, в сообщении — id контакта: таблица без ключа кодов не
выдаёт); сравнение `hmac.compare_digest`; погашение — `select_for_update` + `used_at` + сессия в одной транзакции
(второй параллельный ввод того же кода получает отказ); не больше `LOGIN_CODE_MAX_ATTEMPTS` неверных попыток на
письмо (`code_attempts`) и на адрес (счётчик в кэше: неизвестный адрес блокируется так же, как известный, — ответ не
выдаёт, есть ли адрес). Новый запрос письма (`request_magic_link`) сбрасывает счётчик адреса и гасит прежний код.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from parties.models import Contact
from portal.exceptions import PortalTooManyRequests, PortalValidationError
from portal.models import MagicLinkToken, PortalSession
from portal.services.access import company_has_cabinet_access
from portal.services.tokens import generate_token, hash_token, issue_portal_session
from rest_framework.exceptions import PermissionDenied

logger = logging.getLogger(__name__)

#: Срок письма входа по запросу клиента — ссылки и кода (B-MAIL-1: письмо может идти несколько минут).
LOGIN_LINK_TTL = timedelta(minutes=60)
#: Срок письма-приглашения из ERP (не меняется B-MAIL-1).
INVITE_LINK_TTL = timedelta(hours=24)
LOGIN_CODE_DIGITS = 6
#: Неверных кодов подряд до блокировки (на письмо и на адрес); дальше — только новый код.
LOGIN_CODE_MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class IssuedLogin:
    """Что уходит клиенту в письме: ссылка (сырой токен) и код. В базе — только их хеши."""

    raw_token: str
    code: str


def generate_login_code() -> str:
    """Случайный код из 6 цифр с ведущими нулями (`secrets`, не `random`)."""
    return f"{secrets.randbelow(10**LOGIN_CODE_DIGITS):0{LOGIN_CODE_DIGITS}d}"


def hash_login_code(contact_id: int, code: str) -> str:
    """HMAC-SHA256 кода с ключом `SECRET_KEY`: 10⁶ вариантов кода не перебрать по утёкшей таблице без ключа."""
    message = f"portal-login-code:{contact_id}:{code}".encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), message, hashlib.sha256).hexdigest()


def issue_login(contact: Contact, purpose: str, ttl: timedelta) -> IssuedLogin:
    """Новая запись входа (ссылка + код) для письма; прежние записи того же назначения гасятся.

    Вход гасит только прежние входы, приглашение — только прежние приглашения: одно не отнимает другое.
    """
    MagicLinkToken.objects.filter(contact=contact, purpose=purpose, used_at__isnull=True).update(used_at=timezone.now())
    issued = IssuedLogin(raw_token=generate_token(), code=generate_login_code())
    MagicLinkToken.objects.create(
        token_hash=hash_token(issued.raw_token),
        code_hash=hash_login_code(contact.pk, issued.code),
        contact=contact,
        purpose=purpose,
        expires_at=timezone.now() + ttl,
    )
    return issued


# ── Счётчик неверных кодов на адрес (кэш) ────────────────────────────────────────────────────────────────────────


def _failures_key(clean_email: str) -> str:
    return "portal:login-code-failures:" + hashlib.sha256(clean_email.encode("utf-8")).hexdigest()[:32]


def address_failures(clean_email: str) -> int:
    return int(cache.get(_failures_key(clean_email)) or 0)


def _register_failure(clean_email: str) -> int:
    key = _failures_key(clean_email)
    ttl = int(LOGIN_LINK_TTL.total_seconds())
    cache.add(key, 0, ttl)
    try:
        return int(cache.incr(key))
    except ValueError:  # ключ истёк между add и incr
        cache.set(key, 1, ttl)
        return 1


def reset_address_failures(clean_email: str) -> None:
    """Новый код для адреса — счёт попыток заново (вызывается при запросе письма и приглашении)."""
    cache.delete(_failures_key(clean_email))


# ── Обмен кода на сессию ──────────────────────────────────────────────────────────────────────────────────────────


def _locked_candidates(contact: Contact) -> List[MagicLinkToken]:
    """Живые записи контакта с кодом, под блокировкой строк до конца транзакции (вход и приглашение — до двух).

    После коммита параллельного погашения PostgreSQL перепроверяет условие: погашенная строка сюда уже не попадает.
    """
    return list(
        MagicLinkToken.objects.select_for_update(of=("self",))
        .filter(
            contact=contact,
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
            code_attempts__lt=LOGIN_CODE_MAX_ATTEMPTS,
        )
        .exclude(code_hash="")
        .order_by("-created_at")
    )


def _redeem(contact: Contact, code: str, ip_address: Optional[str], user_agent: str) -> Optional[Tuple]:
    """Одна транзакция: найти запись по коду, погасить её и выдать сессию; `None` — код не подошёл (попытка учтена)."""
    supplied = hash_login_code(contact.pk, code)
    with transaction.atomic():
        candidates = _locked_candidates(contact)
        match = None
        for row in candidates:  # сравниваем со всеми — время ответа не зависит от того, какая запись подошла
            if hmac.compare_digest(row.code_hash, supplied) and match is None:
                match = row
        if match is None:
            if candidates:
                MagicLinkToken.objects.filter(pk__in=[row.pk for row in candidates]).update(
                    code_attempts=F("code_attempts") + 1
                )
            return None
        if not company_has_cabinet_access(contact.company_id) or contact.is_archived:
            logger.info("Login code of a contact without cabinet access rejected (contact %s)", contact.pk)
            raise PermissionDenied("FORBIDDEN")
        match.used_at = timezone.now()
        match.save(update_fields=["used_at"])
        return issue_portal_session(contact, "magic_link", ip_address=ip_address, user_agent=user_agent)


def exchange_login_code(
    email: str, code: str, ip_address: Optional[str] = None, user_agent: str = ""
) -> Tuple[PortalSession, str]:
    """`POST /auth/code`: код из письма → сессия портала.

    Неверный, просроченный, использованный код и неизвестный адрес — 422 `LOGIN_CODE_INVALID` (один ответ);
    `LOGIN_CODE_MAX_ATTEMPTS`-я неверная попытка и дальше — 429 `LOGIN_CODE_LOCKED`, пока адрес не запросит новый код.
    """
    from portal.services.magic_link import find_login_contact

    clean_email = email.strip().lower()
    if address_failures(clean_email) >= LOGIN_CODE_MAX_ATTEMPTS:
        raise PortalTooManyRequests("LOGIN_CODE_LOCKED")

    contact = find_login_contact(clean_email)
    # Неизвестный адрес проходит тот же `_redeem` с несуществующим контактом: блокировка и хеш кода те же (B-FX3-1)
    result = _redeem(contact if contact is not None else Contact(pk=0), code, ip_address, user_agent)
    if result is not None:
        reset_address_failures(clean_email)
        return result

    failures = _register_failure(clean_email)
    logger.info("Login code rejected (attempt %s for the address)", failures)
    if failures >= LOGIN_CODE_MAX_ATTEMPTS:
        raise PortalTooManyRequests("LOGIN_CODE_LOCKED")
    raise PortalValidationError("LOGIN_CODE_INVALID")
