"""End-to-end lifecycle integration test for the Portal API (/api/portal/v1/*).

Verifies the entire client journey:
Upload specification -> Create request with lines -> View request card ->
Receive Quote -> View Quote details (sanitized, no margin/cost) -> Accept Quote ->
Contract auto-generated -> Client signs contract ->
Invoice issued -> Act issued -> Client accepts Act ->
Catalog browsing (sanitized) -> Company profile edit -> Team invitation.
"""

import datetime
import uuid
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from parties.models import Contact
from portal.tests.conftest import issue_test_acceptance_code
from rest_framework import status

from catalog.models import Category, Product, ProductStatus
from crm.constants import ActStatusCode, ContractStatusCode, DealStageCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import (
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteItem,
    QuoteStatus,
)


@pytest.fixture
def catalog_products(db):
    from core.models import Currency

    curr_uzs, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Узбекский сум", "symbol": "so'm"})
    cat, _ = Category.objects.get_or_create(name="Трубы и фитинги")
    published_status, _ = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Опубликован"})
    draft_status, _ = ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик"})

    p1 = Product.objects.create(
        name="Труба 89х4 ст20",
        sku="PIPE-89-4",
        category=cat,
        status=published_status,
        list_price=Decimal("450000"),
        list_price_currency=curr_uzs,
    )
    p2 = Product.objects.create(
        name="Секретная деталь (черновик)",
        sku="DRAFT-001",
        category=cat,
        status=draft_status,
    )
    return {"published": p1, "draft": p2, "category": cat}


