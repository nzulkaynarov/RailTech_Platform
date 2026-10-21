"""Данные ERP в карточке клиента CRM (шов 0.3.0, FIX-60): долг по валютам.

Только чтение и только то, что безопасно показать менеджеру. Любой сбой (коннектор не настроен,
ERP недоступна, лимит частоты, ответ без поля) — не ошибка карточки: блок «Долг» просто не
показывается (`status="unavailable"`), остальная карточка работает как раньше.
"""

from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import DomainError, ErpRateLimitedError, NotFoundError
from app.integrations.erp_company import ErpCompanyClient, Money
from app.models.clients import Client

logger = structlog.get_logger(__name__)

Status = Literal["ok", "unavailable"]


@dataclass(frozen=True, slots=True)
class ClientReceivables:
    status: Status
    receivables: list[Money]
    #: Почему блока нет (для подсказки админу); пусто при `ok`.
    reason: str | None = None
    retry_after_s: int | None = None


class ErpClientCardService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], erp_company: ErpCompanyClient
    ) -> None:
        self._sessions = sessions
        self._erp = erp_company

    async def receivables(self, client_id: int) -> ClientReceivables:
        async with self._sessions() as session:
            client = await session.get(Client, client_id)
            if client is None:
                raise NotFoundError("client not found")
            erp_company_id = client.erp_company_id
        if erp_company_id is None:
            return ClientReceivables("unavailable", [], reason="not_linked")
        try:
            result = await self._erp.receivables(erp_company_id)
        except ErpRateLimitedError as exc:
            return ClientReceivables(
                "unavailable", [], reason="rate_limited", retry_after_s=exc.retry_after_s
            )
        except DomainError as exc:
            reason = str(exc.details.get("reason") or exc.code)
            logger.warning("erp_receivables_unavailable", client_id=client_id, reason=reason)
            return ClientReceivables("unavailable", [], reason=reason)
        if result.by_currency is None:
            return ClientReceivables("unavailable", [], reason="no_data")
        return ClientReceivables("ok", result.by_currency)
