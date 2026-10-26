"""Попытка доставки: запрос, отправка (httpx), итог по L3 — общая часть адаптеров SQLAlchemy и Django."""

from __future__ import annotations

import asyncio
import json
import random
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import httpx

from .policy import RETRY_AFTER_STATUSES, BreakerPolicy, RetryPolicy, Verdict, classify_status, parse_retry_after
from .signing import signed_headers

ERROR_LIMIT = 500
#: Сколько простаивающих соединений держит клиент шины между попытками.
KEEPALIVE_CONNECTIONS = 50


def delivery_limits() -> httpx.Limits:
    """Пул соединений клиента шины — без общего потолка (по умолчанию httpx — 100).

    Один клиент обслуживает всех подписчиков процесса. Общий потолок делает пул узким местом: медленные ответы одного
    подписчика занимают его весь, и запрос быстрого ждёт свободного соединения — конца чужого ответа (W11C-G-1, замер
    W13-A0: 3,6 с до platform-bff). Границу ставит не пул, а свой предел на подписчика
    (`BusConfig.subscriber_connections`, семафор в шине): медленный подписчик не может занять сокеты другого, а сокетов
    в процессе не больше «подписчики × предел»."""
    return httpx.Limits(max_connections=None, max_keepalive_connections=KEEPALIVE_CONNECTIONS)


