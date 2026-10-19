"""Лимит частоты erp-mcp: по компании из подписанного контекста, а не по IP (FIX-12, S-9).

Весь трафик агентов CRM приходит с одного адреса, поэтому общий анонимный лимит (20/мин по IP)
душил бы всех клиентов разом. Ключ — `erp_company_id` (в режиме prospect — `crm_client_id`);
запрос с невалидным контекстом считается по IP отправителя, чтобы подбор подписи не был бесплатным.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle

from .context import HEADER_NAME, AgentContextError, verify_agent_context


class AgentContextRateThrottle(SimpleRateThrottle):
    scope = "mcp"

    def get_cache_key(self, request, view):
        secret = settings.ERP_MCP_CONTEXT_KEY
        try:
            if not secret:
                raise AgentContextError("ERP_MCP_CONTEXT_KEY is not configured")
            context = verify_agent_context(request.headers.get(HEADER_NAME), secret)
        except AgentContextError:
            ident = f"invalid:{self.get_ident(request)}"
        else:
            if context.erp_company_id is not None:
                ident = f"company:{context.erp_company_id}"
            else:
                ident = f"prospect:{context.crm_client_id}"
        return self.cache_format % {"scope": self.scope, "ident": ident}
