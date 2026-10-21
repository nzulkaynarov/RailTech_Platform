"""Контрактные тесты событий ERP → CRM: каждое из 22 событий проверяется по `events.schema.json` (FIX-35, I-15, G-5).

Источник правды — файлы контракта: схема `packages/contracts/events.schema.json` и примеры
`packages/contracts/examples/events/<тип>.json` (по одному на тип; те же примеры — фикстуры тестов CRM). Здесь нет копий
списка типов и полей. Проверяется:

1. набор типов = схема = `VALID_EVENT_TYPES` = набор примеров; каждый пример проходит схему, а сторож её ловит (негатив);
2. конвейер отправки (`emit_event`) принимает тело каждого примера и сохраняет его без изменений;
3. боевой код (настоящие объекты, сигналы и сервисы, а не заглушки) выпускает все 22 типа, и каждое тело — по схеме;
4. режимы проверки в рантайме: `strict` — исключение и нет записи в журнале, `log` — запись и сообщение в лог, `off`;
5. подпись: подписывает первый секрет списка (ротация без простоя).
"""

from __future__ import annotations

import json
import logging

import pytest
from integration.models import CrmContactMapping, IntegrationWebhookEvent
from integration.services import event_contract
from integration.services.event_contract import EventContractError
from integration.services.webhooks import (
    SECRET_MASK,
    SECRET_PAYLOAD_FIELDS,
    VALID_EVENT_TYPES,
    delivery_payload,
    emit_act_event,
    emit_event,
    emit_invite_sent,
    sign_payload,
    webhook_signing_secret,
)
from integration.tests.world import (
    add_act,
    add_contract,
    add_fulfillment,
    add_invoice,
    add_order_quote,
    add_quote,
    make_company,
    make_deal,
)
from parties.models import Contact
from portal.services.acceptance import request_acceptance_code
from portal.services.documents import encode_document_id
from sales.models import DeliveryLine
from sales.services.delivery_lines import accept_delivery_line, dispute_delivery_line, sync_delivery_lines

from core.tests.events_contract import event_errors, event_types, example_event, example_files, find_events_schema_path
from crm.constants import ActStatusCode, ContractStatusCode, FulfillmentStatusCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import ActStatus, ContractStatus, DealStage, InvoiceStatus, QuoteStatus

pytestmark = pytest.mark.django_db

ALL_EVENTS = event_types()


# ── 1. Набор типов, примеры и сторож ─────────────────────────────────────────────────────────────────


def test_schema_is_found_and_has_22_event_types():
    assert find_events_schema_path().is_file()
    assert len(ALL_EVENTS) == 22


def test_event_types_of_schema_code_and_examples_are_the_same_set():
    assert set(ALL_EVENTS) == set(VALID_EVENT_TYPES), "типы в events.schema.json и в VALID_EVENT_TYPES разошлись"
    assert set(example_files()) == set(
        ALL_EVENTS
    ), "на каждое событие контракта нужен ровно один пример в examples/events"


@pytest.mark.parametrize("event", ALL_EVENTS)
def test_every_example_matches_the_schema_and_its_own_event(event):
    body = example_event(event)
    assert event_errors(body) == []
    assert body["event"] == event


def test_guard_detects_a_broken_event():
    good = example_event("invoice.issued")
    assert event_errors(good) == []

    def broken(**changes):
        return event_errors({**good, **changes})

    assert broken(event="invoice.unknown"), "тип не из контракта"
    assert broken(occurred_at="2026-10-17T09:00:00"), "время без часового пояса"
    assert broken(deal={**good["deal"], "stage": "CLOSED_WON"}), "сырая стадия FSM вместо DealStage"
    assert broken(deal={**good["deal"], "amount": "125000000"}), "сумма без копеек"
    assert broken(payload={**good["payload"], "internal_margin": "1.00"}), "лишний ключ"
    assert broken(payload={k: v for k, v in good["payload"].items() if k != "due_date"}), "нет обязательного поля"
    assert broken(payload={**good["payload"], "link": "не ссылка"}), "ссылка не URI"
    no_deal = {k: v for k, v in good.items() if k != "deal"}
    assert event_errors(no_deal), "счёт без сделки"
    assert event_errors({k: v for k, v in good.items() if k != "actor"})


# ── 2. Конвейер отправки принимает и не искажает тело каждого примера ─────────────────────────────────


