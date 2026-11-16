"""Письма компании в кабинете — проекция из событий EDS (ЛИД-8, ADR-0026).

Тела событий — пример контракта `letter.registered.v2` и собранное по схеме `document.registered.v2` с блоком `letter`.
Чьё письмо — только по сделке или точному ИНН; повтор события — та же строка; ответ закрывает входящее только своей
компании. Сквозной случай — через приёмник шины `/bus/v1/events`.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path

import pytest
from django.test import Client
from django.utils import timezone
from integration.bus import get_bus
from integration.tests.world import make_company, make_deal
from portal.models import LetterDirection, LetterState, PortalLetter
from portal.services import letters
from rt_bus.django.models import Inbox
from rt_bus.signing import format_timestamp, sign

pytestmark = pytest.mark.django_db

EVENTS_DIR = Path(os.environ.get("RT_BUS_CONTRACTS_DIR", "/opt/rt/contracts/events"))


def incoming(*, deal=None, inn=None, letter_id=None, number="IN-104/26", company=None) -> dict:
    data = copy.deepcopy(
        json.loads((EVENTS_DIR / "eds" / "examples" / "letter.registered.v2.json").read_text(encoding="utf-8"))["data"]
    )
    data["letter"]["eds_letter_id"] = letter_id or str(uuid.uuid4())
    data["letter"]["number"] = number
    data["letter"]["sender"]["inn"] = inn
    data["links"].update(
        {
            "erp_deal_id": deal.pk if deal else None,
            "erp_request_id": deal.pk if deal else None,
            "erp_company_id": company.pk if company else None,
        }
    )
    return data


def outgoing(*, deal=None, inn=None, reply_to: dict | None = None, number="OUT-007/26", doc_id=None) -> dict:
    return {
        "document": {
            "eds_document_id": doc_id or str(uuid.uuid4()),
            "kind": "letter_out",
            "number": number,
            "subject": "Ответ на запрос КП",
            "author": {"crm_user_id": 11, "full_name": "Сардор Снабженцев"},
            "registered_at": "2026-11-16T07:00:00Z",
            "amount": None,
            "due_date": None,
            "erp_deal_id": deal.pk if deal else None,
            "deal_number": None,
            "letter": {
                "recipient": {"name": "ООО «Клиент»", "inn": inn, "email": "office@client.uz"},
                "in_reply_to": reply_to,
            },
        },
        "actor": {"type": "staff", "crm_user_id": 11},
    }


def test_incoming_by_deal_is_a_receipt_in_the_deal_company():
    company = make_company(inn="300000777")
    deal = make_deal(company)
    outcome = letters.apply_letter_registered(incoming(deal=deal, inn="999999999"))
    assert outcome.applied
    row = PortalLetter.objects.get(company=company)
    assert (row.direction, row.state, row.number, row.deal_id) == (
        LetterDirection.IN,
        LetterState.REGISTERED,
        "IN-104/26",
        deal.pk,
    )
    assert str(row.date) == "2026-10-26"


def test_incoming_without_deal_matches_exact_inn_only():
    company = make_company(inn="300000001")
    make_company(name="ООО «Пример Логистик» другое", inn="300000002", crm_client_id=7002)
    assert letters.apply_letter_registered(incoming(inn="300000001")).applied
    assert PortalLetter.objects.get().company == company
    # Ни сделки, ни ИНН — письмо в кабинет не попадает; по названию не сопоставляем.
    assert letters.apply_letter_registered(incoming(inn=None)).reason == "no_company"
    assert letters.apply_letter_registered(incoming(inn="300000999")).reason == "no_company"
    assert PortalLetter.objects.count() == 1


def test_incoming_linked_by_the_registrar_to_an_erp_company():
    """Аудит сущностей С-7: регистратор EDS связал письмо с компанией ERP — квитанция у неё, даже без ИНН в письме."""
    company = make_company(inn="300000555")
    assert letters.apply_letter_registered(incoming(company=company, inn=None)).applied
    assert PortalLetter.objects.get().company == company


def test_outgoing_answer_closes_the_incoming_of_the_same_company():
    company = make_company(inn="300000777")
    deal = make_deal(company)
    letter_id = str(uuid.uuid4())
    letters.apply_letter_registered(incoming(deal=deal, letter_id=letter_id))
    outcome = letters.apply_document_registered(
        outgoing(deal=deal, reply_to={"eds_letter_id": letter_id, "number": "IN-104/26"})
    )
    assert outcome.applied
    sent = PortalLetter.objects.get(direction=LetterDirection.OUT)
    assert (sent.company, sent.state, sent.reply_number) == (company, LetterState.SENT, "IN-104/26")
    received = PortalLetter.objects.get(direction=LetterDirection.IN)
    assert (received.state, received.reply_number) == (LetterState.ANSWERED, "OUT-007/26")
    # Повтор входящего (поздняя доставка) не откатывает «Отвечено».
    letters.apply_letter_registered(incoming(deal=deal, letter_id=letter_id))
    received.refresh_from_db()
    assert received.state == LetterState.ANSWERED


def test_outgoing_to_a_third_party_does_not_reach_the_company():
    company = make_company(inn="300000777")
    letter_id = str(uuid.uuid4())
    letters.apply_letter_registered(incoming(inn="300000777", letter_id=letter_id))
    bank = make_company(name="Банк", inn="200000001", crm_client_id=None)
    # Письмо в банк «в ответ» на письмо компании: банк — получатель, кабинет компании его не видит, входящее не «Отвечено».
    letters.apply_document_registered(
        outgoing(inn="200000001", reply_to={"eds_letter_id": letter_id, "number": "IN-104/26"})
    )
    assert not PortalLetter.objects.filter(company=company, direction=LetterDirection.OUT).exists()
    assert PortalLetter.objects.get(company=company).state == LetterState.REGISTERED
    assert PortalLetter.objects.get(company=bank).direction == LetterDirection.OUT


def test_repeat_and_non_letter_documents():
    company = make_company(inn="300000777")
    doc_id = str(uuid.uuid4())
    letters.apply_document_registered(outgoing(inn="300000777", doc_id=doc_id))
    assert letters.apply_document_registered(outgoing(inn="300000777", doc_id=doc_id)).reason == "updated"
    assert PortalLetter.objects.filter(company=company).count() == 1
    memo = outgoing(inn="300000777")
    memo["document"]["kind"] = "memo"
    del memo["document"]["letter"]
    assert letters.apply_document_registered(memo).reason == "not_letter_out"


def test_bus_receiver_projects_the_incoming_letter(monkeypatch, django_capture_on_commit_callbacks):
    secret = "e" * 64
    monkeypatch.setenv("RT_BUS_SECRET_EDS_ERP", secret)
    bus = get_bus()
    monkeypatch.setattr(bus, "enqueue", bus.process_inbox)
    company = make_company(inn="300000001")
    env = json.loads((EVENTS_DIR / "eds" / "examples" / "letter.registered.v2.json").read_text(encoding="utf-8"))
    env.update({"id": str(uuid.uuid4()), "time": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")})
    env["data"] = incoming(inn="300000001")
    body = json.dumps(env, ensure_ascii=False).encode()
    stamp = format_timestamp(timezone.now())
    with django_capture_on_commit_callbacks(execute=True):
        response = Client().post(
            "/bus/v1/events",
            data=body,
            content_type="application/cloudevents+json",
            HTTP_X_RT_PUBLISHER="eds",
            HTTP_X_RT_EVENT_ID=env["id"],
            HTTP_X_RT_TIMESTAMP=stamp,
            HTTP_X_RT_SIGNATURE=sign(secret, env["id"], stamp, body),
        )
    assert response.status_code == 200 and response.json()["status"] == "received"
    assert Inbox.objects.get(event_id=env["id"]).status == "processed"
    assert PortalLetter.objects.get(company=company).number == "IN-104/26"
