"""Публикаторы событий ERP на шину rt_bus (B3): `DealRef`, `Actor`, пропуск несопоставленных компаний, тела 23 типов.

Бывший `test_webhooks.py` без доставки: подпись, ретраи и журнал вебхуков заменены библиотекой `rt_bus` (её тесты —
`packages/rt-bus/tests`). Здесь — то, что решает ERP: состав `data` по схемам `packages/contracts/events/erp/`.
Шина проверяет `data` строго до записи в outbox, поэтому каждое событие, дошедшее до outbox, уже соответствует схеме.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.utils import timezone
from integration.models import CrmClientMapping, CrmContactMapping
from integration.services.document_events import publish_document_created
from integration.services.events import (
    VALID_EVENT_TYPES,
    build_actor,
    build_deal_ref,
    event_type_name,
    publish_act_event,
    publish_contract_signed,
    publish_deal_outcome,
    publish_deal_stage_changed,
    publish_delivery_event,
    publish_event,
    publish_invite_sent,
    publish_invoice_event,
    publish_quote_outcome,
    publish_quote_sent,
    publish_request_created,
)
from integration.tests import bus_support
from parties.models import Company, Contact
from portal.services.documents import PortalDocument, encode_document_id

from crm.constants import DealStageCode
from crm.models import Deal, DealStage, Quote, QuoteStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def mapped_company():
    """Тестовая компания ERP, привязанная к клиенту CRM."""
    company = Company.objects.create(name="ООО ТестТранс", inn="123456789")
    mapping = CrmClientMapping.objects.create(company=company, crm_client_id=42)
    return company, mapping


@pytest.fixture
def deal_stages():
    """Настоящие стадии FSM ERP (`crm/constants.py`): ключ — стадия контракта, которую они дают на сделке без документов."""
    codes = {
        "request": DealStageCode.DRAFT,
        "quoting": DealStageCode.CALCULATING,
        "quote_sent": DealStageCode.QUOTE_SENT,
        "won": DealStageCode.CLOSED_WON,
        "lost": DealStageCode.CLOSED_LOST,
    }
    return {key: DealStage.objects.get_or_create(code=code, defaults={"name": code})[0] for key, code in codes.items()}


def test_the_24_types_of_the_erp_are_the_files_of_the_contract():
    import json
    import os
    from pathlib import Path

    events_dir = Path(os.environ["RT_BUS_CONTRACTS_DIR"]) / "erp"
    names = {p.name[: -len(".v1.json")] for p in events_dir.glob("*.v1.json") if not p.name.startswith("_")}
    # Волна 12 (E5): quote.ready_for_approval публикует ERP (EDS-03); волна 16 (D1-9): invite.requested — файлы контракта = VALID_EVENT_TYPES.
    assert names == VALID_EVENT_TYPES and len(VALID_EVENT_TYPES) == 24
    for short in VALID_EVENT_TYPES:
        assert event_type_name(short) == f"uz.railtech.erp.{short}.v1"
        assert json.loads((events_dir / f"{short}.v1.json").read_text(encoding="utf-8"))["type"] == "object"
    with pytest.raises(ValueError, match="Неизвестный тип"):
        event_type_name("quote.vanished")


def test_build_actor():
    assert build_actor() == {"type": "system"}

    user_mock = MagicMock()
    user_mock.is_portal_user = False
    user_mock.get_full_name.return_value = "Азиз Кадиров"
    assert build_actor(user=user_mock) == {"type": "staff", "name": "Азиз Кадиров"}

    portal_user_mock = MagicMock()
    portal_user_mock.is_portal_user = True
    portal_user_mock.get_full_name.return_value = "Клиент Представитель"
    assert build_actor(user=portal_user_mock) == {"type": "client", "name": "Клиент Представитель"}


def test_build_deal_ref(mapped_company, deal_stages):
    company, _ = mapped_company
    deal = Deal.objects.create(company=company, title="Поставка рельсов", stage=deal_stages["quoting"])

    deal_ref = build_deal_ref(deal)
    assert deal_ref["erp_deal_id"] == deal.id
    assert deal_ref["number"] == f"D-{deal.id}"
    assert deal_ref["title"] == "Поставка рельсов"
    assert deal_ref["stage"] == "quoting"
    assert deal_ref["amount"] is None, "КП клиенту не отправлялось — суммы нет"
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


def test_build_deal_ref_amount_ignores_drafts_and_takes_the_latest_sent_quote(mapped_company, deal_stages):
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


def test_deal_ref_stage_outside_the_contract_is_rejected(mapped_company):
    """Сырой код FSM или выдуманная стадия в событие не попадают: код решает, а не молча подставляет."""
    company, _ = mapped_company
    deal = Deal.objects.create(company=company)
    for bad in ("CLOSED_WON", "quoted", "", None):
        with pytest.raises(ValueError, match="не из контракта"):
            build_deal_ref({"erp_deal_id": 1, "stage": bad})
        with pytest.raises(ValueError, match="не из контракта"):
            publish_deal_stage_changed(deal, from_stage="request", to_stage=bad)
    assert bus_support.published() == []


def test_unmapped_company_gets_no_event():
    unmapped = Company.objects.create(name="Локальная без CRM")
    assert publish_event("request.created", unmapped.id, {"source": "erp"}) is None
    assert bus_support.published() == []


def test_mapped_company_event_is_written_to_the_outbox_with_the_old_body(mapped_company):
    company, mapping = mapped_company
    event = publish_event("invite.sent", company.id, {"channels": ["email"]})
    assert event is not None
    envelope = bus_support.only("invite.sent")
    assert envelope["id"] == event.id and envelope["source"] == "rt://erp"
    assert envelope["dataschema"] == "rt://contracts/events/erp/invite.sent/v1"
    assert envelope["subject"] == f"company/{company.id}"
    assert envelope["data"] == {
        "erp_company_id": company.id,
        "crm_client_id": mapping.crm_client_id,
        "actor": {"type": "system"},
        "payload": {"channels": ["email"]},
    }
    assert "version" not in envelope["data"] and "event" not in envelope["data"]  # они в конверте


def test_event_data_not_by_the_schema_is_an_error_and_writes_nothing(mapped_company):
    from rt_bus import EventValidationError

    company, _ = mapped_company
    with pytest.raises(EventValidationError):
        publish_event(
            "invoice.issued", company.id, {"erp_invoice_id": 1, "number": "N", "amount": "1", "currency": "UZS"}
        )
    assert bus_support.published() == []


def test_all_22_event_types_payload_builders(mapped_company, deal_stages):
    company, _ = mapped_company
    deal = Deal.objects.create(company=company, stage=deal_stages["request"])

    publish_request_created(deal, source="cabinet", erp_request_id=12, summary="Строки")
    request = bus_support.only("request.created")["data"]
    assert request["payload"] == {
        "source": "cabinet",
        "erp_request_id": 12,
        "summary": "Строки",
        "company_name": "ООО ТестТранс",
        "company_inn": "123456789",
    }
    assert request["deal"]["erp_deal_id"] == deal.id

    publish_deal_stage_changed(deal, from_stage="request", to_stage="quoting", reason="КП готово")
    assert bus_support.only("deal.stage_changed")["data"]["payload"] == {
        "from": "request",
        "to": "quoting",
        "reason": "КП готово",
    }

    publish_deal_outcome(deal, won=True, amount="50000.00", currency="UZS")
    assert bus_support.only("deal.won")["data"]["payload"]["amount"] == "50000.00"
    publish_deal_outcome(deal, won=False, lost_reason="Дорого")
    assert bus_support.only("deal.lost")["data"]["payload"]["lost_reason"] == "Дорого"

    quote = Quote.objects.create(deal=deal, version=1, total_incl_vat=Decimal("100000.00"))
    publish_quote_sent(quote, public_url="https://cabinet.railtech.uz/q/tok")
    assert bus_support.only("quote.sent")["data"]["payload"]["public_url"] == "https://cabinet.railtech.uz/q/tok"
    publish_quote_outcome("quote.viewed", quote)
    publish_quote_outcome("quote.accepted", quote)
    publish_quote_outcome("quote.rejected", quote, reason="Не подошли сроки")
    assert bus_support.only("quote.rejected")["data"]["payload"]["reason"] == "Не подошли сроки"
    with pytest.raises(ValueError):
        publish_quote_outcome("quote.sent", quote)

    contract_mock = MagicMock(id=55, deal=deal, number="CT-2026-00055")
    publish_contract_signed(contract_mock, by="both")
    assert bus_support.only("contract.signed")["data"]["payload"]["by"] == "both"

    inv_mock = MagicMock(id=77, deal=deal, number="INV-2026-00077", total_incl_vat=Decimal("25000.00"))
    inv_mock.due_date = timezone.now().date()
    inv_mock.currency = "UZS"
    publish_invoice_event("invoice.issued", inv_mock)
    assert bus_support.only("invoice.issued")["data"]["payload"]["amount"] == "25000.00"

    fulf_mock = MagicMock(deal=deal, status=MagicMock(code="in_transit"), tracking_number="TRACK123")
    fulf_mock.expected_delivery_date = timezone.now().date()
    publish_delivery_event("delivery.status_changed", fulf_mock)
    assert bus_support.only("delivery.status_changed")["data"]["payload"]["status"] == "in_transit"

    act_mock = MagicMock(id=88, deal=deal, number="ACT-2026-00088")
    publish_act_event("act.accepted", act_mock)
    assert bus_support.only("act.accepted")["data"]["payload"]["erp_act_id"] == 88

    contact = Contact.objects.create(company=company, name="Иван Иванов")
    CrmContactMapping.objects.create(contact=contact, crm_contact_id=101)
    publish_invite_sent(contact, channels=["telegram", "email"])
    assert bus_support.only("invite.sent")["data"]["payload"] == {
        "channels": ["telegram", "email"],
        "erp_contact_id": contact.id,
        "crm_contact_id": 101,
    }

    # document.created: на входе документ портала (FIX-38), id — портальный, вид — вид документа
    document = PortalDocument(
        id=encode_document_id("act", 999),
        kind="act",
        source="act",
        obj=MagicMock(),
        number="DOC-999",
        date=timezone.localdate(),
        title="Акт сверки",
        file_name="DOC-999.pdf",
        deal=deal,
    )
    publish_document_created(document)
    assert bus_support.only("document.created")["data"]["payload"] == {
        "erp_document_id": 999 * 8 + 4,
        "kind": "act",
        "number": "DOC-999",
        "title": "Акт сверки",
    }
    for envelope in bus_support.published():
        bus_support.assert_matches_contract(envelope)


def test_deal_outcome_payload_has_the_sent_amount_or_zero(mapped_company, deal_stages):
    company, _ = mapped_company
    deal = Deal.objects.create(company=company, stage=deal_stages["request"])
    publish_deal_outcome(deal, won=False, lost_reason="Дорого")
    assert bus_support.only("deal.lost")["data"]["payload"] == {
        "amount": "0.00",
        "currency": "UZS",
        "lost_reason": "Дорого",
    }

    sent = QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Отправлено"})[0]
    Quote.objects.create(
        deal=deal, version=1, status=sent, total_incl_vat=Decimal("750000.00"), public_access_token="tok-sent-2"
    )
    publish_deal_outcome(Deal.objects.get(pk=deal.pk), won=True)
    won = bus_support.only("deal.won")["data"]
    assert won["payload"] == {"amount": "750000.00", "currency": "UZS"}
    assert won["deal"]["amount"] == "750000.00"


# ─── request.created: отправитель и менеджер письма EDS (C1-G-7, решение архитектора 2026-10-26) ─────────────────────


def _staff_user(email, crm_user_id=None):
    from integration.models import CrmUserMapping

    from accounts.models import CustomUser

    user = CustomUser.objects.create_user(
        email=email, username=email, password="pw", first_name="Алия", last_name="Каримова"
    )
    if crm_user_id is not None:
        CrmUserMapping.objects.create(crm_user_id=crm_user_id, user=user)
    return user


def test_request_created_names_the_offline_contact_and_the_deal_owner_as_manager(mapped_company, deal_stages):
    company, _ = mapped_company
    contact = Contact.objects.create(company=company, name="Бахтиёр Каримов", email="b@client.test")
    owner = _staff_user("owner@railtech.test", crm_user_id=7)
    deal = Deal.objects.create(company=company, contact=contact, assigned_to=owner, stage=deal_stages["request"])

    publish_request_created(deal, source="erp", erp_request_id=deal.id, summary="Заявка")
    payload = bus_support.only("request.created")["data"]["payload"]
    assert (payload["contact_name"], payload["manager_crm_user_id"]) == ("Бахтиёр Каримов", 7)


def test_request_created_falls_back_to_the_primary_contact_and_the_deal_manager(mapped_company, deal_stages):
    company, _ = mapped_company
    Contact.objects.create(company=company, name="Второй", email="2@client.test")
    Contact.objects.create(company=company, name="Основной", email="1@client.test", is_primary=True)
    unmapped = _staff_user("nomap@railtech.test")
    manager = _staff_user("manager@railtech.test", crm_user_id=8)
    deal = Deal.objects.create(company=company, assigned_to=unmapped, manager=manager, stage=deal_stages["request"])

    publish_request_created(deal, source="erp", erp_request_id=deal.id)
    payload = bus_support.only("request.created")["data"]["payload"]
    assert (payload["contact_name"], payload["manager_crm_user_id"]) == ("Основной", 8)


def test_request_created_without_known_parties_omits_the_optional_fields(deal_stages):
    """Компания без ИНН-похожего ИНН, без контактов и без ответственного — новых полей нет (событие как до C1-G-7)."""
    company = Company.objects.create(name="ООО Без ИНН")
    CrmClientMapping.objects.create(company=company, crm_client_id=43)
    deal = Deal.objects.create(company=company, stage=deal_stages["request"])

    publish_request_created(deal, source="erp", erp_request_id=deal.id)
    payload = bus_support.only("request.created")["data"]["payload"]
    assert payload == {"source": "erp", "erp_request_id": deal.id, "company_name": "ООО Без ИНН"}


def test_explicit_manager_wins_over_the_deal_owner(mapped_company, deal_stages):
    company, _ = mapped_company
    owner = _staff_user("owner2@railtech.test", crm_user_id=9)
    deal = Deal.objects.create(company=company, assigned_to=owner, stage=deal_stages["request"])

    publish_request_created(deal, source="crm", erp_request_id=deal.id, manager_crm_user_id=101)
    assert bus_support.only("request.created")["data"]["payload"]["manager_crm_user_id"] == 101