@pytest.mark.parametrize("event", ALL_EVENTS)
def test_emit_event_stores_the_example_body_unchanged(event):
    company = make_company(crm_client_id=42)
    body = example_event(event)
    stored = emit_event(
        event_type=event,
        erp_company_id=company.pk,
        payload=body["payload"],
        deal=body.get("deal"),
        actor=body["actor"],
        occurred_at=body["occurred_at"],
        crm_client_id=42,
        send_async=False,
    )
    expected = {**body, "erp_company_id": company.pk}
    if event in SECRET_PAYLOAD_FIELDS:  # секрет (код акцепта) в журнале замаскирован, тело доставки — как в примере
        for name in SECRET_PAYLOAD_FIELDS[event]:
            expected = {**expected, "payload": {**expected["payload"], name: SECRET_MASK}}
        assert delivery_payload(stored) == {**body, "erp_company_id": company.pk}
    assert stored.payload == expected, "тело события в журнале расходится с примером контракта"
    assert stored.event_type == event and stored.headers["X-Event-Type"] == event
    assert not event_errors(delivery_payload(stored))


# ── 3. Боевой код выпускает все 22 типа ───────────────────────────────────────────────────────────────


def _status(model, code):
    return model.objects.get_or_create(code=code, defaults={"name": code})[0]


def produce_all_events():
    """Один сценарий на настоящих объектах: сигналы моделей и сервисы выпускают все типы (тела проверяет `emit_event`)."""
    from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocument, GeneratedDocumentStatus

    company = make_company(crm_client_id=7001)
    contact = Contact.objects.filter(company=company).first()
    CrmContactMapping.objects.create(contact=contact, crm_contact_id=58)

    deal = make_deal(company)  # request.created
    deal.stage = _status(DealStage, "CALCULATING")
    deal.save()  # deal.stage_changed

    quote = add_quote(deal, 1, QuoteStatusCode.DRAFT, "5000000")
    for code in (QuoteStatusCode.SENT, QuoteStatusCode.APPROVED):  # quote.sent, quote.accepted
        quote.status = _status(QuoteStatus, code)
        quote.save()
    rejected = add_quote(deal, 2, QuoteStatusCode.DRAFT, "4000000")
    for code in (QuoteStatusCode.SENT, QuoteStatusCode.REJECTED):  # quote.rejected
        rejected.status = _status(QuoteStatus, code)
        rejected.save()
    from integration.services.webhooks import emit_quote_outcome

    emit_quote_outcome("quote.viewed", quote=quote, actor={"type": "client"})

    contract = add_contract(deal, quote, ContractStatusCode.PENDING_CLIENT)
    contract.status = _status(ContractStatus, ContractStatusCode.SIGNED)
    contract.client_signed_at = contract.manager_signed_at = contract.created_at
    contract.save()  # contract.signed

    for code in (InvoiceStatusCode.ISSUED, InvoiceStatusCode.PAID, InvoiceStatusCode.OVERDUE):
        invoice = add_invoice(deal, InvoiceStatusCode.DRAFT, total="5000000", contract=contract)
        invoice.status = _status(InvoiceStatus, code)
        invoice.save()  # invoice.issued / paid / overdue
    for code in (ActStatusCode.ISSUED, ActStatusCode.SIGNED):  # act.issued, act.accepted
        act = add_act(deal, ActStatusCode.DRAFT, contract=contract, invoice=invoice)
        act.status = _status(ActStatus, code)
        act.save()
    # act.returned боевой код не выпускает ни при каком статусе акта (`reject_act` ставит DRAFT, кодов RETURNED/DISPUTED/
    # REJECTED в ActStatusCode нет) — см. `test_act_returned_has_no_trigger_in_the_real_flow`; тело — через генератор.
    emit_act_event("act.returned", act=act, reason="Не указана партия 2", actor={"type": "client"})

    from integration.services.webhooks import emit_delivery_event

    shipment = add_fulfillment(deal, FulfillmentStatusCode.SHIPPED, tracking_number="TRK-0047")
    emit_delivery_event("delivery.status_changed", shipment, line_summary="Строки 1–3", line_nos=[1, 2, 3])
    emit_delivery_event(
        "delivery.eta_changed", shipment, line_summary="Строки 1–3", previous_eta=shipment.created_at.date()
    )

    document_kind, _ = DocumentTemplateKind.objects.get_or_create(code="INVOICE", defaults={"name": "Счёт"})
    template, _ = DocumentTemplate.objects.get_or_create(company=company, name="Счёт", defaults={"kind": document_kind})
    issued, _ = GeneratedDocumentStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Выпущен"})
    document = GeneratedDocument.objects.create(
        company=company, deal=deal, template=template, status=issued, number="СЧ-1", title="Счёт на оплату"
    )  # document.created
    assert document.pk

    emit_invite_sent(contact=contact, channels=["telegram", "email"])  # invite.sent

    # Код акцепта контакту с Telegram и сопоставлением в CRM — настоящий сервис портала (FIX-60a).
    contact.telegram_user_id = 424242
    contact.save(update_fields=["telegram_user_id"])
    sent = add_quote(deal, 3, QuoteStatusCode.SENT, "3000000")
    assert request_acceptance_code(sent, contact)["channel"] == "telegram"  # quote.acceptance_code_requested

    # Приёмка и замечание клиента по строкам поставки — настоящие сервисы портала.
    fulfillments = []
    for key in ("accepted", "disputed"):
        order_deal = make_deal(company, title=f"Поставка {key}")
        add_order_quote(order_deal)
        fulfillments.append(add_fulfillment(order_deal, FulfillmentStatusCode.DELIVERED))
    sync_delivery_lines(fulfillments)
    lines = list(DeliveryLine.objects.order_by("id"))
    assert len(lines) >= 2, "для событий приёмки нужны две строки поставки"
    accept_delivery_line(lines[0].pk, contact)
    dispute_delivery_line(lines[1].pk, contact, "Повреждена упаковка")

    # deal.won / deal.lost — закрытие сделки
    won = make_deal(company, title="Выиграна")
    won.stage = _status(DealStage, "CLOSED_WON")
    won.save()
    lost = make_deal(company, title="Проиграна")
    lost.stage = _status(DealStage, "CLOSED_LOST")
    lost.save()
    return encode_document_id("generated", document.pk)


