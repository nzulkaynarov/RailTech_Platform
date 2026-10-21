"""FIX-22: КП в портале — что видно клиенту, код акцепта, акцепт и отказ только через сервисы ERP.

Находки аудита: P-3 (клиент видел и принимал КП в согласовании), P-7 (`GET /quotes/{id}` падал 500 на позиции из
каталога). Контракт 0.2.0: `POST /quotes/{id}/request-code`, коды ошибок акцепта и отказа. На каждый эндпоинт —
чужая компания → 404, `can_act=false` → 403, повтор действия → 409.
"""

from __future__ import annotations

import datetime
import re

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from portal.services import acceptance
from portal.tests.conftest import LOCMEM_CHANNELS
from portal.tests.contract_support import check_response, component, response_schema
from portal.tests.contract_world import make_quote
from rest_framework.throttling import SimpleRateThrottle
from sales.models.acceptance import QuoteAcceptanceCode

from crm.constants import ContractStatusCode, DealStageCode, QuoteStatusCode
from crm.models import Contract, QuoteItem
from notifications.models import EmailLog

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"
VISIBLE = ("sent", "viewed", "accepted", "rejected", "expired", "expired_status")


@pytest.fixture(autouse=True)
def _locmem_mail(settings):
    settings.EMAIL_CHANNELS = LOCMEM_CHANNELS
    mail.outbox.clear()


def post(client, path, body=None):
    return client.post(f"{API}{path}", body if body is not None else {}, format="json")


def emailed_code() -> str:
    """Шестизначный код из последнего письма клиенту (в базе только хеш)."""
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


# ── P-3: клиенту видны только отправленные КП ─────────────────────────────────────────────────────


def test_list_shows_only_quotes_that_were_sent(contract_world, portal_client):
    listed = {item["id"]: item["status"] for item in portal_client.get(f"{API}/quotes").json()}
    expected = {contract_world["quotes"][key].pk for key in VISIBLE}
    assert expected <= set(listed)  # (кроме них в мире есть принятые КП сделок с поставками — они тоже видны)
    assert {listed[contract_world["quotes"][key].pk] for key in VISIBLE} == {
        "sent",
        "viewed",
        "accepted",
        "rejected",
        "expired",
    }
    assert not set(listed) & {quote.pk for quote in contract_world["hidden_quotes"].values()}


@pytest.mark.parametrize(
    "key",
    ["draft", "pending_trade_review", "pending_approval", "ready_to_send", "sent_without_link"],
)
def test_quote_before_sending_is_not_found_everywhere(contract_world, portal_client, key):
    """КП в согласовании (и любое до отправки) — 404 карточкой, акцептом, отказом и запросом кода."""
    quote = contract_world["hidden_quotes"][key]
    for method, path, body in (
        ("get", f"/quotes/{quote.pk}", None),
        ("post", f"/quotes/{quote.pk}/request-code", {}),
        ("post", f"/quotes/{quote.pk}/accept", {"code": "123456"}),
        ("post", f"/quotes/{quote.pk}/reject", {"reason": "не хочу"}),
    ):
        url = f"{API}{path}"
        response = portal_client.get(url) if method == "get" else portal_client.post(url, body, format="json")
        assert response.status_code == 404, f"{method.upper()} {path} → {response.status_code}"
        assert response.json() == {"detail": "NOT_FOUND"}
    quote.refresh_from_db()
    assert quote.status.code != QuoteStatusCode.APPROVED  # акцептом КП в согласовании стать нельзя


def test_every_visible_quote_has_a_public_link_and_no_internal_layer(contract_world, portal_client):
    for key in VISIBLE:
        body = portal_client.get(f"{API}/quotes/{contract_world['quotes'][key].pk}").json()
        assert (
            body["public_url"].startswith("http")
            and contract_world["quotes"][key].public_access_token in body["public_url"]
        )
        assert not check_response(body, component("Quote"))


# ── P-7: GET /quotes/{id} с позицией из каталога ─────────────────────────────────────────────────


