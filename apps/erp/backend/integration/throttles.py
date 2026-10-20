"""Лимит частоты сервисного токена CRM → ERP (FIX-33, Q-FIX30-4).

Токен CRM для DRF — анонимный пользователь, и общий `anon` (20/мин по IP) отвечал бы 429 вне контракта
`erp-integration.yaml` на обычной работе бота и карточек клиентов. Аутентификация проходит ДО throttle
(DRF: `perform_authentication` → `check_permissions` → `check_throttles`), поэтому неверный токен получает 401
и не расходует лимит. Токен общий на всё направление (CRM одна), ключ — весь сервис.
"""

from rest_framework.throttling import SimpleRateThrottle


class IntegrationServiceRateThrottle(SimpleRateThrottle):
    scope = "integration"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": "crm-service"}