def test_real_code_produces_every_event_type_and_all_bodies_match_the_schema():
    produce_all_events()
    produced = IntegrationWebhookEvent.objects.all()
    missing = set(ALL_EVENTS) - {event.event_type for event in produced}
    assert not missing, f"боевой код не выпустил события: {sorted(missing)} (проверь сценарий produce_all_events)"
    for event in produced:
        body = delivery_payload(event)  # секрет (код акцепта) — из кэша: в журнале он замаскирован
        assert event_errors(body) == [], f"{event.event_type}: {event_errors(body)}"
        assert event.headers["X-Event-Type"] == event.event_type


# ── 4. Режимы проверки в рантайме ────────────────────────────────────────────────────────────────────


def bad_emit(company):
    return emit_event(
        event_type="invoice.issued",
        erp_company_id=company.pk,
        payload={"erp_invoice_id": 1, "number": "N", "amount": "1", "currency": "UZS"},
        crm_client_id=42,
        send_async=False,
    )


def test_strict_mode_raises_and_writes_nothing(settings):
    settings.ERP_EVENTS_CONTRACT_MODE = "strict"
    company = make_company(crm_client_id=42)
    with pytest.raises(EventContractError, match="invoice.issued"):
        bad_emit(company)
    assert IntegrationWebhookEvent.objects.count() == 0


def test_log_mode_logs_the_violation_and_still_sends(settings, caplog):
    settings.ERP_EVENTS_CONTRACT_MODE = "log"
    company = make_company(crm_client_id=42)
    with caplog.at_level(logging.ERROR, logger="integration.services.event_contract"):
        stored = bad_emit(company)
    assert stored is not None and IntegrationWebhookEvent.objects.count() == 1
    assert any("не соответствует events.schema.json" in record.getMessage() for record in caplog.records)


def test_log_mode_never_writes_field_values_to_the_log(settings, caplog):
    """В лог — тип события, путь и правило схемы; значения полей (ПДн: имена, замечания) туда не попадают."""
    settings.ERP_EVENTS_CONTRACT_MODE = "log"
    company = make_company(crm_client_id=42)
    body = example_event("delivery.line_disputed")
    body["payload"]["remark"] = "Секретное замечание Иванова И.И. " * 100  # длиннее maxLength 2000
    body["payload"]["decided_at"] = "ПДн-не-дата-Петров"
    with caplog.at_level(logging.ERROR, logger="integration.services.event_contract"):
        stored = emit_event(
            event_type="delivery.line_disputed",
            erp_company_id=company.pk,
            payload=body["payload"],
            deal=body["deal"],
            actor=body["actor"],
            crm_client_id=42,
            send_async=False,
        )
    assert stored is not None
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "delivery.line_disputed" in text
    assert "payload/decided_at (format)" in text and "payload/remark (maxLength)" in text
    for leaked in ("Петров", "Иванова", "Секретное", "Иван Петров"):
        assert leaked not in text