def test_quote_with_catalog_items_is_200_and_unit_comes_from_the_product_card(contract_world, portal_client):
    quote = make_quote(
        contract_world["main"],
        20,
        QuoteStatusCode.SENT,
        uzs=contract_world["uzs"],
        items=False,
    )
    QuoteItem.objects.create(
        quote=quote, product=contract_world["product"], imported_raw_name="труба клиента", quantity=3, unit=""
    )
    response = portal_client.get(f"{API}/quotes/{quote.pk}")
    assert response.status_code == 200
    line = response.json()["lines"][0]
    assert line["title"] == contract_world["product"].name and line["unit"] == "шт"  # единица — из `uom` карточки


def _detail_query_count(client, quote) -> int:
    with CaptureQueriesContext(connection) as queries:
        assert client.get(f"{API}/quotes/{quote.pk}").status_code == 200
    return len(queries)


def test_quote_detail_does_not_query_per_line(contract_world, portal_client):
    """Число запросов карточки КП не растёт с числом позиций каталога (единица — `select_related("product__uom")`)."""
    world = contract_world
    few = make_quote(world["main"], 21, QuoteStatusCode.SENT, uzs=world["uzs"], items=False)
    many = make_quote(world["main"], 22, QuoteStatusCode.SENT, uzs=world["uzs"], items=False)
    for quote, count in ((few, 1), (many, 8)):
        for number in range(count):
            QuoteItem.objects.create(
                quote=quote,
                product=world["product"],
                imported_raw_name=f"позиция {number}",
                quantity=1,
                unit="",
                position=number + 1,
            )
    # Первое открытие КП отмечает просмотр (лишние запросы) — прогреваем обе карточки и сравниваем повторное чтение.
    _detail_query_count(portal_client, few)
    _detail_query_count(portal_client, many)
    assert _detail_query_count(portal_client, many) == _detail_query_count(portal_client, few)


# ── POST /quotes/{id}/request-code ───────────────────────────────────────────────────────────────


def test_request_code_by_email_is_202_with_masked_address_and_works_end_to_end(
    contract_world, portal_client, client_contact
):
    quote = contract_world["quotes"]["sent"]
    response = post(portal_client, f"/quotes/{quote.pk}/request-code")

    assert response.status_code == 202
    assert response.json() == {"channel": "email", "sent_to": "a***@example.uz", "expires_in": 900}
    assert not check_response(response.json(), response_schema("/quotes/{id}/request-code", "post", "202"))
    # письмо через шаблон ERP: в `EmailLog` и в почте клиента — по адресу контакта сессии
    assert mail.outbox[-1].to == [client_contact.email]
    log = EmailLog.objects.get(template="quote_acceptance_code")
    assert log.status == EmailLog.STATUS_SENT and log.to_emails == [client_contact.email]
    row = QuoteAcceptanceCode.objects.get(quote=quote)
    assert row.email == client_contact.email and row.consumed_at is None

    accepted = post(portal_client, f"/quotes/{quote.pk}/accept", {"code": emailed_code()})
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    assert not check_response(accepted.json(), response_schema("/quotes/{id}/accept", "post", "200"))


def test_new_request_replaces_the_previous_code(contract_world, portal_client):
    quote = contract_world["quotes"]["sent"]
    post(portal_client, f"/quotes/{quote.pk}/request-code")
    first = emailed_code()
    post(portal_client, f"/quotes/{quote.pk}/request-code")
    second = emailed_code()

    assert QuoteAcceptanceCode.objects.filter(quote=quote, consumed_at__isnull=True).count() == 1
    if first != second:
        stale = post(portal_client, f"/quotes/{quote.pk}/accept", {"code": first})
        assert stale.status_code == 409 and stale.json() == {"detail": "QUOTE_CODE_INVALID"}


def test_request_code_without_any_channel_is_422(contract_world, portal_client, client_contact):
    type(client_contact).objects.filter(pk=client_contact.pk).update(email="", telegram_user_id=None)

    response = post(portal_client, f"/quotes/{contract_world['quotes']['sent'].pk}/request-code")

    assert response.status_code == 422 and response.json() == {"detail": "CONTACT_CHANNEL_REQUIRED"}
    assert not QuoteAcceptanceCode.objects.exists()


