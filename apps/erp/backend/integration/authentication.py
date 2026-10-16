"""Integration authentication (CONTRACTS §0, §2, M3-ERP-01).

Проверяет заголовок `Authorization: Bearer <token>` против `settings.SERVICE_TOKEN_CRM_TO_ERP`.
Поддерживает до двух активных сервисных токенов для бесшовной ротации без простоя.
"""

from __future__ import annotations

import secrets
from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework import authentication, exceptions


class IntegrationTokenAuthentication(authentication.BaseAuthentication):
    """Аутентификация сервисных вызовов CRM → ERP.

    Читает заголовок `Authorization: Bearer <SERVICE_TOKEN_CRM_TO_ERP>`.
    При несовпадении или отсутствии токена возбуждает AuthenticationFailed("UNAUTHORIZED"),
    чтобы exception handler вернул строго 401 {"detail": "UNAUTHORIZED"}.
    """

    def authenticate(self, request) -> Optional[Tuple[AnonymousUser, str]]:
        auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header:
            raise exceptions.AuthenticationFailed("UNAUTHORIZED")

        parts = auth_header.strip().split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise exceptions.AuthenticationFailed("UNAUTHORIZED")

        token = parts[1]
        allowed_tokens = getattr(settings, "SERVICE_TOKEN_CRM_TO_ERP", [])
        if isinstance(allowed_tokens, str):
            allowed_tokens = [t.strip() for t in allowed_tokens.split(",") if t.strip()]

        # Безопасное сравнение токенов против time-attack
        is_valid = any(secrets.compare_digest(token, expected) for expected in allowed_tokens if expected)
        if not is_valid:
            raise exceptions.AuthenticationFailed("UNAUTHORIZED")

        request.is_crm_service = True
        return (AnonymousUser(), token)
