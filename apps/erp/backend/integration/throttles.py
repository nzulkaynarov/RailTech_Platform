"""Лимит частоты запросов CRM к integration (Q-FIX30-4, FIX-35).

Запрос с валидным сервисным токеном — «анонимный» пользователь DRF, и общий лимит `anon` (20 в минуту с адреса)
душил бота и карточки CRM: один экран — несколько запросов, а за ним ещё `health`. Здесь свой scope
`integration` (`core/settings/api.py`, env `INTEGRATION_RATE`, по умолчанию 300/minute): ключ — хеш токена,
а не адрес. Лимит нужен как предохранитель от зацикленного клиента, а не как ограничение обычной работы.

Неаутентифицированный запрос отвечает 401 раньше throttle (DRF: аутентификация — до лимитов).
Ответ при превышении — 429 `{"detail": "TOO_MANY_REQUESTS"}` и `Retry-After` (`integration_exception_handler`).
"""

from __future__ import annotations

import hashlib

from rest_framework.throttling import SimpleRateThrottle


class IntegrationServiceRateThrottle(SimpleRateThrottle):
    scope = "integration"

    def get_cache_key(self, request, view):
        token = request.auth if isinstance(request.auth, str) else ""
        if not token:
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        return self.cache_format % {"scope": self.scope, "ident": digest}
