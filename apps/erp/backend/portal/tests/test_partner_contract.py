"""Сторож контракта для раздела «Мои товары» (PART-2): ответы `/partner/*` проходят JSON Schema `erp-portal.yaml`.

Те же проверки, что у `test_contract_guard.py` (схема, множество ключей ⊆ `properties`), но на мире партнёра: сессия клиента
в этот раздел не допущена. Каждое значение enum, достижимое из модели, должно встретиться в ответах.
"""

import base64
import uuid
from types import SimpleNamespace

import pytest
from portal.tests.contract_support import check_response, component, contract_get_paths, response_schema
from portal.tests.partner_world import PREFIX, row, upload, xlsx
from portal.tests.test_contract_guard import PARTNER_GET_PATHS

from sourcing.catalog_import import run_catalog_import

pytestmark = pytest.mark.django_db


def test_partner_get_paths_are_exactly_the_contract_ones():
    assert PARTNER_GET_PATHS == {path for path in contract_get_paths() if path.startswith("/partner/")}


def assert_matches(body, path, method="get", status="200"):
    problems = check_response(body, response_schema(path, method, status))
    assert not problems, f"{method.upper()} {path}: " + "; ".join(problems)


def test_list_and_detail_match_the_contract(partner_world):
    w = partner_world
    page = w["client_a"].get(f"{PREFIX}/products")
    assert page.status_code == 200
    assert_matches(page.json(), "/partner/products")
    seen_status = {item["status"] for item in page.json()["items"]}
    seen_freshness = {item["offer"]["freshness"] for item in page.json()["items"] if item["offer"]}
    assert seen_status == set(component("PartnerCardStatus")["enum"])
    assert {"fresh", "expiring"} <= seen_freshness
    for card in w["cards"].values():
        response = w["client_a"].get(f"{PREFIX}/products/{card.pk}")
        if response.status_code == 200:
            assert_matches(response.json(), "/partner/products/{id}")


def test_every_review_decision_of_the_contract_is_reachable_and_valid_in_history(partner_world):
    """Решения истории сверяются с enum контракта, как статусы: каждое достижимо из модели, детальная — по схеме."""
    from catalog.models import ProductReview

    w = partner_world
    ProductReview.objects.create(product=w["cards"]["published"], decision="published")
    ProductReview.objects.create(product=w["cards"]["draft"], decision="cancelled")
    # значения модели и контракта совпадают: добавили решение в одном месте — тест краснеет, пока нет другого
    model_values = {value for value, _label in ProductReview.Decision.choices}
    contract_values = set(component("PartnerReviewEntry")["properties"]["decision"]["enum"])
    assert model_values == contract_values
    decisions = set()
    for card in w["cards"].values():
        response = w["client_a"].get(f"{PREFIX}/products/{card.pk}")
        if response.status_code == 200:
            assert_matches(response.json(), "/partner/products/{id}")
            decisions |= {h["decision"] for h in response.json()["history"]}
    assert decisions == contract_values


def test_submit_and_confirm_match_the_contract(partner_world):
    w = partner_world
    c = w["cards"]
    submit = w["client_a"].post(
        f"{PREFIX}/products/submit", {"ids": [c["draft"].pk, c["b_only"].pk, c["published"].pk]}, format="json"
    )
    assert_matches(submit.json(), "/partner/products/submit", "post")
    confirm = w["client_a"].post(f"{PREFIX}/offers/confirm", {"ids": [c["draft"].pk, c["b_only"].pk]}, format="json")
    assert_matches(confirm.json(), "/partner/offers/confirm", "post")
    assert {e["code"] for e in submit.json()["errors"] + confirm.json()["errors"]} <= set(
        component("ErrorCode")["x-extensible-enum"]
    )


