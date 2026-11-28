"""КАБ-1: «Есть предложение» в Кабинете — только когда клиент может открыть КП.

Статус заявки (`projections.request_status`) и список «Предложения» берут КП одним предикатом (`client_quotes_visible` /
`client_quotes_q`). Пока КП на проверке ВЭД, у директора или «готово к отправке», заявка — «В работе», а не «Есть
предложение»; колокольчик «КП отправлено» пишется только при отправке (`READY_TO_SEND` → `SENT`).
"""

from __future__ import annotations

import pytest
from crm.constants import DealStageCode, QuoteStatusCode
from integration.tests.world import add_quote, make_company, make_deal
from portal import projections
from portal.models import PortalNotice
from sales.models import Quote

pytestmark = pytest.mark.django_db

NOT_YET_VISIBLE = [
    QuoteStatusCode.DRAFT,
    QuoteStatusCode.PENDING_TRADE_REVIEW,
    QuoteStatusCode.PENDING_APPROVAL,
    QuoteStatusCode.READY_TO_SEND,
]
VISIBLE = [QuoteStatusCode.SENT, QuoteStatusCode.APPROVED, QuoteStatusCode.REJECTED, QuoteStatusCode.CLOSED, "EXPIRED"]


def _status(deal) -> str:
    deal = type(deal).objects.prefetch_related("quotes__status", "invoices__status", "acts__status").get(pk=deal.pk)
    return projections.request_status(deal)


@pytest.mark.parametrize("quote_status", NOT_YET_VISIBLE)
def test_quote_before_sending_is_not_an_offer_for_the_client(quote_status):
    deal = make_deal(make_company(), DealStageCode.CALCULATING)
    add_quote(deal, 1, quote_status, "5000000")
    assert _status(deal) == "in_progress"


@pytest.mark.parametrize("quote_status", VISIBLE)
def test_quote_the_client_can_open_is_an_offer(quote_status):
    deal = make_deal(make_company(), DealStageCode.QUOTE_SENT)
    add_quote(deal, 1, quote_status, "5000000", sent=True)
    assert _status(deal) == "quoted"


def test_sent_status_without_public_link_is_not_an_offer():
    """Список «Предложения» требует публичную ссылку — без неё и статус «Есть предложение» не нужен."""
    deal = make_deal(make_company(), DealStageCode.QUOTE_SENT)
    add_quote(deal, 1, QuoteStatusCode.SENT, "5000000", sent=False)
    assert _status(deal) == "in_progress"


def test_stage_quote_sent_without_visible_quote_is_not_an_offer():
    deal = make_deal(make_company(), DealStageCode.QUOTE_SENT)
    add_quote(deal, 1, QuoteStatusCode.PENDING_APPROVAL, "5000000")
    assert _status(deal) == "in_progress"


def test_returned_for_rework_keeps_the_offer_the_client_already_has():
    """Версия 1 ушла клиенту, версия 2 пересчитывается и ждёт директора: версия 1 в списке есть — предложение есть."""
    deal = make_deal(make_company(), DealStageCode.CALCULATING)
    add_quote(deal, 1, QuoteStatusCode.SENT, "5000000", sent=True)
    add_quote(deal, 2, QuoteStatusCode.PENDING_APPROVAL, "5200000")
    assert _status(deal) == "quoted"


def test_new_request_stays_new_and_in_calculation_stays_in_progress():
    company = make_company()
    assert _status(make_deal(company, DealStageCode.DRAFT)) == "new"
    assert _status(make_deal(company, DealStageCode.CALCULATING)) == "in_progress"


def test_status_agrees_with_the_cabinet_quotes_list_for_every_quote_status():
    """Один предикат: заявка «Есть предложение» ⇔ в выборке списка «Предложения» есть КП этой сделки."""
    company = make_company()
    for status in [*NOT_YET_VISIBLE, *VISIBLE]:
        deal = make_deal(company, DealStageCode.CALCULATING)
        add_quote(deal, 1, status, "5000000", sent=status in VISIBLE)
        in_list = Quote.objects.filter(projections.client_quotes_q(), deal=deal).exists()
        assert (_status(deal) == "quoted") is in_list, status


@pytest.mark.parametrize("quote_status", NOT_YET_VISIBLE)
def test_no_offer_notice_before_the_quote_is_sent(quote_status):
    """Колокольчик «КП отправлено» пишет только отправка; на этапах до неё отправить нельзя и строки ленты нет."""
    from crm.services.quotes import QuoteLifecycleService

    deal = make_deal(make_company(), DealStageCode.CALCULATING)
    quote = add_quote(deal, 1, quote_status, "5000000")
    if quote_status != QuoteStatusCode.READY_TO_SEND:
        with pytest.raises(Exception, match="Cannot send quote in status"):  # гейт `assert_sendable`
            QuoteLifecycleService.send_to_client(quote.pk, None)
    assert not PortalNotice.objects.filter(kind="quote_sent", object_id=quote.pk).exists()
