"""429 `TOO_MANY_REQUESTS` ERP (шов 0.3.0, FIX-60): `Retry-After` в клиенте, очереди, пробе."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest
import respx
from procrastinate.jobs import Job

from app.config import Settings
from app.domain.errors import ErpRateLimitedError, Reason, UpstreamUnavailableError
from app.integrations.erp import (
    DEFAULT_RETRY_AFTER_S,
    MAX_RETRY_AFTER_S,
    ErpRateLimited,
    HttpxErpClient,
    HttpxErpProbe,
    retry_after_seconds,
)
from app.tasks import erp_handoff, erp_users
from app.tasks.erp_retry import ErpRetryStrategy
from tests.unit.services.test_erp_connector import BASE, HEALTH, HEALTHY, configured
from tests.unit.test_erp_handoff import _DummyStore, _sample_payload

ERP = "https://erp.internal"
HANDOFF = f"{ERP}/api/integration/v1/clients/handoff"
PROVISION = f"{ERP}/api/integration/v1/users/provision"
REVOKE = f"{ERP}/api/integration/v1/users/42/sessions"
TOO_MANY = {"detail": "TOO_MANY_REQUESTS"}


def _response(retry_after: str | None) -> httpx.Response:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return httpx.Response(429, json=TOO_MANY, headers=headers)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("7", 7),
        (" 45 ", 45),
        ("0", 1),  # хотя бы секунда: ноль — повтор без паузы в тот же лимит
        ("999999", MAX_RETRY_AFTER_S),
        ("soon", DEFAULT_RETRY_AFTER_S),
        ("", DEFAULT_RETRY_AFTER_S),
        (None, DEFAULT_RETRY_AFTER_S),
    ],
)
def test_retry_after_seconds_is_bounded_and_tolerant(header: str | None, expected: int) -> None:
    assert retry_after_seconds(_response(header)) == expected


def test_retry_after_accepts_an_http_date() -> None:
    moment = datetime.now(UTC) + timedelta(seconds=90)
    seconds = retry_after_seconds(_response(format_datetime(moment, usegmt=True)))
    assert 80 <= seconds <= 90


# ── Клиент ERP: 429 — временная ошибка с паузой ──────────────────────────────────────────────


async def test_handoff_429_is_a_transient_error_with_the_pause_from_retry_after() -> None:
    client = HttpxErpClient(_DummyStore("t"), Settings(erp_base_url=ERP, erp_service_token="t"))
    with respx.mock:
        respx.post(HANDOFF).mock(return_value=_response("17"))
        with pytest.raises(ErpRateLimitedError) as caught:
            await client.handoff_client(_sample_payload())

    assert caught.value.retry_after_s == 17
    assert caught.value.details["reason"] == Reason.ERP_RATE_LIMITED
    assert isinstance(caught.value, UpstreamUnavailableError)  # для вызывающих — обычный сбой


async def test_staff_sync_429_is_a_transient_error_with_the_pause_from_retry_after() -> None:
    from tests.unit.test_erp_users_client import PAYLOAD, _client

    with respx.mock() as mock:
        mock.post(PROVISION).mock(return_value=_response("21"))
        mock.delete(REVOKE).mock(return_value=_response(None))
        with pytest.raises(ErpRateLimitedError) as provision:
            await _client(ERP).provision_user(PAYLOAD)
        with pytest.raises(ErpRateLimitedError) as revoke:
            await _client(ERP).revoke_sessions(42)

    assert provision.value.retry_after_s == 21
    assert revoke.value.retry_after_s == DEFAULT_RETRY_AFTER_S


# ── Очередь: повтор после паузы, ограниченное число попыток ─────────────────────────────────


def _job(attempts: int) -> Any:
    return Job(
        id=1, queue="notify", lock=None, queueing_lock=None, task_name="t", attempts=attempts
    )


@pytest.mark.parametrize("module", [erp_handoff, erp_users])
def test_queue_waits_for_retry_after_when_it_is_longer_than_the_schedule(module: Any) -> None:
    retry = module.RETRY
    assert isinstance(retry, ErpRetryStrategy)
    decision = retry.get_retry_decision(exception=ErpRateLimitedError(240), job=_job(0))
    assert decision is not None
    waited = (decision.retry_at - datetime.now(UTC)).total_seconds()
    assert 235 <= waited <= 240


def test_queue_keeps_the_regular_schedule_when_retry_after_is_shorter() -> None:
    retry = erp_handoff.RETRY
    decision = retry.get_retry_decision(exception=ErpRateLimitedError(2), job=_job(3))
    assert decision is not None
    waited = (decision.retry_at - datetime.now(UTC)).total_seconds()
    assert waited >= retry.linear_wait * 3 - 1  # расписание не короче, чем без 429


def test_queue_does_not_change_the_schedule_for_other_errors() -> None:
    retry = erp_handoff.RETRY
    decision = retry.get_retry_decision(exception=RuntimeError("boom"), job=_job(1))
    assert decision is not None
    waited = (decision.retry_at - datetime.now(UTC)).total_seconds()
    assert retry.linear_wait - 2 <= waited <= retry.linear_wait + 2


@pytest.mark.parametrize("module", [erp_handoff, erp_users])
def test_rate_limit_retries_are_bounded_by_max_attempts(module: Any) -> None:
    retry = module.RETRY
    limit = retry.max_attempts
    assert limit is not None
    error = ErpRateLimitedError(30)
    assert retry.get_retry_decision(exception=error, job=_job(limit - 1)) is not None
    assert retry.get_retry_decision(exception=error, job=_job(limit)) is None


# ── «Проверить связь»: статус, а не ошибка ───────────────────────────────────────────────────


@respx.mock
async def test_check_reports_rate_limit_as_a_status_not_an_error() -> None:
    respx.get(HEALTH).mock(return_value=_response("12"))
    service, _, _ = configured()

    result = await service.check()

    assert isinstance(result, ErpRateLimited)
    assert result.retry_after_s == 12


@respx.mock
async def test_rate_limit_does_not_overwrite_the_last_known_health() -> None:
    route = respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, _ = configured()
    await service.check()
    route.mock(return_value=_response("5"))

    await service.check()

    facts = await service.health_facts()
    assert (facts.error, facts.status, facts.version) == (None, "ok", "1.2.3")


@respx.mock
async def test_rate_limit_without_history_is_not_reported_as_healthy() -> None:
    respx.get(HEALTH).mock(return_value=_response("5"))
    service, _, _ = configured()
    await service.check()

    facts = await service.health_facts()
    assert facts.configured is True
    assert facts.error is not None  # неизвестно — не «всё хорошо»


async def test_probe_tolerates_unknown_fields_in_the_health_answer() -> None:
    """Терпимый читатель (Q-FIX35-4): новое необязательное поле `Health` не ломает проверку."""
    body = {**HEALTHY, "region": "uz-1", "build": {"sha": "abc"}}
    with respx.mock:
        respx.get(HEALTH).mock(return_value=httpx.Response(200, json=body))
        from app.integrations.erp import ErpConnection

        health = await HttpxErpProbe().health(ErpConnection(base_url=BASE, token="t"))
    assert health.status == "ok"
