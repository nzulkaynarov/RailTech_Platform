"""Версия токенов пользователя (FIX-11, S-6): отзыв доступа гасит и access-токены.

JWT-токены сотрудника несут claim `tv` = `CustomUser.token_version` на момент выдачи. Отзыв доступа из CRM
(`integration.services.provision.revoke_crm_user_sessions`) увеличивает версию — аутентификация
(`accounts.authentication.TokenVersionJWTAuthentication`) отвечает 401 на access с другой версией, а
`CookieTokenRefreshView` — на refresh. Токен без claim (выдан до FIX-11) равен версии 0: пока доступ не
отзывали, он живёт; после первого отзыва — нет.
"""

from __future__ import annotations

from rest_framework_simplejwt.tokens import RefreshToken

TOKEN_VERSION_CLAIM = "tv"


def token_version_of(token) -> int:
    """Версия из токена (access или refresh); нет claim или мусор — 0."""
    try:
        return int(token.get(TOKEN_VERSION_CLAIM, 0))
    except (TypeError, ValueError):
        return -1  # не число — никогда не совпадёт с версией пользователя


def refresh_for(user) -> RefreshToken:
    """Refresh-токен сотрудника с текущей версией; access из него (`.access_token`) её наследует."""
    refresh = RefreshToken.for_user(user)
    refresh[TOKEN_VERSION_CLAIM] = user.token_version
    return refresh
