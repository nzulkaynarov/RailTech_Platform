"""A1, A7, A2 волны 18a — «Отметить за контрагента»: решение клиента по КП и согласие с договором записывает сотрудник.

* A1: «Клиент принял / отклонил» по подтверждению клиента (обязательный файл — решение юриста 2026-11-02) идёт тем же
  ядром, что онлайн-решение в кабинете: тот же итог (статус КП, стадия, проект, договор, событие, уведомление), плюс
  атрибуция на КП, в журнале и в событии (`recorded_by_staff`); только SENT (иначе 409), право `deal.manage` (иначе 403),
  поля и файл (иначе 400).
* A7: «КП отправлено → Проект» руками не переводится (409), договор из отправленного, но не принятого КП не формируется.
* A2: «Согласован клиентом» у договора — с каналом и лицом со стороны клиента, видны в истории проекта.
"""

from __future__ import annotations

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from integration.tests import bus_support
from integration.tests import world as w

from crm.constants import ContractStatusCode, DealStageCode, QuoteStatusCode
from crm.models import ActivityLog, Contract, Deal, Quote
from crm.services.quotes.lifecycle_accept import perform_quote_acceptance, perform_quote_rejection
from crm.tests.projects_world import PDF, PNG, api, contract_in, pw  # noqa: F401
from notifications.models import Notification
from sourcing.models import Attachment

pytestmark = pytest.mark.django_db

URL = "/api/v1/crm/quotes/{id}/record-client-decision/"


def evidence(name="letter.pdf", content=PDF, content_type="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def body(decision="accept", **over):
    data = {
        "decision": decision,
        "channel": "email",
        "counterparty_person": "Каримов А., снабженец",
        "occurred_on": timezone.localdate().isoformat(),
        "comment": "Письмо клиента: «согласны с КП»" if decision == "accept" else "Дорого, нашли дешевле",
        "file": evidence(),
    }
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


def sent_quote(pw, title="Поставка шпал"):  # noqa: F811
    deal = w.make_deal(pw.client, DealStageCode.QUOTE_SENT, title=title)
    deal.manager = pw.manager
    deal.save(update_fields=["manager"])
    return w.add_quote(deal, 1, QuoteStatusCode.SENT, "7000000")


def post(user, quote, data):
    return api(user).post(URL.format(id=quote.pk), data, format="multipart")


def outcome(quote) -> dict:
    """Наблюдаемый итог решения — то, что должно совпадать у онлайн-пути и записи сотрудником."""
    quote.refresh_from_db()
    deal = Deal.objects.get(pk=quote.deal_id)
    contracts = Contract.objects.filter(quote=quote).exclude(status__code=ContractStatusCode.CANCELLED)
    return {
        "quote": quote.status.code,
        "stage": deal.stage.code,
        "project": (deal.number or "").startswith("ПР"),
        "contracts": [c.status.code for c in contracts],
        "notified": Notification.objects.filter(deal=deal, user=deal.manager).count(),
    }


# ── A1: принято ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_accept_by_staff_gives_the_same_result_as_online_acceptance(pw):  # noqa: F811
    online = sent_quote(pw, "Онлайн")
    perform_quote_acceptance(online.pk, contact_email="i@client.uz", request_ip="10.0.0.1")
    expected = outcome(online)
    bus_support.reset()

    quote = sent_quote(pw, "Со слов")
    response = post(pw.manager, quote, body())

    assert response.status_code == 200, response.content
    assert outcome(quote) == expected
    assert expected["quote"] == QuoteStatusCode.APPROVED and expected["stage"] == DealStageCode.CONTRACT_SIGNED
    assert expected["contracts"] == [ContractStatusCode.PENDING_CLIENT] and expected["project"]
    assert response.json()["client_decision"]["decision"] == "accept"
    assert response.json()["can_record_client_decision"] is False, "решение принято — кнопок больше нет"


def test_accept_records_attribution_on_the_quote_journal_and_event(pw):  # noqa: F811
    quote = sent_quote(pw)
    assert post(pw.manager, quote, body()).status_code == 200
    quote.refresh_from_db()

    meta = quote.client_decision_meta
    assert meta["decision"] == "accept" and meta["channel"] == "email"
    assert meta["counterparty_person"] == "Каримов А., снабженец" and meta["recorded_by_id"] == pw.manager.pk
    assert quote.approved_by_id is None, "approved_by — аккаунт клиента; сотрудник — в атрибуции"
    attachment = Attachment.objects.get(pk=meta["evidence_attachment_id"])
    assert attachment.quote_id == quote.pk and attachment.uploaded_by_id == pw.manager.pk
    assert meta["evidence_name"] == "letter.pdf"

    log = ActivityLog.objects.get(event_code="quote.accepted", entity_id=quote.pk)
    assert log.user_id == pw.manager.pk and log.reason == "Письмо клиента: «согласны с КП»"
    assert log.event_params["on_behalf"]["channel"] == "email"
    assert log.event_params["on_behalf"]["evidence_attachment_id"] == attachment.pk, "ссылка на файл — в журнале"

    event = bus_support.only("quote.accepted")
    bus_support.assert_matches_contract(event)
    assert event["data"]["actor"]["type"] == "staff"
    assert event["data"]["payload"]["recorded_by_staff"] == {
        "staff_name": "manager@own.test",
        "channel": "email",
        "counterparty_person": "Каримов А., снабженец",
        "occurred_on": timezone.localdate().isoformat(),
    }


def test_online_acceptance_has_no_staff_attribution(pw):  # noqa: F811
    quote = sent_quote(pw)
    perform_quote_acceptance(quote.pk, contact_email="i@client.uz")
    quote.refresh_from_db()
    assert quote.client_decision_meta == {}
    assert "recorded_by_staff" not in bus_support.only("quote.accepted")["data"]["payload"]


# ── A1: отклонено ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_reject_by_staff_gives_the_same_result_as_online_rejection(pw):  # noqa: F811
    online = sent_quote(pw, "Онлайн")
    perform_quote_rejection(online.pk, reason="Дорого", contact_email="i@client.uz")
    expected = outcome(online)
    bus_support.reset()

    quote = sent_quote(pw, "Со слов")
    response = post(pw.manager, quote, body("reject"))

    assert response.status_code == 200, response.content
    assert outcome(quote) == expected
    assert expected["quote"] == QuoteStatusCode.REJECTED and expected["stage"] == DealStageCode.CALCULATING
    quote.refresh_from_db()
    assert quote.client_reject_reason == "Дорого, нашли дешевле", "причина — как у отказа в кабинете"
    assert quote.client_decision_meta["decision"] == "reject"
    event = bus_support.only("quote.rejected")
    bus_support.assert_matches_contract(event)
    assert event["data"]["payload"]["reason"] == "Дорого, нашли дешевле"
    assert event["data"]["payload"]["recorded_by_staff"]["channel"] == "email"


# ── A1: отказы ────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status_code",
    [
        QuoteStatusCode.DRAFT,
        QuoteStatusCode.APPROVED,
        QuoteStatusCode.REJECTED,
        "EXPIRED",
        QuoteStatusCode.READY_TO_SEND,
    ],
)
def test_quote_not_sent_is_409(pw, status_code):  # noqa: F811
    deal = w.make_deal(pw.client, DealStageCode.QUOTE_SENT)
    quote = w.add_quote(deal, 1, status_code, "7000000")
    response = post(pw.manager, quote, body())
    assert response.status_code == 409 and response.json() == {"detail": "QUOTE_NOT_SENT"}
    assert not Attachment.objects.filter(quote=quote).exists()
    assert not bus_support.published("quote.accepted")


