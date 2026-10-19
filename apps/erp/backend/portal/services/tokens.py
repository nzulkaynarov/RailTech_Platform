"""Токены входа в портал: в базе лежит только SHA-256-хеш, сырое значение живёт в cookie или в ссылке (FIX-14, P-9)."""

import hashlib
import secrets

from django.conf import settings
from django.utils import timezone
from parties.models import Contact
from portal.models import PortalSession


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(raw_token: str) -> str:
    """Хеш для поиска и уникального индекса. Токен — 256 бит энтропии, соль и медленный хеш не нужны."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def token_prefix(token_or_hash: str) -> str:
    """Единственная форма токена, допустимая в логах: первые 6 символов."""
    return token_or_hash[:6]


def issue_portal_session(
    contact: Contact, auth_method: str, ip_address: str | None = None, user_agent: str = ""
) -> tuple[PortalSession, str]:
    """Создаёт сессию портала и возвращает (сессия, сырой токен для cookie). Токен в базе не хранится."""
    raw_token = secrets.token_hex(32)
    max_age_days = getattr(settings, "PORTAL_SESSION_MAX_AGE_DAYS", 14)
    session = PortalSession.objects.create(
        token_hash=hash_token(raw_token),
        contact=contact,
        company=contact.company,
        auth_method=auth_method,
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=timezone.now() + timezone.timedelta(days=max_age_days),
    )
    contact.last_login_at = timezone.now()
    contact.save(update_fields=["last_login_at"])
    return session, raw_token