def test_price_list_task_matches_the_contract(partner_world, monkeypatch):
    w = partner_world
    results = {}

    def delay(b64, supplier_id, dry_run, **options):
        task_id = uuid.uuid4().hex
        results[task_id] = run_catalog_import(base64.b64decode(b64), supplier_id, dry_run, **options)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr("portal.services.partner_price_list.process_catalog_import.delay", delay)
    monkeypatch.setattr(
        "portal.services.partner_price_list.async_result",
        lambda task_id: SimpleNamespace(state="SUCCESS", result=results[task_id]),
    )
    records = [
        row(),
        row(**{"Наименование": "Кран", "Артикул производителя": "K-1", "Цена": "abc"}),
        row(**{"Наименование": "Болт А-4 иначе", "Артикул производителя": "A-4"}),
        row(**{"Наименование": "Ещё одна", "Артикул производителя": "N-1", "Код ТН ВЭД": "99999999999999999999"}),
    ]
    accepted = upload(w["client_a"], xlsx(records))
    assert accepted.status_code == 202
    assert_matches(accepted.json(), "/partner/price-list", "post", "202")
    task = w["client_a"].get(f"{PREFIX}/price-list/{accepted.json()['task_id']}")
    assert_matches(task.json(), "/partner/price-list/{task_id}")
    report = task.json()["report"]
    assert report["errors"] and report["proposals"] and report["missing_breakdown"]


def test_price_template_is_a_workbook(partner_world):
    response = partner_world["client_a"].get(f"{PREFIX}/price-template")
    assert response.status_code == 200 and response.content[:2] == b"PK"
    assert "spreadsheetml" in response["Content-Type"]


def test_partner_orders_and_rfq_match_contract(partner_world):
    from decimal import Decimal

    from supply.models import (
        GoodsReceipt,
        GoodsReceiptLine,
        OrderLogKind,
        OrderStatus,
        PriceRequest,
        PriceRequestLine,
        PriceRequestStatus,
        SupplierOrder,
        SupplierOrderLine,
        SupplierOrderLog,
    )

    w = partner_world
    a = w["a"]
    b = w["b"]
    product = w["cards"]["published"]

    # 1. Заказы поставщику
    order_sent = SupplierOrder.objects.create(
        number="ЗП-2026-001",
        number_year=2026,
        number_seq=1,
        supplier=a,
        status=OrderStatus.SENT,
        note="Срочный заказ",
    )
    SupplierOrderLine.objects.create(
        order=order_sent,
        position=1,
        product=product,
        name="Болт А-4",
        article="A-4",
        unit="шт",
        quantity=10,
        unit_price=Decimal("150.00"),
    )
    SupplierOrderLog.objects.create(
        order=order_sent,
        kind=OrderLogKind.SENT,
        detail="Отправлен поставщику",
    )

    receipt = GoodsReceipt.objects.create(
        order=order_sent,
        supplier_doc="ТТН-100500",
        note="Приёмка первой партии",
    )
    GoodsReceiptLine.objects.create(
        receipt=receipt,
        order_line=order_sent.lines.first(),
        quantity=5,
        conformity_doc_number="ЕАЭС RU С-RU.АЯ46.В.00001/26",
        conformity_doc_valid_until="2027-12-31",
    )

    order_b = SupplierOrder.objects.create(
        number="ЗП-2026-002",
        number_year=2026,
        number_seq=2,
        supplier=b,
        status=OrderStatus.SENT,
    )

    # Список заказов (GET /partner/orders)
    list_resp = w["client_a"].get(f"{PREFIX}/orders")
    assert list_resp.status_code == 200
    assert_matches(list_resp.json(), "/partner/orders")
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == order_sent.id
    assert items[0]["number"] == "ЗП-2026-001"
    assert items[0]["status"] == "sent"

    # Детали заказа (GET /partner/orders/{id})
    detail_resp = w["client_a"].get(f"{PREFIX}/orders/{order_sent.id}")
    assert detail_resp.status_code == 200
    assert_matches(detail_resp.json(), "/partner/orders/{id}")
    assert detail_resp.json()["id"] == order_sent.id
    assert len(detail_resp.json()["lines"]) == 1
    assert detail_resp.json()["lines"][0]["unit_price"] == "150.00"
    assert len(detail_resp.json()["receipts"]) == 1
    rcpt = detail_resp.json()["receipts"][0]
    assert rcpt["supplier_doc"] == "ТТН-100500"
    assert len(rcpt["lines"]) == 1
    assert rcpt["lines"][0]["quantity"] == 5
    assert rcpt["lines"][0]["conformity_doc_number"] == "ЕАЭС RU С-RU.АЯ46.В.00001/26"
    assert rcpt["lines"][0]["conformity_doc_valid_until"] == "2027-12-31"

    # Чужой заказ — 404
    foreign_resp = w["client_a"].get(f"{PREFIX}/orders/{order_b.id}")
    assert foreign_resp.status_code == 404

    # Подтверждение заказа (POST /partner/orders/{id}/confirm)
    confirm_resp = w["client_a"].post(
        f"{PREFIX}/orders/{order_sent.id}/confirm",
        {"expected_date": "2026-12-01"},
        format="json",
    )
    assert confirm_resp.status_code == 200
    assert_matches(confirm_resp.json(), "/partner/orders/{id}/confirm", "post")
    assert confirm_resp.json()["status"] == "confirmed"
    assert confirm_resp.json()["expected_date"] == "2026-12-01"

    # Уведомление об отгрузке (POST /partner/orders/{id}/ship)
    ship_resp = w["client_a"].post(
        f"{PREFIX}/orders/{order_sent.id}/ship",
        {
            "supplier_doc": "ТОРГ-12-999",
            "carrier": "Деловые Линии",
            "tracking_number": "TRK-123456",
            "note": "Погружено 1 коробка",
        },
        format="json",
    )
    assert ship_resp.status_code == 200
    assert_matches(ship_resp.json(), "/partner/orders/{id}/ship", "post")
    assert any("ТОРГ-12-999" in log["detail"] for log in ship_resp.json()["logs"])

    # 2. Запросы цен (PriceRequest)
    rfq_a = PriceRequest.objects.create(
        supplier=a,
        to_email="north@plant-north.example",
        subject="Запрос цен на крепёж",
        note="Просим дать минимальные сроки",
        status=PriceRequestStatus.SENT,
    )
    PriceRequestLine.objects.create(
        request=rfq_a,
        name="Болт А-4",
        article="A-4",
        quantity=50,
        unit="шт",
    )

    rfq_b = PriceRequest.objects.create(
        supplier=b,
        to_email="south@plant-south.example",
        subject="Запрос цен Юг",
        status=PriceRequestStatus.SENT,
    )

    # Список RFQ (GET /partner/price-requests)
    rfq_list = w["client_a"].get(f"{PREFIX}/price-requests")
    assert rfq_list.status_code == 200
    assert_matches(rfq_list.json(), "/partner/price-requests")
    rfq_items = rfq_list.json()["items"]
    assert len(rfq_items) == 1
    assert rfq_items[0]["id"] == rfq_a.id
    assert rfq_items[0]["status"] == "sent"

    # Детали RFQ (GET /partner/price-requests/{id})
    rfq_detail = w["client_a"].get(f"{PREFIX}/price-requests/{rfq_a.id}")
    assert rfq_detail.status_code == 200
    assert_matches(rfq_detail.json(), "/partner/price-requests/{id}")
    assert rfq_detail.json()["id"] == rfq_a.id
    assert len(rfq_detail.json()["lines"]) == 1

    # Чужой RFQ — 404
    rfq_foreign = w["client_a"].get(f"{PREFIX}/price-requests/{rfq_b.id}")
    assert rfq_foreign.status_code == 404

    # Ответ на RFQ (POST /partner/price-requests/{id}/respond)
    respond_resp = w["client_a"].post(
        f"{PREFIX}/price-requests/{rfq_a.id}/respond",
        {"answer_note": "Готовы отгрузить по 140 руб., срок 5 рабочих дней"},
        format="json",
    )
    assert respond_resp.status_code == 200
    assert_matches(respond_resp.json(), "/partner/price-requests/{id}/respond", "post")
    assert respond_resp.json()["status"] == "answered"
    assert respond_resp.json()["answer_note"] == "Готовы отгрузить по 140 руб., срок 5 рабочих дней"
    assert respond_resp.json()["answered_at"] is not None


