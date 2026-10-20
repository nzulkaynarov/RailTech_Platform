"""Лимит частоты запросов CRM к integration (Q-FIX30-4, FIX-35): свой scope `integration`, а не общий `anon` 20/мин.

Запрос с валидным сервисным токеном — «анонимный» пользователь DRF; раньше бот и карточки CRM упирались в общий лимит
20 запросов в минуту с адреса (ответ 429 вне контракта). Теперь ключ — токен, ставка — `INTEGRATION_RATE` (по умолчанию
300/minute), ответ при превышении — 429 `{"detail": "TOO_MANY_REQUESTS"}` и `Retry-After`.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

pytestmark = pytest.mark.django_db

URL = "/api/integration/v1/health"
TOKEN = "test-service-token"  # conftest._seam_secrets


@pytest.fixture(autouse=True)
def _tokens(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = [TOKEN, "second-rotation-token"]


def client_with(token):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api


def test_default_rate_is_far_above_the_old_anon_limit():
    assert SimpleRateThrottle.THROTTLE_RATES["anon"] == "20/minute"
    number, period = SimpleRateThrottle.THROTTLE_RATES["integration"].split("/")
    assert period.startswith("m") and int(number) >= 100


def test_the_21st_request_of_crm_within_a_minute_is_not_throttled():
    api = client_with(TOKEN)
    statuses = [api.get(URL).status_code for _ in range(25)]
    assert 429 not in statuses
    assert set(statuses) == {200}


def test_exceeding_the_own_limit_is_429_with_retry_after(monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "integration", "3/minute")
    api = client_with(TOKEN)
    assert [api.get(URL).status_code for _ in range(3)] == [200, 200, 200]
    limited = api.get(URL)
    assert limited.status_code == 429
    assert limited.json() == {"detail": "TOO_MANY_REQUESTS"}
    assert 0 < int(limited["Retry-After"]) <= 60


def test_limit_is_per_token_not_per_address(monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "integration", "2/minute")
    first, second = client_with(TOKEN), client_with("second-rotation-token")
    assert [first.get(URL).status_code for _ in range(3)] == [200, 200, 429]
    assert second.get(URL).status_code == 200, "второй токен — отдельный счётчик"


def test_write_operations_share_the_same_limit(monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "integration", "1/minute")
    api = client_with(TOKEN)
    assert api.get(URL).status_code == 200
    assert api.delete("/api/integration/v1/users/999999/sessions").status_code == 429


def test_unauthenticated_requests_answer_401_not_429(monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "integration", "1/minute")
    anonymous = APIClient()
    assert {anonymous.get(URL).status_code for _ in range(5)} == {401}
    wrong = client_with("wrong-token")
    assert {wrong.get(URL).status_code for _ in range(5)} == {401}
