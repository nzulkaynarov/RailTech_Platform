"""ЕД-4: позиция каталога в строке — одна схема `ItemRef` и миниатюра для всех, кто видит строки.

ERP — на respx. Миниатюра доступна по разделам строк (`erp.stock`, `erp.calc`, `eds.drafts`,
`eds.projects`, `eds.payments`), а не только каталога; адрес в ответах несёт версию фото — новое
фото, новый адрес."""

import httpx
import pytest

from app.schemas_item_ref import ItemRef, item_ref
from tests.backends import Backends
from tests.conftest import Web
from tests.consts import ERP_URL

API = f"{ERP_URL}/api/v1"
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"0" * 16


def test_ref_from_erp_names_the_card_and_versions_the_thumbnail() -> None:
    raw = {"id": 4, "name": "Реле защиты РЗ-1", "sku": "RT-00004", "kind": "goods", "photo": 8}
    assert item_ref(raw) == ItemRef(
        id="4",
        name="Реле защиты РЗ-1",
        sku="RT-00004",
        kind="goods",
        thumbnail="/api/v1/erp/catalog/items/4/thumbnail?v=8",
    )
    assert item_ref({**raw, "photo": None, "kind": "service"}) == ItemRef(
        id="4", name="Реле защиты РЗ-1", sku="RT-00004", kind="service", thumbnail=None
    )


@pytest.mark.parametrize("raw", [None, {}, {"id": "4", "name": "x"}, {"id": 4, "name": ""}, "4"])
def test_broken_ref_is_none_and_the_row_stays_text(raw: object) -> None:
    assert item_ref(raw) is None


@pytest.mark.parametrize("role", ["MANAGER", "SUPPLY", "ACCOUNTANT", "REGISTRAR"])
async def test_thumbnail_is_served_to_everyone_who_sees_item_rows(
    web: Web, be: Backends, role: str
) -> None:
    await web.login([role])
    erp = be.router.get(f"{API}/catalog/items/4/thumbnail/").mock(
        return_value=httpx.Response(200, content=WEBP, headers={"content-type": "image/webp"})
    )

    response = await web.client.get("/api/v1/erp/catalog/items/4/thumbnail", params={"v": "8"})

    assert response.status_code == 200
    assert response.content == WEBP
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "private, max-age=86400"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert erp.call_count == 1


async def test_thumbnail_is_closed_without_item_sections(web: Web, be: Backends) -> None:
    await web.login(["ADMIN"])
    erp = be.router.get(f"{API}/catalog/items/4/thumbnail/")

    response = await web.client.get("/api/v1/erp/catalog/items/4/thumbnail")

    assert response.status_code == 403
    assert erp.call_count == 0


async def test_no_photo_or_not_webp_is_not_found(web: Web, be: Backends) -> None:
    await web.login(["MANAGER"])
    be.router.get(f"{API}/catalog/items/4/thumbnail/").mock(
        return_value=httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
    )
    be.router.get(f"{API}/catalog/items/5/thumbnail/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )

    assert (await web.client.get("/api/v1/erp/catalog/items/4/thumbnail")).status_code == 404
    assert (await web.client.get("/api/v1/erp/catalog/items/5/thumbnail")).status_code == 404


def test_quote_line_keeps_a_decimal_quantity_and_its_amount() -> None:
    """ADR-0027 п. 9: строка КП «12,5 т» — не «0» и сумма не 0 (раньше BFF брал только целое)."""
    from app.eds_approvals import _lines

    [line] = _lines(
        {
            "items": [
                {
                    "display_type": "ITEM",
                    "product_name": "Рельс Р65",
                    "unit": "т",
                    "quantity": 12.5,
                    "final_price_excl_vat": "1000.00",
                }
            ]
        }
    )
    assert (line.quantity, line.amount, line.item) == (12.5, "12500.00", None)


ERP_REF = {"id": 4, "name": "Реле защиты РЗ-1", "sku": "RT-00004", "kind": "goods", "photo": 8}
THUMB = "/api/v1/erp/catalog/items/4/thumbnail?v=8"


def test_every_stock_row_carries_the_thumbnail_through_our_api_only() -> None:
    """ЕД-4: приёмка, резервы, отгрузки, поиск — миниатюра и артикул, адрес наш, с версией."""
    from app.schemas_erp_stock import to_receipts, to_reservation, to_shipment, to_trace

    receipts = to_receipts(
        {
            "pending": [
                {
                    "order_number": "ЗП-1",
                    "supplier_name": "П",
                    "order_line_id": 7,
                    "name": "Реле",
                    "item": ERP_REF,
                    "quantity": 2,
                    "received_quantity": 0,
                }
            ],
            "done": [
                {
                    "id": 1,
                    "order_number": "ЗП-1",
                    "supplier_name": "П",
                    "received_at": "2026-11-20T10:00:00Z",
                    "quantity": 2,
                    "lines": [{"name": "Реле", "item": ERP_REF, "quantity": 2}],
                }
            ],
            "rights": {"manage": True, "ship": True},
        }
    )
    reservation = to_reservation(
        {
            "id": 3,
            "product_id": 4,
            "product_name": "Реле",
            "item": ERP_REF,
            "deal": {"id": 9, "number": "З-9", "title": "Т"},
            "quote_item_id": None,
            "quantity": 2,
            "shipped_quantity": 0,
            "remaining": 2,
            "status": "active",
            "created_at": "2026-11-20T10:00:00Z",
        }
    )
    shipment = to_shipment(
        {
            "id": 1,
            "number": "О-1",
            "deal": {"id": 9, "number": "З-9", "title": "Т"},
            "shipped_at": "2026-11-20T10:00:00Z",
            "lines": [
                {"product_id": 4, "item": ERP_REF, "name": "Реле", "quantity": 2, "units": []}
            ],
        }
    )
    trace = to_trace(
        {
            "results": [
                {
                    "id": 1,
                    "kind": "serial",
                    "number": "SN-1",
                    "quantity": 1,
                    "shipped_quantity": 0,
                    "status": "in_stock",
                    "product": {"id": 4, "item": ERP_REF, "name": "Реле", "article": "РЗ"},
                    "origin": {
                        "received_at": "2026-11-20T10:00:00Z",
                        "order_number": "ЗП-1",
                        "supplier_name": "П",
                        "deal": None,
                    },
                    "destinations": [],
                }
            ]
        }
    )

    refs = [
        receipts.pending[0].item,
        receipts.done[0].lines[0].item,
        reservation.item,
        shipment.lines[0].item,
        trace.items[0].product.item,
    ]
    assert [r and r.thumbnail for r in refs] == [THUMB] * 5
    assert all(r and r.sku == "RT-00004" for r in refs)


def test_old_erp_without_item_keeps_the_row_text_only() -> None:
    from app.schemas_erp_stock import to_shipment

    shipment = to_shipment(
        {
            "id": 1,
            "number": "О-1",
            "deal": {"id": 9, "number": "З-9", "title": "Т"},
            "shipped_at": "2026-11-20T10:00:00Z",
            "lines": [{"product_id": 4, "name": "Реле", "quantity": 2, "units": []}],
        }
    )
    assert shipment.lines[0].item is None