def test_partner_product_documents_match_the_contract(partner_world):
    from django.core.files.uploadedfile import SimpleUploadedFile

    w = partner_world
    card = w["cards"]["draft"]
    client_a = w["client_a"]
    client_b = w["client_b"]

    # 1. Загрузка документа multipart/form-data
    test_file = SimpleUploadedFile("cert.pdf", b"%PDF-1.4 test certificate content", content_type="application/pdf")
    upload_resp = client_a.post(
        f"{PREFIX}/products/{card.pk}/documents",
        {
            "file": test_file,
            "title": "Сертификат соответствия ГОСТ",
            "kind": "certificate",
            "number": "ГОСТ-12345",
            "valid_until": "2028-05-15",
        },
        format="multipart",
    )
    assert upload_resp.status_code == 201
    assert_matches(upload_resp.json(), "/partner/products/{id}/documents", "post", "201")
    doc_id = upload_resp.json()["id"]
    assert upload_resp.json()["title"] == "Сертификат соответствия ГОСТ"
    assert upload_resp.json()["number"] == "ГОСТ-12345"

    # 2. Список документов карточки
    list_resp = client_a.get(f"{PREFIX}/products/{card.pk}/documents")
    assert list_resp.status_code == 200
    assert_matches(list_resp.json(), "/partner/products/{id}/documents")
    docs = list_resp.json()
    assert len(docs) == 1
    assert docs[0]["id"] == doc_id

    # 3. Детали товара включают documents
    card_resp = client_a.get(f"{PREFIX}/products/{card.pk}")
    assert card_resp.status_code == 200
    assert_matches(card_resp.json(), "/partner/products/{id}")
    assert len(card_resp.json()["documents"]) == 1
    assert card_resp.json()["documents"][0]["id"] == doc_id

    # 4. Скачивание файла
    file_resp = client_a.get(f"{PREFIX}/products/{card.pk}/documents/{doc_id}/file")
    assert file_resp.status_code == 200
    assert b"".join(file_resp.streaming_content) == b"%PDF-1.4 test certificate content"

    # 5. Чужой партнёр — 404
    foreign_resp = client_b.get(f"{PREFIX}/products/{card.pk}/documents")
    assert foreign_resp.status_code == 404
    foreign_file = client_b.get(f"{PREFIX}/products/{card.pk}/documents/{doc_id}/file")
    assert foreign_file.status_code == 404

    # 6. Удаление документа
    del_resp = client_a.delete(f"{PREFIX}/products/{card.pk}/documents/{doc_id}")
    assert del_resp.status_code == 204

    # Проверка, что удалено
    list_after_del = client_a.get(f"{PREFIX}/products/{card.pk}/documents")
    assert list_after_del.status_code == 200
    assert len(list_after_del.json()) == 0