def test_request_code_for_a_telegram_only_contact_not_matched_in_crm_is_422(
    contract_world, portal_client, client_contact
):
    """Контакт только с Telegram и без сопоставления в CRM: боту писать некому, письма нет — 422, а не код в никуда.
    (С сопоставлением код уходит событием `quote.acceptance_code_requested`: `test_portal_acceptance_code_event.py`.)"""
    type(client_contact).objects.filter(pk=client_contact.pk).update(email="")

    response = post(portal_client, f"/quotes/{contract_world['quotes']['sent'].pk}/request-code")

    assert response.status_code == 422 and response.json() == {"detail": "CONTACT_CHANNEL_REQUIRED"}


def test_request_code_other_company_is_404(contract_world, portal_client, other_portal_client):
    quote = contract_world["quotes"]["sent"]
    response = post(other_portal_client, f"/quotes/{quote.pk}/request-code")
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}
    assert not QuoteAcceptanceCode.objects.exists() and not mail.outbox


def test_request_code_without_can_act_is_403(contract_world, readonly_portal_client):
    response = post(readonly_portal_client, f"/quotes/{contract_world['quotes']['sent'].pk}/request-code")
    assert response.status_code == 403 and response.json() == {"detail": "FORBIDDEN"}
    assert not QuoteAcceptanceCode.objects.exists() and not mail.outbox


def test_request_code_without_session_is_401(contract_world, anon_portal_client):
    response = post(anon_portal_client, f"/quotes/{contract_world['quotes']['sent'].pk}/request-code")
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("key", "code"),
    [
        ("accepted", "QUOTE_FINALIZED"),
        ("rejected", "QUOTE_FINALIZED"),
        ("expired", "QUOTE_EXPIRED"),
        ("expired_status", "QUOTE_EXPIRED"),
    ],
)
def test_request_code_for_a_quote_not_awaiting_an_answer_is_409(contract_world, portal_client, key, code):
    response = post(portal_client, f"/quotes/{contract_world['quotes'][key].pk}/request-code")
    assert response.status_code == 409 and response.json() == {"detail": code}
    assert not mail.outbox


def test_request_code_shares_the_portal_accept_limit(contract_world, portal_client, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "portal_accept", "2/minute")
    path = f"/quotes/{contract_world['quotes']['sent'].pk}/request-code"
    codes = [post(portal_client, path).status_code for _ in range(3)]
    assert codes == [202, 202, 429]
    assert post(portal_client, path).json() == {"detail": "TOO_MANY_REQUESTS"}


# ── POST /quotes/{id}/accept ─────────────────────────────────────────────────────────────────────


def test_accept_goes_through_the_lifecycle_service(contract_world, portal_client, client_contact):
    quote = contract_world["quotes"]["sent"]
    post(portal_client, f"/quotes/{quote.pk}/request-code")

    response = post(portal_client, f"/quotes/{quote.pk}/accept", {"code": emailed_code()})

    assert response.status_code == 200 and response.json()["status"] == "accepted"
    quote.refresh_from_db()
    assert quote.status.code == QuoteStatusCode.APPROVED
    assert quote.deal.stage.code == DealStageCode.CONTRACT_SIGNED
    assert (
        Contract.objects.filter(deal=quote.deal, quote=quote)
        .exclude(status__code=ContractStatusCode.CANCELLED)
        .exists()
    )
    assert QuoteAcceptanceCode.objects.get(quote=quote).consumed_at is not None


@pytest.mark.parametrize("code", ["000000", "1"])
def test_accept_with_wrong_or_not_requested_code(contract_world, portal_client, code):
    quote = contract_world["quotes"]["sent"]
    response = post(portal_client, f"/quotes/{quote.pk}/accept", {"code": code})
    assert response.status_code == (409 if len(code) >= 4 else 422)
    assert response.json() == {"detail": "QUOTE_CODE_INVALID" if len(code) >= 4 else "VALIDATION_ERROR"}
    quote.refresh_from_db()
    assert quote.status.code == QuoteStatusCode.SENT


