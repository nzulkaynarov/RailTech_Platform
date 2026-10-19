"""Аутентификация сотрудников: JWT с версией токенов (FIX-11, S-6).

Замыкает цепочку настроек (последний модуль): подменяет только класс аутентификации DRF, остальное в
`REST_FRAMEWORK` (лимиты, пагинация, версии API — `api.py`) остаётся как есть. `TokenVersionJWTAuthentication`
ведёт себя как `JWTAuthentication` и дополнительно отвечает 401 на access-токен с устаревшей версией
`CustomUser.token_version` — так отзыв доступа из CRM гасит и уже выданные access-токены.
"""

from .observability import REST_FRAMEWORK as _REST_FRAMEWORK
from .observability import *  # noqa: F401,F403 — последовательная композиция настроек

REST_FRAMEWORK = {
    **_REST_FRAMEWORK,
    "DEFAULT_AUTHENTICATION_CLASSES": ("accounts.authentication.TokenVersionJWTAuthentication",),
}
