"""Причина отказа по КП попадает в ленту (event_params) в ОБЕИХ ветках — офлайн-контакт с
публичной страницы и авторизованный покупатель. Прогон глазами 17-08: продавец видел
«КП отклонено клиентом, КП v2» и нигде не находил причину — шаблон ленты её не печатал,
а в ветке авторизованного покупателя причина в параметры не писалась вовсе."""

import pytest
from rest_framework.test import APIClient

from crm.models import ActivityLog
from crm.tests.test_public_quote_page_wave_a import _make_sent_quote, _url, lookups  # noqa: F401


@pytest.mark.django_db
def test_public_reject_reason_lands_in_event_params_and_detail(lookups):  # noqa: F811
    quote, _ = _make_sent_quote(token="tok_reason_feed")
    resp = APIClient().post(
        _url(quote, "reject/"), {"reason": "Дорого, конкурент дешевле"}, format="json", SERVER_NAME="localhost"
    )
    assert resp.status_code == 200
    entry = ActivityLog.objects.get(entity_id=quote.id, event_code="quote.rejected")
    assert entry.event_params["reason"] == "Дорого, конкурент дешевле"
    assert "Дорого, конкурент дешевле" in entry.detail


@pytest.mark.django_db
def test_user_reject_reason_lands_in_event_params(lookups):  # noqa: F811
    from crm.services.quotes import QuoteLifecycleService

    quote, seller_user = _make_sent_quote(token="tok_reason_user")
    QuoteLifecycleService.reject_quote(quote.pk, rejected_by_user=seller_user, reason="Не подходит срок")
    entry = ActivityLog.objects.get(entity_id=quote.id, event_code="quote.rejected")
    assert entry.event_params["reason"] == "Не подходит срок"
    assert entry.detail.endswith("— Не подходит срок")