@pytest.mark.parametrize(
    ("key", "code"),
    [
        ("accepted", "QUOTE_FINALIZED"),
        ("rejected", "QUOTE_FINALIZED"),
        ("expired", "QUOTE_EXPIRED"),
        ("expired_status", "QUOTE_EXPIRED"),
    ],
)
def test_accept_quote_not_awaiting_an_answer_is_409_and_keeps_the_code(contract_world, portal_client, key, code):
    quote = contract_world["quotes"][key]
    response = post(portal_client, f"/quotes/{quote.pk}/accept", {"code": "123456"})
    assert response.status_code == 409 and response.json() == {"detail": code}


def test_accept_repeat_is_409(contract_world, portal_client):
    quote = contract_world["quotes"]["sent"]
    post(portal_client, f"/quotes/{quote.pk}/request-code")
    code = emailed_code()
    assert post(portal_client, f"/quotes/{quote.pk}/accept", {"code": code}).status_code == 200
    again = post(portal_client, f"/quotes/{quote.pk}/accept", {"code": code})
    assert again.status_code == 409 and again.json() == {"detail": "QUOTE_FINALIZED"}


def test_accept_other_company_is_404(contract_world, other_portal_client):
    response = post(other_portal_client, f"/quotes/{contract_world['quotes']['sent'].pk}/accept", {"code": "123456"})
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}


def test_accept_without_can_act_is_403(contract_world, readonly_portal_client):
    response = post(readonly_portal_client, f"/quotes/{contract_world['quotes']['sent'].pk}/accept", {"code": "123456"})
    assert response.status_code == 403 and response.json() == {"detail": "FORBIDDEN"}


def test_accept_body_outside_the_contract_is_422(contract_world, portal_client):
    path = f"/quotes/{contract_world['quotes']['sent'].pk}/accept"
    assert post(portal_client, path, {"code": "1234567890123"}).status_code == 422
    assert post(portal_client, path, {}).status_code == 422


# ── POST /quotes/{id}/reject ─────────────────────────────────────────────────────────────────────