@pytest.mark.django_db
class TestPortalEndToEndLifecycle:
    def test_full_portal_cycle(self, portal_client, client_company, client_contact, catalog_products):
        # ── 1. Загрузка файла спецификации (Q-14) ──────────────────────────
        file_content = b"Mock PDF specification content for steel pipes"
        uploaded_file = SimpleUploadedFile("specification.pdf", file_content, content_type="application/pdf")

        upload_resp = portal_client.post(
            "/api/portal/v1/uploads",
            {"file": uploaded_file},
            format="multipart",
        )
        assert upload_resp.status_code == status.HTTP_201_CREATED
        upload_data = upload_resp.data
        assert "upload_id" in upload_data
        assert upload_data["name"] == "specification.pdf"
        assert upload_data["mime_type"] == "application/pdf"
        upload_id = upload_data["upload_id"]

        # ── 2. Создание запроса клиентом со строками и файлом ──────────────
        req_resp = portal_client.post(
            "/api/portal/v1/requests",
            {
                "summary": "Поставка стальных труб 89х4",
                "lines": [
                    {"text": "Труба 89х4 ст20 ГОСТ 8732", "quantity": "150", "unit": "м"},
                    {"text": "Отвод 89х4 90 градусов", "quantity": "10", "unit": "шт"},
                ],
                "attachments": [{"upload_id": upload_id, "name": "specification.pdf"}],
            },
            format="json",
        )
        assert req_resp.status_code == status.HTTP_201_CREATED
        req_data = req_resp.data
        deal_id = req_data["id"]  # запрос и сделка — одна запись; `deal` пуст, пока по запросу ничего не произошло
        assert req_data["status"] == "new" and req_data["deal"] is None and req_data["deal_id"] is None
        assert req_data["source"] == "cabinet"
        assert req_data["summary"] == "Поставка стальных труб 89х4"

        # ── 3. Просмотр карточки запроса (Q-16) ────────────────────────────
        detail_resp = portal_client.get(f"/api/portal/v1/requests/{deal_id}")
        assert detail_resp.status_code == status.HTTP_200_OK
        detail_data = detail_resp.data
        assert len(detail_data["lines"]) == 2
        assert detail_data["lines"][0]["text"] == "Труба 89х4 ст20 ГОСТ 8732"
        assert detail_data["lines"][0]["quantity"] == "150"
        assert len(detail_data["attachments"]) == 1
        assert detail_data["attachments"][0]["upload_id"] == upload_id

        # ── 4. Менеджер бэк-офиса готовит и отправляет КП ──────────────────
        deal = Deal.objects.get(pk=deal_id)
        quote_sent_stage, _ = DealStage.objects.get_or_create(
            code=DealStageCode.QUOTE_SENT, defaults={"name": "КП отправлено"}
        )
        deal.stage = quote_sent_stage
        deal.save(update_fields=["stage"])

        sent_status, _ = QuoteStatus.objects.get_or_create(code=QuoteStatusCode.SENT, defaults={"name": "Отправлено"})
        from core.models import Currency

        curr_uzs, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Узбекский сум", "symbol": "so'm"})
        quote = Quote.objects.create(
            public_access_token=uuid.uuid4().hex,
            deal=deal,
            version=1,
            status=sent_status,
            total_incl_vat=Decimal("75000000"),
            quote_currency=curr_uzs,
        )
        QuoteItem.objects.create(
            quote=quote,
            imported_raw_name="Труба 89х4 ст20 ГОСТ 8732",
            quantity=150,
            frozen_base_price=Decimal("500000"),
            margin_percent=Decimal("0"),
        )

        # ── 5. Клиент видит КП и просматривает детали ──────────────────────
        q_list_resp = portal_client.get("/api/portal/v1/quotes")
        assert q_list_resp.status_code == status.HTTP_200_OK
        assert any(q["id"] == quote.id for q in q_list_resp.data)

        q_detail_resp = portal_client.get(f"/api/portal/v1/quotes/{quote.id}")
        assert q_detail_resp.status_code == status.HTTP_200_OK
        q_data = q_detail_resp.data
        assert q_data["id"] == quote.id
        assert q_data["total"] == {"amount": "84000000.00", "currency": "UZS"}
        assert "items" not in q_data and "vat_rate" not in q_data  # внутренний слой клиенту не отдаётся
        items = q_data["lines"]
        assert len(items) == 1
        # Проверяем санитацию: себестоимость, наценка и НДС строки НЕ попадают в ответ клиенту
        item_data = items[0]
        assert set(item_data) == {
            "line_no",
            "kind",
            "title",
            "description",
            "quantity",
            "unit",
            "unit_price",
            "total",
            "promised_date",
        }
        assert item_data["kind"] == "item" and item_data["title"] == "Труба 89х4 ст20 ГОСТ 8732"
        assert item_data["unit_price"] == {"amount": "500000.00", "currency": "UZS"}
        assert item_data["total"] == {"amount": "75000000.00", "currency": "UZS"}

        # ── 6. Клиент акцептует КП одноразовым кодом из письма ──────────────
        code = issue_test_acceptance_code(quote, client_contact.email)
        accept_resp = portal_client.post(
            f"/api/portal/v1/quotes/{quote.id}/accept",
            {"code": code},
            format="json",
        )
        assert accept_resp.status_code == status.HTTP_200_OK
        assert accept_resp.data["status"] in ("accepted", "approved")

        # Проверяем состояние в БД: сделка CONTRACT_SIGNED, создан контракт
        deal.refresh_from_db()
        assert deal.stage.code == DealStageCode.CONTRACT_SIGNED
        contract = Contract.objects.filter(deal=deal).first()
        assert contract is not None

        # ── 7. Клиент просматривает и подписывает контракт ─────────────────
        contract_status_sent, _ = ContractStatus.objects.get_or_create(
            code=ContractStatusCode.PENDING_CLIENT, defaults={"name": "На подписи"}
        )
        contract.status = contract_status_sent
        contract.save(update_fields=["status"])

        contracts_resp = portal_client.get("/api/portal/v1/contracts")
        assert contracts_resp.status_code == status.HTTP_200_OK
        assert any(c["id"] == contract.id for c in contracts_resp.data)

        sign_resp = portal_client.post(f"/api/portal/v1/contracts/{contract.id}/sign", format="json")
        assert sign_resp.status_code == status.HTTP_200_OK
        contract.refresh_from_db()
        assert (
            contract.client_signer is not None
            or getattr(contract, "client_signed_at", None) is not None
            or getattr(contract, "signed_at", None) is not None
        )

        # ── 8. Счёт на оплату и Акт ─────────────────────────────────────────
        inv_issued, _ = InvoiceStatus.objects.get_or_create(
            code=InvoiceStatusCode.ISSUED, defaults={"name": "Выставлен"}
        )
        invoice = Invoice.objects.create(
            issued_at=datetime.date.today(),
            deal=deal,
            contract=contract,
            number="INV-2026-PORTAL-01",
            status=inv_issued,
            total_incl_vat=Decimal("75000000"),
        )
        inv_resp = portal_client.get("/api/portal/v1/invoices")
        assert inv_resp.status_code == status.HTTP_200_OK
        assert any(inv["id"] == invoice.id for inv in inv_resp.data)

        act_issued, _ = ActStatus.objects.get_or_create(code=ActStatusCode.ISSUED, defaults={"name": "Выставлен"})
        act = Act.objects.create(
            deal=deal,
            contract=contract,
            invoice=invoice,
            number="ACT-2026-PORTAL-01",
            status=act_issued,
            total_amount=Decimal("75000000"),
        )

        acts_resp = portal_client.get("/api/portal/v1/acts")
        assert acts_resp.status_code == status.HTTP_200_OK
        assert any(a["id"] == act.id for a in acts_resp.data)

        # Клиент принимает акт
        act_accept_resp = portal_client.post(f"/api/portal/v1/acts/{act.id}/accept", format="json")
        assert act_accept_resp.status_code == status.HTTP_200_OK
        assert act_accept_resp.data["status"] == "accepted"  # контракт 0.2.0: issued|accepted|returned
        act.refresh_from_db()
        assert act.status.code == ActStatusCode.SIGNED

        # ── 9. Каталог продукции и категории (Q-15) ────────────────────────
        cat_resp = portal_client.get("/api/portal/v1/catalog/categories")
        assert cat_resp.status_code == status.HTTP_200_OK
        assert len(cat_resp.data) >= 1
        assert any(c["name"] == "Трубы и фитинги" for c in cat_resp.data)

        catalog_resp = portal_client.get("/api/portal/v1/catalog")
        assert catalog_resp.status_code == status.HTTP_200_OK
        catalog_items = catalog_resp.data["items"]
        names = [item["name"] for item in catalog_items]
        assert "Труба 89х4 ст20" in names
        assert "Секретная деталь (черновик)" not in names  # неопубликованный товар скрыт

        # ── 10. Профиль компании и приглашение в команду ───────────────────
        company_resp = portal_client.get("/api/portal/v1/company")
        assert company_resp.status_code == status.HTTP_200_OK
        assert company_resp.data["name"] == client_company.name

        update_comp_resp = portal_client.put(
            "/api/portal/v1/company",
            {"bank_details": "р/с 20208000999988887777 в НБУ", "language": "uz"},
            format="json",
        )
        assert update_comp_resp.status_code == status.HTTP_200_OK
        assert update_comp_resp.data["bank_details"] == "р/с 20208000999988887777 в НБУ"
        assert update_comp_resp.data["language"] == "uz"

        # Приглашение коллеги
        invite_resp = portal_client.post(
            "/api/portal/v1/team/invite",
            {
                "name": "Dilshod Teammate",
                "email": "dilshod.team@example.uz",
                "phone": "+998901112233",
                "language": "ru",
                "can_act": True,
                "channels": ["email"],
            },
            format="json",
        )
        assert invite_resp.status_code == status.HTTP_201_CREATED
        assert Contact.objects.filter(email="dilshod.team@example.uz", company=client_company).exists()