def encode_body(envelope: Mapping[str, Any]) -> bytes:
    """Тело запроса: конверт JSON без пробелов, UTF-8 (подпись считается по этим байтам)."""
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def clip(text: str, limit: int = ERROR_LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(frozen=True)
class Claimed:
    """Доставка, взятая воркером в аренду (`in_flight` до `lease_until`)."""

    id: int
    event_id: uuid.UUID
    event_type: str
    subscriber: str
    attempts: int
    lease_token: uuid.UUID
    probe: bool = False
    #: Проба взяла доставку раньше её срока (подписчик на паузе, готовых доставок нет): срок повтора, который неудача
    #: пробы не двигает и попытку не сжигает.
    early_until: datetime | None = None


@dataclass(frozen=True)
class Attempt:
    url: str
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class AttemptResult:
    verdict: Verdict
    status_code: int | None
    error: str | None
    retry_after: float | None = None


class OutcomeKind(StrEnum):
    DELIVERED = "delivered"
    RETRY = "retry"
    DEAD = "dead"
    #: Попытка не состоялась по нашей причине (нет секрета, нет подписчика в файле): попытка не засчитывается.
    POSTPONE = "postpone"


class BreakerEffect(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    NONE = "none"


@dataclass(frozen=True)
class Outcome:
    kind: OutcomeKind
    next_attempt_at: datetime | None = None
    status_code: int | None = None
    error: str | None = None
    breaker: BreakerEffect = BreakerEffect.NONE


def build_attempt(envelope: Mapping[str, Any], *, publisher: str, url: str, secret: str, now: datetime) -> Attempt:
    body = encode_body(envelope)
    headers = signed_headers(
        publisher=publisher,
        event_id=str(envelope["id"]),
        body=body,
        secret=secret,
        now=now,
        correlation_id=envelope.get("correlationid"),
        traceparent=envelope.get("traceparent"),
    )
    return Attempt(url=url, headers=headers, body=body)


def result_from_response(response: httpx.Response, now: datetime) -> AttemptResult:
    verdict = classify_status(response.status_code)
    if verdict is Verdict.DELIVERED:
        return AttemptResult(verdict, response.status_code, None)
    retry_after = (
        parse_retry_after(response.headers.get("Retry-After"), now)
        if response.status_code in RETRY_AFTER_STATUSES
        else None
    )
    try:
        text = response.text
    except (UnicodeDecodeError, httpx.ResponseNotRead):
        text = ""
    return AttemptResult(verdict, response.status_code, clip(f"HTTP {response.status_code}: {text}"), retry_after)


def result_from_exception(exc: BaseException) -> AttemptResult:
    return AttemptResult(Verdict.RETRY, None, clip(f"{type(exc).__name__}: {exc}"))


def deadline_result(seconds: float) -> AttemptResult:
    return AttemptResult(Verdict.RETRY, None, f"DeadlineExceeded: no complete response within {seconds:g} s")


async def send_async(
    client: httpx.AsyncClient,
    attempt: Attempt,
    http_timeout: float,
    now: datetime,
    *,
    deadline: float,
    gate: asyncio.Semaphore | None = None,
) -> AttemptResult:
    """Попытка с общим дедлайном `deadline` < аренды (таймаут httpx — на операцию, медленный ответ его обходит).

    `gate` — предел одновременных запросов к подписчику в процессе: ожидание места входит в дедлайн."""

    async def post() -> httpx.Response:
        if gate is None:
            return await client.post(attempt.url, content=attempt.body, headers=attempt.headers, timeout=http_timeout)
        async with gate:
            return await client.post(attempt.url, content=attempt.body, headers=attempt.headers, timeout=http_timeout)

    try:
        response = await asyncio.wait_for(post(), timeout=deadline)
    except TimeoutError:
        return deadline_result(deadline)
    except Exception as exc:  # noqa: BLE001 — любой сбой попытки (сеть, неверный адрес) — повтор, а не потеря пачки
        return result_from_exception(exc)
    return result_from_response(response, now)


def send_sync(
    client: httpx.Client,
    attempt: Attempt,
    http_timeout: float,
    now: datetime,
    *,
    gate: threading.BoundedSemaphore | None = None,
    deadline: float | None = None,
) -> AttemptResult:
    """Попытка из потока пула. `gate` — предел одновременных запросов к подписчику в процессе; места ждём не дольше
    `deadline` (иначе — итог «дедлайн», как у зависшего ответа)."""
    if gate is not None and not gate.acquire(timeout=deadline):
        return deadline_result(deadline or 0.0)
    try:
        response = client.post(attempt.url, content=attempt.body, headers=attempt.headers, timeout=http_timeout)
    except Exception as exc:  # noqa: BLE001 — любой сбой попытки (сеть, неверный адрес) — повтор, а не потеря пачки
        return result_from_exception(exc)
    finally:
        if gate is not None:
            gate.release()
    return result_from_response(response, now)


def decide_outcome(
    claimed: Claimed, result: AttemptResult, *, policy: RetryPolicy, now: datetime, rng: random.Random
) -> Outcome:
    """Итог попытки: доставлено, повтор по расписанию (или `Retry-After`), `dead`."""
    if result.verdict is Verdict.DELIVERED:
        return Outcome(OutcomeKind.DELIVERED, status_code=result.status_code, breaker=BreakerEffect.SUCCESS)
    if result.verdict is Verdict.DEAD:
        # Подписчик ответил, но событие он не примет никогда: счётчик предохранителя не растёт; ответ на пробную
        # доставку — признак, что подписчик жив: предохранитель закрывается.
        effect = BreakerEffect.SUCCESS if claimed.probe else BreakerEffect.NONE
        return Outcome(OutcomeKind.DEAD, status_code=result.status_code, error=result.error, breaker=effect)
    delay = policy.delay_after(claimed.attempts, rng, result.retry_after)
    if delay is None:
        return Outcome(
            OutcomeKind.DEAD,
            status_code=result.status_code,
            error=clip(f"retries exhausted after {claimed.attempts} attempts; last: {result.error}"),
            breaker=BreakerEffect.FAILURE,
        )
    return Outcome(
        OutcomeKind.RETRY,
        next_attempt_at=now + timedelta(seconds=delay),
        status_code=result.status_code,
        error=result.error,
        breaker=BreakerEffect.FAILURE,
    )


def early_probe_outcome(claimed: Claimed, outcome: Outcome) -> Outcome:
    """Неудача пробы, взявшей доставку раньше срока: пробу засчитывает предохранитель (пауза продлевается), а у самой
    доставки срок остаётся прежним и попытка не сгорает (`POSTPONE`). Успех и неповторяемый ответ — как обычно."""
    if claimed.early_until is None or outcome.breaker is not BreakerEffect.FAILURE:
        return outcome
    return Outcome(
        OutcomeKind.POSTPONE,
        next_attempt_at=claimed.early_until,
        status_code=outcome.status_code,
        error=outcome.error,
        breaker=BreakerEffect.FAILURE,
    )


def postpone(now: datetime, seconds: float, reason: str) -> Outcome:
    return Outcome(OutcomeKind.POSTPONE, next_attempt_at=now + timedelta(seconds=seconds), error=clip(reason))


def dead(reason: str) -> Outcome:
    return Outcome(OutcomeKind.DEAD, error=clip(reason))


def pause_until(now: datetime, breaker: BreakerPolicy) -> datetime:
    return now + timedelta(seconds=breaker.pause_seconds)
