"""SIGN-4, FX-10: строки «Ждут вашей подписи» из маршрутов EDS `signing`."""

from typing import Any

import pytest

from app.eds_approvals import signing_page


class FakeProxy:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.params: dict[str, Any] = {}

    async def request(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self.params = params
        return self.payload


@pytest.mark.asyncio
async def test_rows_carry_document_and_amount_and_only_open_own_steps_are_asked() -> None:
    proxy = FakeProxy(
        {
            "items": [
                {
                    "id": "40000000-0000-4000-8000-000000000115",
                    "title": "Договор Д-500",
                    "created_at": "2026-11-09T08:00:00Z",
                    "object": {
                        "kind": "signing",
                        "signing_kind": "contract",
                        "signing_number": "Д-500",
                        "signing_amount_tiyins": 1250050,
                        "signing_currency": "UZS",
                    },
                }
            ]
        }
    )

    page = await signing_page(proxy)  # type: ignore[arg-type]

    assert proxy.params["mine"] == "true"
    assert proxy.params["template"] == ["signing"]
    assert proxy.params["status"] == ["open"]
    [row] = page.items
    assert (row.kind, row.number, row.amount, row.currency) == (
        "contract",
        "Д-500",
        "12500.50",
        "UZS",
    )
