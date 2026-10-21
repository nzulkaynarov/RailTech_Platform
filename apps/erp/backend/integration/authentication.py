"""Integration authentication (CONTRACTS §0, §2, M3-ERP-01).

Проверяет заголовок `Authorization: Bearer <token>` против токенов из `services.credentials`: выданных сопряжением
(БД, шифрованно) либо, пока сопряжения нет, `settings.SERVICE_TOKEN_CRM_TO_ERP` (M3-ERP-05).
Поддерживает до двух активных сервисных токенов для бесшовной ротации без простоя.
"""

from __future__ import annotations

from typing import Optional, Tuple

from django.contrib.auth.models import AnonymousUser
from rest_framework import authentication, exceptions

from .services import credentials


class IntegrationTokenAuthentication(authentication.BaseAuthentication):
    """Аутентификация сервисных вызовов CRM → ERP.

    Читает заголовок `Authorization: Bearer <сервисный токен CRM→ERP>`.
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
        # Безопасное сравнение токенов против time-attack — внутри `token_is_active`.
        if not credentials.token_is_active(token):
            raise exceptions.AuthenticationFailed("UNAUTHORIZED")

        request.is_crm_service = True
        return (AnonymousUser(), token)