def test_partner_finance_and_scorecard_match_contract(partner_world):
    """Сводка взаиморасчётов и оценка эффективности партнёра по контракту (K4, K5)."""
    from decimal import Decimal

    from supply.models import (
        GoodsReceipt,
        GoodsReceiptLine,
        OrderStatus,
        PriceRequest,
        PriceRequestStatus,
        SupplierOrder,
        SupplierOrderLine,
    )

    w = partner_world
    a = w["a"]
    product = w["cards"]["published"]

    # Завершённый заказ с приёмкой
    order_completed = SupplierOrder.objects.create(
        number="ЗП-2026-099",
        number_year=2026,
        number_seq=99,
        supplier=a,
        status=OrderStatus.RECEIVED,
        expected_date="2026-11-20",
    )
    line_c = SupplierOrderLine.objects.create(
        order=order_completed,
        position=1,
        product=product,
        name="Болт А-4",
        quantity=20,
        received_quantity=20,
        unit_price=Decimal("120.00"),
    )
    receipt_c = GoodsReceipt.objects.create(
        order=order_completed,
        supplier_doc="ТТН-10099",
    )
    GoodsReceiptLine.objects.create(
        receipt=receipt_c,
        order_line=line_c,
        quantity=20,
    )

    # Запрос цен
    PriceRequest.objects.create(
        supplier=a,
        subject="Запрос цен на крепёж",
        status=PriceRequestStatus.SENT,
        to_email="north@plant-north.example",
    )

    # 1. Сводка партнёра А
    resp = w["client_a"].get(f"{PREFIX}/finance")
    assert resp.status_code == 200
    assert_matches(resp.json(), "/partner/finance")
    data = resp.json()

    assert "balances" in data
    assert "scorecard" in data
    assert "settlements" in data
    assert isinstance(data["balances"], list)
    assert len(data["balances"]) > 0
    bal = data["balances"][0]
    assert bal["currency"]
    assert Decimal(bal["ordered_total"]) >= Decimal(bal["received_total"])

    sc = data["scorecard"]
    assert 0 <= sc["otif_rate"] <= 100
    assert 0 <= sc["rfq_response_rate"] <= 100
    assert 0 <= sc["price_freshness_rate"] <= 100
    assert sc["completed_orders_count"] >= 1

    settlements = data["settlements"]
    assert len(settlements) >= 1
    st = settlements[0]
    assert "order_id" in st
    assert "order_number" in st
    assert "status" in st
    assert "receipts_count" in st

    # 2. Сводка партнёра Б
    resp_b = w["client_b"].get(f"{PREFIX}/finance")
    assert resp_b.status_code == 200
    assert_matches(resp_b.json(), "/partner/finance")
