"""Лимиты частоты портала: по сессии, а не по IP (FIX-15, аудит P-14).

Общий анонимный лимит DRF (20/мин по IP) для портала не годится: экран Cabinet — пачка запросов, а за
одним NAT сидят все клиенты компании, поэтому интерфейс упирался в 429 при обычной работе. Здесь:

- `PortalSessionRateThrottle` — ключ id сессии портала (смена IP счётчик не сбрасывает, соседи за NAT
  не мешают друг другу);
- `PortalLoginRateThrottle` (scope `portal_login`) — вход без сессии (запрос magic-link, обмен ссылки,
  `initData`), ключ — IP: сессии ещё нет, а подбор и рассылка бьют именно по входу. Лимит на адрес
  e-mail (N в час) считает `portal.services.magic_link`;
- `PortalAcceptRateThrottle` (scope `portal_accept`) — попытки акцепта КП с кодом, ключ — сессия:
  жёсткий потолок против перебора кода поверх лимита попыток самого кода.

Ставки — `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` (`core/settings/api.py`, env `PORTAL_*_RATE`).
Ответ при превышении — 429 `{"detail": "TOO_MANY_REQUESTS"}` и `Retry-After` (`portal_exception_handler`).
"""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


class _PortalSessionKeyedThrottle(SimpleRateThrottle):
    """Ключ — id сессии портала; без сессии (аутентификация не прошла) — IP, чтобы подбор не был бесплатным."""

    def get_cache_key(self, request, view):
        session = getattr(request, "portal_session", None)
        ident = f"session:{session.pk}" if session is not None else f"ip:{self.get_ident(request)}"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PortalSessionRateThrottle(_PortalSessionKeyedThrottle):
    scope = "portal_session"


class PortalAcceptRateThrottle(_PortalSessionKeyedThrottle):
    scope = "portal_accept"


class PortalLoginRateThrottle(SimpleRateThrottle):
    scope = "portal_login"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