@pytest.mark.parametrize("who", ["supply", "accountant", "outsider"])
def test_without_deal_manage_is_403(pw, who):  # noqa: F811
    quote = sent_quote(pw)
    response = post(getattr(pw, who), quote, body())
    assert response.status_code == 403
    quote.refresh_from_db()
    assert quote.status.code == QuoteStatusCode.SENT and not Attachment.objects.filter(quote=quote).exists()


def test_admin_may_record(pw):  # noqa: F811
    assert post(pw.admin, sent_quote(pw), body()).status_code == 200


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"file": None}, "EVIDENCE_REQUIRED"),
        ({"file": evidence("empty.pdf", b"", "application/pdf")}, "EVIDENCE_REQUIRED"),
        ({"file": evidence("fake.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")}, "EVIDENCE_INVALID"),
        ({"file": evidence("run.exe", b"MZ\x90\x00", "application/octet-stream")}, "EVIDENCE_INVALID"),
        ({"decision": "maybe"}, "DECISION_INVALID"),
        ({"channel": "pigeon"}, "CHANNEL_INVALID"),
        ({"counterparty_person": "  "}, "COUNTERPARTY_PERSON_REQUIRED"),
        ({"comment": ""}, "COMMENT_REQUIRED"),
        ({"occurred_on": "вчера"}, "OCCURRED_ON_INVALID"),
        (
            {"occurred_on": (timezone.localdate() + datetime.timedelta(days=1)).isoformat()},
            "OCCURRED_ON_IN_FUTURE",
        ),
    ],
)
def test_invalid_fields_are_400_and_change_nothing(pw, over, code):  # noqa: F811
    quote = sent_quote(pw)
    response = post(pw.manager, quote, body(**over))
    assert response.status_code == 400 and response.json() == {"detail": code}
    quote.refresh_from_db()
    assert quote.status.code == QuoteStatusCode.SENT and quote.client_decision_meta == {}
    assert not Attachment.objects.filter(quote=quote).exists() and not bus_support.published()


