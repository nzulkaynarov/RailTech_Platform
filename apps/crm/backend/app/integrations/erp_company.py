"""Карточка клиента из ERP (шов 0.3.0, FIX-60): долг по валютам.

`GET /api/integration/v1/companies/{erp_company_id}/summary` → `CompanySummary` (CONTRACTS §2).
CRM берёт из ответа только `receivables_by_currency` — долг по каждой валюте отдельно, без
пересчёта по курсу (Q-FIX30-2). Читатель терпимый (Q-FIX35-4): лишние поля игнорируются; нет
поля (ERP старше шва 0.3.0), оно не список или в нём мусор — `None`/пропуск строки, а не ошибка:
карточка клиента остаётся такой, как была.
"""

import re
from dataclasses import dataclass
from typing import Protocol

from app.domain.errors import Reason, UpstreamUnavailableError
from app.integrations.erp_http import ErpIntegrationHttp, bad_response

_AMOUNT = re.compile(r"^-?\d+\.\d{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class Money:
    amount: str
    currency: str


@dataclass(frozen=True, slots=True)
class CompanyReceivables:
    #: Долг по валютам; пусто — долга нет; `None` — ERP не прислала поле (карточка без блока).
    by_currency: list[Money] | None


class ErpCompanyClient(Protocol):
    async def receivables(self, erp_company_id: int) -> CompanyReceivables: ...


def parse_receivables(data: object) -> CompanyReceivables:
    """Тело `CompanySummary` → долг по валютам; неразборчивые строки пропускаются."""
    raw = data.get("receivables_by_currency") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return CompanyReceivables(None)
    rows = [
        Money(item["amount"], item["currency"])
        for item in raw
        if isinstance(item, dict)
        and isinstance(item.get("amount"), str)
        and isinstance(item.get("currency"), str)
        and _AMOUNT.fullmatch(item["amount"])
        and _CURRENCY.fullmatch(item["currency"])
    ]
    return CompanyReceivables(rows)


class HttpxErpCompanyClient(ErpIntegrationHttp):
    async def receivables(self, erp_company_id: int) -> CompanyReceivables:
        response = await self._send("GET", f"/companies/{int(erp_company_id)}/summary")
        if response.status_code == 404:
            return CompanyReceivables(None)  # компании в ERP нет: показывать нечего
        if response.status_code != 200:
            raise bad_response(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise UpstreamUnavailableError(
                "bad json from erp", reason=Reason.ERP_BAD_RESPONSE
            ) from exc
        return parse_receivables(data)
