"""Публичная ссылка на СТАРУЮ редакцию и след возврата КП (наблюдения O1/O2, 18-08).

O2: у каждой версии КП свой публичный токен, поэтому ссылка на прошлую редакцию продолжает
жить после выпуска новой. Эталоны (HubSpot «Recall & edit», Odoo reset-to-draft) переиздают
по тому же адресу и такой проблемы не имеют — у нас страница обязана честно сказать, что
цена уже не та. «Superseded» считается по факту наличия более новой РАЗОСЛАННОЙ версии,
без отдельного статуса (модель Salesforce CPQ: живёт одна запись, версия — снимок).

O1: вернуть КП на доработку можно по одной лишь ссылке (действие обратимо, как reject в Odoo),
поэтому единственная защита — след: e-mail получателя, которому мы отправляли ссылку, и IP.
"""

import pytest
from rest_framework.test import APIClient

from crm.models import ActivityLog, Quote, QuoteStatus
from crm.tests.test_public_quote_page_wave_a import _make_sent_quote, _url, lookups  # noqa: F401


def _page(quote):
    return APIClient().get(_url(quote), SERVER_NAME="localhost", HTTP_ACCEPT="text/html")


@pytest.mark.django_db
def test_page_says_nothing_while_this_is_the_latest_version(lookups):  # noqa: F811
    quote, _ = _make_sent_quote(token="tok_latest")
    body = _page(quote).content.decode()
    assert "Есть более новая редакция" not in body


@pytest.mark.django_db
def test_page_warns_when_a_newer_sent_version_exists(lookups):  # noqa: F811
    quote, _ = _make_sent_quote(token="tok_superseded")
    Quote.objects.create(
        deal=quote.deal,
        version=quote.version + 1,
        status=QuoteStatus.objects.get(code="SENT"),
        seller_company_id=quote.seller_company_id,
        prepared_by=quote.prepared_by,
    )
    body = _page(quote).content.decode()
    assert "Есть более новая редакция" in body
    assert f"№{quote.version + 1}" in body


@pytest.mark.django_db
def test_draft_next_version_does_not_supersede_a_live_link(lookups):  # noqa: F811
    """Черновик, который продавец ещё правит, ничего не отменяет — клиент не должен пугаться."""
    quote, _ = _make_sent_quote(token="tok_draft_next")
    Quote.objects.create(
        deal=quote.deal,
        version=quote.version + 1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        seller_company_id=quote.seller_company_id,
        prepared_by=quote.prepared_by,
    )
    assert "Есть более новая редакция" not in _page(quote).content.decode()


@pytest.mark.django_db
def test_return_for_revision_records_recipient_and_ip(lookups):  # noqa: F811
    quote, _ = _make_sent_quote(token="tok_trace", contact_email="buyer@acme.uz")
    resp = APIClient().post(
        _url(quote, "reject/"),
        {"reason": "Нужен другой срок"},
        format="json",
        SERVER_NAME="localhost",
        REMOTE_ADDR="203.0.113.77",
    )
    assert resp.status_code == 200

    entry = ActivityLog.objects.get(entity_id=quote.id, event_code="quote.rejected")
    assert entry.event_params["contact_email"] == "buyer@acme.uz", "непонятно, кому уходила ссылка"
    assert entry.event_params["ip"], "IP не записан — следа не осталось"
    assert entry.event_params["reason"] == "Нужен другой срок"


@pytest.mark.django_db
def test_page_has_no_leaked_template_comments(lookups):  # noqa: F811
    """Ни один комментарий шаблона не должен доехать до клиента.

    Прогон глазами 18-08: многострочный `{# … #}` Django комментарием НЕ считает и печатает
    как текст — клиент увидел служебную заметку разработчика прямо над кнопкой «Принять».
    Многострочные комментарии в этом шаблонетолько через `{% comment %}`.
    """
    quote, _ = _make_sent_quote(token="tok_no_comments")
    body = _page(quote).content.decode()
    assert "{#" not in body and "#}" not in body, "комментарий шаблона утёк на страницу клиента"
    assert "O2:" not in body


@pytest.mark.django_db
def test_returned_state_wording_matches_on_both_screens(lookups):  # noqa: F811
    """Серверный экран «возвращено» и его JS-двойник говорят ОДНО И ТО ЖЕ.

    Прогон на проде 18-08: серверный блок переименовали в «возвращено продавцу», а блок
    `#rejected-state`, который скрипт показывает сразу после ответа (без перезагрузки),
    остался со старым «Предложение отклонено» — клиент видел ОТКАЗ там, где действие
    называется возвратом. Двойники обязаны совпадать словами.
    """
    # 1. Живое КП: на странице есть скрытый JS-двойник и кнопка возврата.
    live, _ = _make_sent_quote(token="tok_wording_live")
    live_body = _page(live).content.decode()
    assert "Вернуть на доработку" in live_body
    assert "Предложение возвращено продавцу" in live_body, "JS-двойник не переименован"
    assert "Предложение отклонено" not in live_body

    # 2. Уже возвращённое КП: серверный экран говорит теми же словами.
    returned, _ = _make_sent_quote(token="tok_wording_returned")
    APIClient().post(_url(returned, "reject/"), {"reason": "дорого"}, format="json", SERVER_NAME="localhost")
    returned_body = _page(returned).content.decode()
    assert "Предложение возвращено продавцу" in returned_body
    assert "Предложение отклонено" not in returned_body
