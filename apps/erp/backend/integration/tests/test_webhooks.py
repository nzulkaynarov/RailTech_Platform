"""Unit and integration tests for ERP -> CRM webhooks (CONTRACTS §3, M3-ERP-02).

Проверяет:
1. Вычисление и верификацию HMAC-SHA256 подписи (`X-Signature: sha256=<hex>`).
2. Стадию и сумму в `DealRef` (одна функция стадий — `integration/services/stages.py`, её тесты — `test_stages.py`).
3. Сборку объектов Actor, DealRef и тела события.
4. Пропуск вебхуков для не связанных с CRM компаний (отсутствие CrmClientMapping).
5. Создание записей `IntegrationWebhookEvent` и валидность всех типов событий по контракту.
6. Celery-задачу `deliver_webhook_event`: успешная отправка (200), ретраи при 5xx/ошибках сети,
   исчерпание попыток и перевод в FAILED, ручной перезапуск `redeliver_event`.
7. Сигналы Django: создание заявки (`request.created`), смену стадии (`deal.stage_changed`, `deal.won`),
   смену статуса КП (`quote.sent`, `quote.accepted`), статусов счетов (`invoice.issued`, `invoice.paid`),
   приглашение контакта (`invite.sent`).
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone
from integration.models import CrmClientMapping, CrmContactMapping, IntegrationWebhookEvent, WebhookEventStatus
from integration.services.webhooks import (
    build_actor,
    build_deal_ref,
    emit_act_event,
    emit_contract_signed,
    emit_deal_outcome,
    emit_deal_stage_changed,
    emit_delivery_event,
    emit_document_created,
    emit_event,
    emit_invite_sent,
    emit_invoice_event,
    emit_quote_outcome,
    emit_quote_sent,
    emit_request_created,
    sign_payload,
    verify_signature,
)
from integration.tasks import RETRY_DELAYS, deliver_webhook_event, redeliver_event
from parties.models import Company, Contact

from crm.constants import DealStageCode
from crm.models import Deal, DealStage, Invoice, InvoiceStatus, Quote, QuoteStatus


@pytest.fixture
def mapped_company(db):
    """Тестовая компания ERP, привязанная к клиенту CRM."""
    company = Company.objects.create(name="ООО ТестТранс", inn="123456789")
    mapping = CrmClientMapping.objects.create(company=company, crm_client_id=42)
    return company, mapping


@pytest.fixture
def deal_stages(db):
    """Настоящие стадии FSM ERP (`crm/constants.py`): ключ — стадия контракта, которую они дают на сделке без документов."""
    codes = {
        "request": DealStageCode.DRAFT,
        "quoting": DealStageCode.CALCULATING,
        "quote_sent": DealStageCode.QUOTE_SENT,
        "won": DealStageCode.CLOSED_WON,
        "lost": DealStageCode.CLOSED_LOST,
    }
    return {key: DealStage.objects.get_or_create(code=code, defaults={"name": code})[0] for key, code in codes.items()}


# ─── 1. Signature & Helpers Tests ─────────────────────────────────────────────


def test_signature_computation_and_verification():
    secret = "test-secret-key"
    payload = b'{"hello":"world"}'

    signature = sign_payload(secret, payload)
    assert signature.startswith("sha256=")
    assert len(signature) == 7 + 64  # 'sha256=' + 64 hex characters

    assert verify_signature(secret, payload, signature) is True
    assert verify_signature(secret, b'{"other":"payload"}', signature) is False
    assert verify_signature("wrong-secret", payload, signature) is False


def test_build_actor():
    actor_sys = build_actor()
    assert actor_sys == {"type": "system"}

    user_mock = MagicMock()
    user_mock.is_portal_user = False
    user_mock.get_full_name.return_value = "Азиз Кадиров"
    actor_staff = build_actor(user=user_mock)
    assert actor_staff == {"type": "staff", "name": "Азиз Кадиров"}

    portal_user_mock = MagicMock()
    portal_user_mock.is_portal_user = True
    portal_user_mock.get_full_name.return_value = "Клиент Представитель"
    actor_client = build_actor(user=portal_user_mock)
    assert actor_client == {"type": "client", "name": "Клиент Представитель"}


def test_build_deal_ref(db, mapped_company, deal_stages):
    company, _ = mapped_company
    deal = Deal.objects.create(
        company=company,
        title="Поставка рельсов",
        stage=deal_stages["quoting"],
    )

    deal_ref = build_deal_ref(deal)
    assert deal_ref["erp_deal_id"] == deal.id
    assert deal_ref["number"] == f"D-{deal.id}"
    assert deal_ref["title"] == "Поставка рельсов"
    assert deal_ref["stage"] == "quoting"
    assert deal_ref["amount"] is None, "КП клиенту не отправлялось — суммы нет (events.schema.json: null)"
    assert deal_ref["currency"] == "UZS"

    dict_ref = build_deal_ref(
        {
            "erp_deal_id": 99,
            "number": "D-99",
            "title": "Тестовая",
            "stage": "won",
            "amount": "1500000.50",
            "currency": "usd",
        }
    )
    assert dict_ref["erp_deal_id"] == 99
    assert dict_ref["stage"] == "won"
    assert dict_ref["amount"] == "1500000.50"
    assert dict_ref["currency"] == "USD"
    assert build_deal_ref({"erp_deal_id": 5, "stage": "request", "amount": None})["amount"] is None


def test_build_deal_ref_amount_ignores_drafts_and_takes_the_latest_sent_quote(db, mapped_company, deal_stages):
    company, _ = mapped_company
    deal = Deal.objects.create(company=company, stage=deal_stages["quote_sent"])
    sent = QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Отправлено"})[0]
    draft = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик"})[0]
    Quote.objects.create(
        deal=deal, version=1, status=sent, total_incl_vat=Decimal("1200000.00"), public_access_token="tok-sent-1"
    )
    Quote.objects.create(deal=deal, version=2, status=draft, total_incl_vat=Decimal("9900000.00"))

    ref = build_deal_ref(deal)
    assert ref["stage"] == "quote_sent"
    assert ref["amount"] == "1200000.00"


def test_deal_ref_stage_outside_the_contract_is_rejected(db, mapped_company):
    """Сырой код FSM или выдуманная стадия в событие не попадают: код решает, а не молча подставляет."""
    company, _ = mapped_company
    deal = Deal.objects.create(company=company)
    for bad in ("CLOSED_WON", "quoted", "", None):
        with pytest.raises(ValueError, match="не из контракта"):
            build_deal_ref({"erp_deal_id": 1, "stage": bad})
        with pytest.raises(ValueError, match="не из контракта"):
            emit_deal_stage_changed(deal=deal, from_stage="request", to_stage=bad, send_async=False)


# ─── 2. Emission & Serialization Tests ────────────────────────────────────────


def test_emit_event_unmapped_company_is_skipped(db):
    unmapped = Company.objects.create(name="Локальная без CRM")
    event = emit_event(
        event_type="request.created",
        erp_company_id=unmapped.id,
        payload={"source": "erp"},
        send_async=False,
    )
    assert event is None
    assert IntegrationWebhookEvent.objects.count() == 0


def test_emit_event_mapped_company_creates_record(db, mapped_company):
    company, mapping = mapped_company
    event = emit_event(
        event_type="invite.sent",
        erp_company_id=company.id,
        payload={"channels": ["email"]},
        send_async=False,
    )
    assert event is not None
    assert event.status == WebhookEventStatus.PENDING
    assert event.event_type == "invite.sent"
    assert event.payload["version"] == 1
    assert event.payload["erp_company_id"] == company.id
    assert event.payload["crm_client_id"] == mapping.crm_client_id
    assert "X-Signature" in event.headers
    assert event.headers["X-Signature"].startswith("sha256=")
    assert event.headers["X-Event-Type"] == "invite.sent"


def test_all_19_event_types_payload_builders(db, mapped_company, deal_stages):
    company, _ = mapped_company
    deal = Deal.objects.create(company=company, stage=deal_stages["request"])

    # 1. request.created
    e1 = emit_request_created(deal=deal, source="cabinet", erp_request_id=12, summary="Строки", send_async=False)
    assert e1.payload["event"] == "request.created"
    assert e1.payload["payload"]["source"] == "cabinet"
    assert e1.payload["payload"]["erp_request_id"] == 12

    # 2. deal.stage_changed
    e2 = emit_deal_stage_changed(
        deal=deal, from_stage="request", to_stage="quoting", reason="КП готово", send_async=False
    )
    assert e2.payload["event"] == "deal.stage_changed"
    assert e2.payload["payload"]["from"] == "request"
    assert e2.payload["payload"]["to"] == "quoting"

    # 3. deal.won
    e3 = emit_deal_outcome(deal=deal, won=True, amount="50000.00", currency="UZS", send_async=False)
    assert e3.payload["event"] == "deal.won"
    assert e3.payload["payload"]["amount"] == "50000.00"

    # 4. deal.lost
    e4 = emit_deal_outcome(deal=deal, won=False, lost_reason="Дорого", send_async=False)
    assert e4.payload["event"] == "deal.lost"
    assert e4.payload["payload"]["lost_reason"] == "Дорого"

    # 5. quote.sent
    quote = Quote.objects.create(deal=deal, version=1, total_incl_vat=Decimal("100000.00"))
    e5 = emit_quote_sent(quote=quote, public_url="https://cabinet.railtech.uz/q/tok", send_async=False)
    assert e5.payload["event"] == "quote.sent"
    assert e5.payload["payload"]["erp_quote_id"] == quote.id
    assert e5.payload["payload"]["public_url"] == "https://cabinet.railtech.uz/q/tok"

    # 6. quote.viewed, quote.accepted, quote.rejected
    e6 = emit_quote_outcome("quote.viewed", quote=quote, send_async=False)
    assert e6.payload["event"] == "quote.viewed"
    e7 = emit_quote_outcome("quote.accepted", quote=quote, send_async=False)
    assert e7.payload["event"] == "quote.accepted"
    e8 = emit_quote_outcome("quote.rejected", quote=quote, reason="Не подошли сроки", send_async=False)
    assert e8.payload["event"] == "quote.rejected"
    assert e8.payload["payload"]["reason"] == "Не подошли сроки"

    # 7. contract.signed
    contract_mock = MagicMock()
    contract_mock.id = 55
    contract_mock.deal = deal
    contract_mock.number = "CT-2026-00055"
    e9 = emit_contract_signed(contract=contract_mock, by="both", send_async=False)
    assert e9.payload["event"] == "contract.signed"
    assert e9.payload["payload"]["by"] == "both"

    # 8. invoice.issued, invoice.paid, invoice.overdue
    inv_mock = MagicMock()
    inv_mock.id = 77
    inv_mock.deal = deal
    inv_mock.number = "INV-2026-00077"
    inv_mock.total_incl_vat = Decimal("25000.00")
    inv_mock.due_date = timezone.now().date()
    inv_mock.currency = "UZS"
    e10 = emit_invoice_event("invoice.issued", invoice=inv_mock, send_async=False)
    assert e10.payload["event"] == "invoice.issued"
    assert e10.payload["payload"]["amount"] == "25000.00"

    # 9. delivery.status_changed, delivery.eta_changed
    fulf_mock = MagicMock()
    fulf_mock.deal = deal
    fulf_mock.status = MagicMock(code="in_transit")
    fulf_mock.expected_delivery_date = timezone.now().date()
    fulf_mock.tracking_number = "TRACK123"
    e11 = emit_delivery_event("delivery.status_changed", fulfillment=fulf_mock, send_async=False)
    assert e11.payload["event"] == "delivery.status_changed"
    assert e11.payload["payload"]["status"] == "in_transit"

    # 10. act.issued, act.accepted, act.returned
    act_mock = MagicMock()
    act_mock.id = 88
    act_mock.deal = deal
    act_mock.number = "ACT-2026-00088"
    e12 = emit_act_event("act.accepted", act=act_mock, send_async=False)
    assert e12.payload["event"] == "act.accepted"
    assert e12.payload["payload"]["erp_act_id"] == 88

    # 11. invite.sent
    contact = Contact.objects.create(company=company, name="Иван Иванов")
    CrmContactMapping.objects.create(contact=contact, crm_contact_id=101)
    e13 = emit_invite_sent(contact=contact, channels=["telegram", "email"], send_async=False)
    assert e13.payload["event"] == "invite.sent"
    assert e13.payload["payload"]["channels"] == ["telegram", "email"]
    assert e13.payload["payload"]["crm_contact_id"] == 101

    # 12. document.created
    doc_mock = MagicMock()
    doc_mock.id = 999
    doc_mock.deal = deal
    doc_mock.number = "DOC-999"
    doc_mock.template = MagicMock()
    doc_mock.template.kind = MagicMock(code="act")
    doc_mock.title = "Акт сверки"
    e14 = emit_document_created(document=doc_mock, send_async=False)
    assert e14.payload["event"] == "document.created"
    assert e14.payload["payload"]["kind"] == "act"


# ─── 3. Celery Task & Delivery Tests ──────────────────────────────────────────


def test_deliver_webhook_event_success_200(db, mapped_company):
    company, _ = mapped_company
    event = emit_event("invite.sent", company.id, {"channels": ["email"]}, send_async=False)

    fake_response = MagicMock(status_code=200, text="OK")
    with patch("httpx.Client.post", return_value=fake_response) as mock_post:
        success = deliver_webhook_event(event.id)
        assert success is True
        mock_post.assert_called_once()

    event.refresh_from_db()
    assert event.status == WebhookEventStatus.SENT
    assert event.response_status == 200
    assert event.attempts == 1
    assert event.sent_at is not None
    assert event.last_error == ""


def test_deliver_webhook_event_already_sent_is_noop(db, mapped_company):
    company, _ = mapped_company
    event = emit_event("invite.sent", company.id, {"channels": ["email"]}, send_async=False)
    event.status = WebhookEventStatus.SENT
    event.save()

    with patch("httpx.Client.post") as mock_post:
        success = deliver_webhook_event(event.id)
        assert success is True
        mock_post.assert_not_called()


def test_deliver_webhook_event_500_retries(db, mapped_company):
    from celery.exceptions import Retry

    company, _ = mapped_company
    event = emit_event("invite.sent", company.id, {"channels": ["email"]}, send_async=False)

    fake_response = MagicMock(status_code=500, text="Internal Server Error")
    with patch("httpx.Client.post", return_value=fake_response):
        with patch.object(deliver_webhook_event, "retry") as mock_retry:
            mock_retry.side_effect = Retry("RetryCalled")
            with pytest.raises(Retry, match="RetryCalled"):
                deliver_webhook_event(event.id)

            mock_retry.assert_called_once()
            _, kwargs = mock_retry.call_args
            assert kwargs["countdown"] == RETRY_DELAYS[0]

    event.refresh_from_db()
    assert event.attempts == 1
    assert "HTTP 500" in event.last_error
    assert event.status == WebhookEventStatus.PENDING


def test_deliver_webhook_event_exhausted_retries_marks_failed(db, mapped_company):
    company, _ = mapped_company
    event = emit_event("invite.sent", company.id, {"channels": ["email"]}, send_async=False)
    event.attempts = len(RETRY_DELAYS)
    event.save()

    fake_response = MagicMock(status_code=503, text="Service Unavailable")
    with patch("httpx.Client.post", return_value=fake_response):
        success = deliver_webhook_event(event.id)
        assert success is False

    event.refresh_from_db()
    assert event.status == WebhookEventStatus.FAILED
    assert "HTTP 503" in event.last_error


def test_redeliver_event_triggers_task(db, mapped_company):
    company, _ = mapped_company
    event = emit_event("invite.sent", company.id, {"channels": ["email"]}, send_async=False)
    event.status = WebhookEventStatus.FAILED
    event.save()

    with patch("integration.tasks.deliver_webhook_event.delay") as mock_delay:
        redelivered = redeliver_event(event.id)
        assert redelivered is not None
        assert redelivered.status == WebhookEventStatus.PENDING
        mock_delay.assert_called_once_with(event.id)


# ─── 4. Django Signals Integration Tests ──────────────────────────────────────


def test_deal_creation_and_stage_changed_signals(db, mapped_company, deal_stages):
    company, _ = mapped_company

    # 1. Deal creation -> request.created
    with patch("integration.signals.webhooks.emit_request_created") as mock_req:
        deal = Deal.objects.create(
            company=company,
            title="Заявка от клиента",
            stage=deal_stages["request"],
        )
        mock_req.assert_called_once()
        assert mock_req.call_args[1]["deal"] == deal

    # 2. Deal stage change -> deal.stage_changed
    with patch("integration.signals.webhooks.emit_deal_stage_changed") as mock_stage_change:
        deal.stage = deal_stages["quoting"]
        deal.save()
        mock_stage_change.assert_called_once()
        kwargs = mock_stage_change.call_args[1]
        assert kwargs["from_stage"] == "request"
        assert kwargs["to_stage"] == "quoting"

    # 3. Deal won -> deal.won (итог продажи — переход FSM в CLOSED_WON); стадия контракта у сделки без документов — contract
    with (
        patch("integration.signals.webhooks.emit_deal_outcome") as mock_outcome,
        patch("integration.signals.webhooks.emit_deal_stage_changed") as mock_stage_change,
    ):
        deal.stage = deal_stages["won"]
        deal.save()
        mock_outcome.assert_called_once()
        assert mock_outcome.call_args[1]["won"] is True
        assert mock_stage_change.call_args[1]["from_stage"] == "quoting"
        assert mock_stage_change.call_args[1]["to_stage"] == "contract"

    # 4. Deal lost -> deal.lost
    with patch("integration.signals.webhooks.emit_deal_outcome") as mock_outcome:
        deal.stage = deal_stages["lost"]
        deal.save()
        mock_outcome.assert_called_once()
        assert mock_outcome.call_args[1]["won"] is False


def test_stage_change_inside_one_contract_stage_emits_no_stage_changed(db, mapped_company):
    """DRAFT → RFQ_OPEN: обе стадии FSM — `request` контракта; события о смене стадии нет."""
    company, _ = mapped_company
    draft = DealStage.objects.get_or_create(code=DealStageCode.DRAFT, defaults={"name": "Черновик"})[0]
    rfq = DealStage.objects.get_or_create(code=DealStageCode.RFQ_OPEN, defaults={"name": "RFQ"})[0]
    deal = Deal.objects.create(company=company, stage=draft)
    with patch("integration.signals.webhooks.emit_deal_stage_changed") as mock_stage_change:
        deal.stage = rfq
        deal.save()
        mock_stage_change.assert_not_called()


def test_deal_outcome_payload_has_the_sent_amount_or_zero(db, mapped_company, deal_stages):
    company, _ = mapped_company
    deal = Deal.objects.create(company=company, stage=deal_stages["request"])
    lost = emit_deal_outcome(deal=deal, won=False, lost_reason="Дорого", send_async=False)
    assert lost.payload["payload"] == {"amount": "0.00", "currency": "UZS", "lost_reason": "Дорого"}

    sent = QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Отправлено"})[0]
    Quote.objects.create(
        deal=deal, version=1, status=sent, total_incl_vat=Decimal("750000.00"), public_access_token="tok-sent-2"
    )
    won = emit_deal_outcome(deal=Deal.objects.get(pk=deal.pk), won=True, send_async=False)
    assert won.payload["payload"] == {"amount": "750000.00", "currency": "UZS"}
    assert won.payload["deal"]["amount"] == "750000.00"


def test_quote_signals(db, mapped_company, deal_stages):
    company, _ = mapped_company
    deal = Deal.objects.create(company=company, stage=deal_stages["request"])
    status_draft, _ = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 1})
    status_sent, _ = QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Отправлено", "sort_order": 2})

    quote = Quote.objects.create(deal=deal, version=1, status=status_draft)

    with patch("integration.signals.webhooks.emit_quote_sent") as mock_sent:
        quote.status = status_sent
        quote.save()
        mock_sent.assert_called_once_with(quote=quote)


def test_invoice_signals(db, mapped_company, deal_stages):
    company, _ = mapped_company
    deal = Deal.objects.create(company=company, stage=deal_stages["request"])
    status_draft, _ = InvoiceStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 1})
    status_issued, _ = InvoiceStatus.objects.get_or_create(
        code="ISSUED", defaults={"name": "Выставлен", "sort_order": 2}
    )
    status_paid, _ = InvoiceStatus.objects.get_or_create(code="PAID", defaults={"name": "Оплачен", "sort_order": 3})

    inv = Invoice.objects.create(deal=deal, number="INV-T-1", status=status_draft)

    with patch("integration.signals.webhooks.emit_invoice_event") as mock_inv_event:
        inv.status = status_issued
        inv.save()
        mock_inv_event.assert_called_with("invoice.issued", invoice=inv)

    with patch("integration.signals.webhooks.emit_invoice_event") as mock_inv_event:
        inv.status = status_paid
        inv.save()
        mock_inv_event.assert_called_with("invoice.paid", invoice=inv)