def test_screenshot_is_accepted_as_evidence(pw):  # noqa: F811
    response = post(pw.manager, sent_quote(pw), body(file=evidence("chat.png", PNG, "image/png"), channel="messenger"))
    assert response.status_code == 200, response.content


def test_quote_detail_tells_who_may_record(pw):  # noqa: F811
    quote = sent_quote(pw)
    url = f"/api/v1/crm/quotes/{quote.pk}/"
    assert api(pw.manager).get(url).json()["can_record_client_decision"] is True
    assert api(pw.supply).get(url).json()["can_record_client_decision"] is False
    assert api(pw.manager).get(url).json()["client_decision"] is None


# ── A7: обходы закрыты ────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("who", ["manager", "admin"])
def test_manual_stage_quote_sent_to_project_is_409(pw, who):  # noqa: F811
    quote = sent_quote(pw)
    response = api(getattr(pw, who)).post(
        f"/api/v1/crm/deals/{quote.deal_id}/change-stage/", {"stage_code": DealStageCode.CONTRACT_SIGNED}, format="json"
    )
    assert response.status_code == 409 and response.json() == {"detail": "QUOTE_ACCEPTANCE_REQUIRED"}
    assert Deal.objects.get(pk=quote.deal_id).stage.code == DealStageCode.QUOTE_SENT


def test_other_manual_moves_from_quote_sent_stay_open(pw):  # noqa: F811
    quote = sent_quote(pw)
    response = api(pw.manager).post(
        f"/api/v1/crm/deals/{quote.deal_id}/change-stage/", {"stage_code": DealStageCode.CALCULATING}, format="json"
    )
    assert response.status_code == 200, response.content


def test_contract_is_not_generated_from_a_sent_quote(pw):  # noqa: F811
    quote = sent_quote(pw)
    response = api(pw.director).post(
        "/api/v1/crm/contracts/generate-from-quote/", {"quote_id": quote.pk}, format="json"
    )
    assert response.status_code == 400 and response.json() == {"detail": "CONTRACT_NEEDS_APPROVAL"}
    assert not Contract.objects.filter(quote=quote).exists()


# ── A2: «Согласован клиентом» с каналом и лицом ───────────────────────────────────────────────────────────────────


CLIENT_AGREED = "/api/v1/crm/contracts/{id}/client-agreed/"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        ({}, "CHANNEL_INVALID"),
        ({"channel": "phone"}, "COUNTERPARTY_PERSON_REQUIRED"),
        ({"channel": "phone", "counterparty_person": "  "}, "COUNTERPARTY_PERSON_REQUIRED"),
    ],
)
def test_client_agreed_needs_channel_and_person(pw, data, code):  # noqa: F811
    contract = contract_in(pw, ContractStatusCode.PENDING_CLIENT)
    response = api(pw.accountant).post(CLIENT_AGREED.format(id=contract.id), data, format="json")
    assert response.status_code == 400 and response.json() == {"detail": code}
    contract.refresh_from_db()
    assert contract.status.code == ContractStatusCode.PENDING_CLIENT


def test_client_agreed_attribution_is_in_the_project_history(pw):  # noqa: F811
    contract = contract_in(pw, ContractStatusCode.PENDING_CLIENT)
    data = {"channel": "paper", "counterparty_person": "Юсупова Н., юрист"}
    assert api(pw.accountant).post(CLIENT_AGREED.format(id=contract.id), data, format="json").status_code == 200

    log = ActivityLog.objects.get(event_code="contract.client_agreed")
    assert log.event_params["on_behalf"] == data
    card = api(pw.accountant).get(f"/api/v1/crm/projects/{pw.deal.pk}/").json()
    entry = next(e for e in card["contract"]["history"] if e["code"] == "contract.client_agreed")
    assert entry["on_behalf"] == data
    other = [e for e in card["journal"] if e["code"] != "contract.client_agreed"]
    assert all(e["on_behalf"] is None for e in other)


def test_quote_acceptance_by_staff_shows_in_the_project_journal(pw):  # noqa: F811
    quote = sent_quote(pw)
    assert post(pw.manager, quote, body()).status_code == 200
    card = api(pw.accountant).get(f"/api/v1/crm/projects/{quote.deal_id}/").json()
    entry = next(e for e in card["journal"] if e["code"] == "quote.accepted")
    assert entry["on_behalf"] == {"channel": "email", "counterparty_person": "Каримов А., снабженец"}
    assert card["can_create_contract"] is False, "договор уже сформирован при акцепте"
    assert Quote.objects.get(pk=quote.pk).status.code == QuoteStatusCode.APPROVED
