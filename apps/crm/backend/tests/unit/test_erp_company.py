"""Долг клиента по валютам из карточки ERP (шов 0.3.0, FIX-60): клиент, читатель, сервис."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.domain.errors import ConflictError, ErpRateLimitedError, NotFoundError, Reason
from app.integrations.erp_company import (
    CompanyReceivables,
    HttpxErpCompanyClient,
    Money,
    parse_receivables,
)
from app.services.erp_client_card import ErpClientCardService
from tests.unit.test_erp_handoff import _DummyStore

ERP = "https://erp.internal"
SUMMARY = f"{ERP}/api/integration/v1/companies/118/summary"
SUMMARY_BODY = {
    "erp_company_id": 118,
    "crm_client_id": 42,
    "name": "ООО Порядок",
    "open_deals": [],
    "receivables": {"amount": "1250000.00", "currency": "UZS"},
    "receivables_by_currency": [
        {"amount": "1250000.00", "currency": "UZS"},
        {"amount": "310.50", "currency": "USD"},
    ],
}


def _client() -> HttpxErpCompanyClient:
    return HttpxErpCompanyClient(
        _DummyStore("t"), Settings(erp_base_url=ERP, erp_service_token="t")
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (SUMMARY_BODY, [Money("1250000.00", "UZS"), Money("310.50", "USD")]),
        ({**SUMMARY_BODY, "receivables_by_currency": []}, []),
        # терпимый читатель: поля нет / не список — «данных нет», а не ошибка
        ({k: v for k, v in SUMMARY_BODY.items() if k != "receivables_by_currency"}, None),
        ({**SUMMARY_BODY, "receivables_by_currency": "много"}, None),
        ([], None),
        (None, None),
        # мусорные строки пропускаются, годные остаются; лишние поля игнорируются
        (
            {
                **SUMMARY_BODY,
                "from_the_future": 1,
                "receivables_by_currency": [
                    {"amount": "10.00", "currency": "UZS", "note": "x"},
                    {"amount": "10", "currency": "UZS"},
                    {"amount": "10.00", "currency": "uzs"},
                    {"amount": 10.0, "currency": "UZS"},
                    "UZS 10.00",
                    None,
                ],
            },
            [Money("10.00", "UZS")],
        ),
    ],
)
def test_receivables_reader_is_tolerant(body: Any, expected: list[Money] | None) -> None:
    assert parse_receivables(body) == CompanyReceivables(expected)


async def test_client_reads_receivables_by_currency_with_the_service_token() -> None:
    with respx.mock:
        route = respx.get(SUMMARY).mock(return_value=httpx.Response(200, json=SUMMARY_BODY))
        result = await _client().receivables(118)

    assert result.by_currency == [Money("1250000.00", "UZS"), Money("310.50", "USD")]
    assert route.calls.last.request.headers["authorization"] == "Bearer t"


async def test_an_older_erp_without_the_field_gives_no_data() -> None:
    old = {k: v for k, v in SUMMARY_BODY.items() if k != "receivables_by_currency"}
    with respx.mock:
        respx.get(SUMMARY).mock(return_value=httpx.Response(200, json=old))
        assert (await _client().receivables(118)).by_currency is None


async def test_unknown_company_gives_no_data() -> None:
    with respx.mock:
        respx.get(SUMMARY).mock(return_value=httpx.Response(404, json={"detail": "NOT_FOUND"}))
        assert (await _client().receivables(118)).by_currency is None


async def test_rate_limit_is_a_transient_error_with_the_pause() -> None:
    with respx.mock:
        respx.get(SUMMARY).mock(
            return_value=httpx.Response(
                429, json={"detail": "TOO_MANY_REQUESTS"}, headers={"Retry-After": "9"}
            )
        )
        with pytest.raises(ErpRateLimitedError) as caught:
            await _client().receivables(118)
    assert caught.value.retry_after_s == 9


# ── Сервис карточки: сбой ERP не ломает карточку ────────────────────────────────────────────────


class _Sessions:
    def __init__(self, erp_company_id: int | None, exists: bool = True) -> None:
        self._client = SimpleNamespace(erp_company_id=erp_company_id) if exists else None

    @asynccontextmanager
    async def __call__(self) -> Any:
        client = self._client

        class _Session:
            async def get(self, *_: Any) -> Any:
                return client

        yield _Session()


class _Erp:
    def __init__(self, result: CompanyReceivables | Exception) -> None:
        self.result = result
        self.calls: list[int] = []

    async def receivables(self, erp_company_id: int) -> CompanyReceivables:
        self.calls.append(erp_company_id)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _service(erp: _Erp, company_id: int | None = 118, *, exists: bool = True) -> Any:
    return ErpClientCardService(_Sessions(company_id, exists), erp)  # type: ignore[arg-type]


async def test_service_returns_the_debt_per_currency() -> None:
    erp = _Erp(CompanyReceivables([Money("5.00", "USD"), Money("7.00", "UZS")]))
    result = await _service(erp).receivables(42)
    assert (result.status, result.reason) == ("ok", None)
    assert result.receivables == [Money("5.00", "USD"), Money("7.00", "UZS")]
    assert erp.calls == [118]


async def test_service_reports_no_debt_as_an_empty_ok() -> None:
    result = await _service(_Erp(CompanyReceivables([]))).receivables(42)
    assert (result.status, result.receivables) == ("ok", [])


@pytest.mark.parametrize(
    ("erp_result", "reason", "retry_after"),
    [
        (CompanyReceivables(None), "no_data", None),
        (ErpRateLimitedError(33), "erp_rate_limited", 33),
        (ConflictError("x", reason=Reason.ERP_NOT_CONFIGURED), "erp_not_configured", None),
    ],
)
async def test_service_hides_the_block_instead_of_failing(
    erp_result: Any, reason: str, retry_after: int | None
) -> None:
    result = await _service(_Erp(erp_result)).receivables(42)
    assert (result.status, result.receivables) == ("unavailable", [])
    assert result.retry_after_s == retry_after
    assert result.reason == (reason if reason != "erp_rate_limited" else "rate_limited")


async def test_service_does_not_call_erp_for_a_client_not_in_erp() -> None:
    erp = _Erp(CompanyReceivables([]))
    result = await _service(erp, company_id=None).receivables(42)
    assert (result.status, result.reason) == ("unavailable", "not_linked")
    assert erp.calls == []


async def test_service_404_for_an_unknown_client() -> None:
    with pytest.raises(NotFoundError):
        await _service(_Erp(CompanyReceivables([])), exists=False).receivables(42)