def test_off_mode_does_not_check(settings):
    settings.ERP_EVENTS_CONTRACT_MODE = "off"
    assert bad_emit(make_company(crm_client_id=42)) is not None


@pytest.mark.parametrize(("debug", "mode"), [(True, "strict"), (False, "log")])
def test_default_mode_follows_debug(settings, debug, mode):
    settings.ERP_EVENTS_CONTRACT_MODE = ""
    settings.DEBUG = debug
    assert event_contract.contract_mode() == mode


def test_missing_schema_is_a_warning_not_a_crash_outside_tests(settings, caplog, monkeypatch):
    settings.ERP_EVENTS_CONTRACT_MODE = "log"
    monkeypatch.setattr(event_contract, "schema_path", lambda: None)
    monkeypatch.setattr(event_contract, "_warned_missing", False)
    with caplog.at_level(logging.WARNING, logger="integration.services.event_contract"):
        assert bad_emit(make_company(crm_client_id=42)) is not None
    assert any("не найден" in record.getMessage() for record in caplog.records)


# ── 5. Секрет подписи: первый из списка ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("current", "current"),
        ("current,previous", "current"),
        (" current , previous ", "current"),
        (",,previous", "previous"),
        ("", ""),
        (",", ""),
    ],
)
def test_signing_secret_is_the_first_of_the_list(settings, raw, expected):
    settings.ERP_WEBHOOK_SECRET = raw
    assert webhook_signing_secret() == expected


def test_events_are_signed_with_the_first_secret_when_two_are_configured(settings):
    settings.ERP_WEBHOOK_SECRET = "new-secret-value,old-secret-value"
    company = make_company(crm_client_id=42)
    body = example_event("quote.viewed")
    stored = emit_event(
        event_type="quote.viewed",
        erp_company_id=company.pk,
        payload=body["payload"],
        deal=body["deal"],
        actor=body["actor"],
        crm_client_id=42,
        send_async=False,
    )
    raw = json.dumps(stored.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert stored.headers["X-Signature"] == sign_payload("new-secret-value", raw)
    assert stored.headers["X-Signature"] != sign_payload("old-secret-value", raw)


def test_act_returned_has_no_trigger_in_the_real_flow():
    """Известный разрыв (аудит): сигнал акта умеет `act.returned`, но ни один статус акта в ERP его не запускает.

    Тест фиксирует это: когда `reject_act` начнёт выпускать событие, он упадёт — и сценарий `produce_all_events`
    нужно перевести с прямого вызова генератора на настоящий переход."""
    company = make_company(crm_client_id=7101)
    deal = make_deal(company)
    contract = add_contract(deal, add_quote(deal, 1, QuoteStatusCode.APPROVED, "1000000"), ContractStatusCode.SIGNED)
    invoice = add_invoice(deal, InvoiceStatusCode.PAID, total="1000000", paid="1000000", contract=contract)
    act = add_act(deal, ActStatusCode.ISSUED, contract=contract, invoice=invoice)
    for code in ActStatusCode.values:
        act.status = _status(ActStatus, code)
        act.save()
    assert not IntegrationWebhookEvent.objects.filter(event_type="act.returned").exists()


def test_delivery_signs_with_the_first_secret_and_a_rotation_takes_effect_for_pending_events(settings):
    """Событие записано при старом секрете, а ушло после ротации: подпись ставит доставка — текущим (первым) секретом."""
    from unittest.mock import MagicMock, patch

    from integration.tasks import deliver_webhook_event

    settings.ERP_WEBHOOK_SECRET = "old-secret-value"
    company = make_company(crm_client_id=42)
    body = example_event("quote.viewed")
    stored = emit_event(
        event_type="quote.viewed",
        erp_company_id=company.pk,
        payload=body["payload"],
        deal=body["deal"],
        actor=body["actor"],
        crm_client_id=42,
        send_async=False,
    )
    settings.ERP_WEBHOOK_SECRET = "new-secret-value,old-secret-value"
    with patch("httpx.Client.post", return_value=MagicMock(status_code=200, text="OK")) as post:
        assert deliver_webhook_event(stored.pk) is True
    sent = post.call_args.kwargs
    assert sent["headers"]["X-Signature"] == sign_payload("new-secret-value", sent["content"])