def test_reject_goes_through_the_lifecycle_service(contract_world, portal_client):
    quote = contract_world["quotes"]["sent"]
    response = post(portal_client, f"/quotes/{quote.pk}/reject", {"reason": "Дорого"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected" and body["rejected_reason"] == "Дорого"
    assert not check_response(body, response_schema("/quotes/{id}/reject", "post", "200"))
    quote.refresh_from_db()
    assert quote.status.code == QuoteStatusCode.REJECTED
    assert quote.deal.stage.code == DealStageCode.CALCULATING  # сделка вернулась на расчёт, как у публичной страницы


def test_reject_repeat_is_409(contract_world, portal_client):
    path = f"/quotes/{contract_world['quotes']['sent'].pk}/reject"
    assert post(portal_client, path, {"reason": "Дорого"}).status_code == 200
    again = post(portal_client, path, {"reason": "Дорого"})
    assert again.status_code == 409 and again.json() == {"detail": "QUOTE_FINALIZED"}


@pytest.mark.parametrize(
    ("key", "code"),
    [
        ("accepted", "QUOTE_FINALIZED"),
        ("rejected", "QUOTE_FINALIZED"),
        ("expired", "QUOTE_EXPIRED"),
        ("expired_status", "QUOTE_EXPIRED"),
    ],
)
def test_reject_quote_not_awaiting_an_answer_is_409(contract_world, portal_client, key, code):
    response = post(portal_client, f"/quotes/{contract_world['quotes'][key].pk}/reject", {"reason": "поздно"})
    assert response.status_code == 409 and response.json() == {"detail": code}


def test_reject_value_error_from_the_lifecycle_is_409_not_500(contract_world, portal_client, monkeypatch):
    """Жизненный цикл кинул ValueError (гонка двух вкладок): ответ 409, а не 500."""
    quote = contract_world["quotes"]["sent"]

    def raced(quote_id, **kwargs):
        from crm.models import QuoteStatus

        type(quote).objects.filter(pk=quote_id).update(status=QuoteStatus.objects.get(code=QuoteStatusCode.REJECTED))
        raise ValueError("Cannot reject quote in status 'REJECTED'. Only SENT quotes can be rejected.")

    monkeypatch.setattr("portal.views.perform_quote_rejection", raced)
    response = post(portal_client, f"/quotes/{quote.pk}/reject", {"reason": "Дорого"})
    assert response.status_code == 409 and response.json() == {"detail": "QUOTE_FINALIZED"}


def test_reject_with_blank_reason_is_422(contract_world, portal_client):
    response = post(portal_client, f"/quotes/{contract_world['quotes']['sent'].pk}/reject", {"reason": "  "})
    assert response.status_code == 422 and response.json() == {"detail": "REASON_REQUIRED"}


def test_reject_other_company_is_404(contract_world, other_portal_client):
    response = post(other_portal_client, f"/quotes/{contract_world['quotes']['sent'].pk}/reject", {"reason": "x"})
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}


def test_reject_without_can_act_is_403(contract_world, readonly_portal_client):
    response = post(readonly_portal_client, f"/quotes/{contract_world['quotes']['sent'].pk}/reject", {"reason": "x"})
    assert response.status_code == 403 and response.json() == {"detail": "FORBIDDEN"}


def test_expiry_is_judged_by_the_local_business_date(contract_world, portal_client):
    """КП со сроком «сегодня» ещё действует: просрочка — строго раньше сегодняшней бизнес-даты."""
    from django.utils import timezone

    quote = contract_world["quotes"]["sent"]
    type(quote).objects.filter(pk=quote.pk).update(valid_until=timezone.localdate())
    assert post(portal_client, f"/quotes/{quote.pk}/request-code").status_code == 202
    type(quote).objects.filter(pk=quote.pk).update(valid_until=timezone.localdate() - datetime.timedelta(days=1))
    assert post(portal_client, f"/quotes/{quote.pk}/request-code").json() == {"detail": "QUOTE_EXPIRED"}


@pytest.mark.parametrize(
    ("email", "masked"),
    [("azamat.client@example.uz", "a***@example.uz"), ("x@y.io", "x***@y.io")],
)
def test_email_is_masked_to_the_first_letter_and_the_domain(email, masked):
    assert acceptance.mask_email(email) == masked
    assert masked.split("@")[0] == email[0] + "***"  # локальная часть адреса не раскрывается


def test_telegram_is_masked_by_username_or_by_name_of_the_channel():
    class Contact:
        telegram_username = "azamat_client"

    assert acceptance.mask_telegram(Contact) == "@a***"
    Contact.telegram_username = ""
    assert acceptance.mask_telegram(Contact) == "Telegram"


def test_quote_expired_by_the_nightly_task_stays_visible_as_expired(contract_world, portal_client):
    """Ночная задача `crm.expire_stale_quotes` ставит статус EXPIRED: КП не пропадает (404) у клиента на следующий день."""
    quote = contract_world["quotes"]["expired_status"]
    assert quote.status.code == "EXPIRED"
    listed = {item["id"]: item["status"] for item in portal_client.get(f"{API}/quotes").json()}
    assert listed[quote.pk] == "expired"
    detail = portal_client.get(f"{API}/quotes/{quote.pk}")
    assert detail.status_code == 200 and detail.json()["status"] == "expired"
    assert not check_response(detail.json(), component("Quote"))


@pytest.mark.parametrize("valid_until", [None, datetime.date(2999, 1, 1)])
def test_expired_status_is_expired_even_without_a_past_valid_until(contract_world, portal_client, valid_until):
    quote = contract_world["quotes"]["expired_status"]
    type(quote).objects.filter(pk=quote.pk).update(valid_until=valid_until)
    assert portal_client.get(f"{API}/quotes/{quote.pk}").json()["status"] == "expired"
    assert post(portal_client, f"/quotes/{quote.pk}/reject", {"reason": "x"}).json() == {"detail": "QUOTE_EXPIRED"}
