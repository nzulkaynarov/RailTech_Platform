"""Корреляция: заголовки → контекст → лог (stdlib и structlog)."""

from __future__ import annotations

import logging

import pytest

from rt_bus import (
    CorrelationFilter,
    correlation,
    correlation_from_headers,
    get_correlation_id,
    structlog_extra_processor,
    structlog_processor,
)


def test_from_headers() -> None:
    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    assert correlation_from_headers({"x-request-id": "req-1", "Traceparent": tp}) == ("req-1", tp)
    cid, tp2 = correlation_from_headers({"X-Request-ID": "bad id with spaces", "traceparent": "garbage"})
    assert len(cid) == 36
    assert tp2 is None


def test_context_is_scoped() -> None:
    assert get_correlation_id() is None
    with correlation("outer"):
        with correlation("inner"):
            assert get_correlation_id() == "inner"
        assert get_correlation_id() == "outer"
    assert get_correlation_id() is None


def test_log_filter_and_structlog(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("tests.context")
    handler = caplog.handler
    handler.addFilter(CorrelationFilter())
    try:
        with caplog.at_level(logging.INFO), correlation("req-7"):
            logger.info("inside")
        logger.warning("outside")
    finally:
        handler.removeFilter(handler.filters[-1])
    by_msg = {r.getMessage(): r for r in caplog.records}
    assert by_msg["inside"].correlation_id == "req-7"  # type: ignore[attr-defined]
    assert by_msg["outside"].correlation_id == "-"  # type: ignore[attr-defined]
    with correlation("req-8"):
        assert structlog_processor(None, "info", {"event": "x"})["correlation_id"] == "req-8"
    assert "correlation_id" not in structlog_processor(None, "info", {"event": "x"})


def _record(name: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(name, logging.WARNING, __file__, 1, "rt_bus_delivery_retry", None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_extra_processor_carries_bus_fields_of_a_stdlib_record_into_the_event() -> None:
    """B-006: поля `extra` журнала шины (причина, код ответа, подписчик, событие, попытка) доходят
    до JSON-журнала сервиса, а не теряются при переходе stdlib-записи в structlog."""
    record = _record(
        "rt_bus",
        subscriber="eds",
        event_id="7b2c",
        attempt=3,
        status_code=503,
        error="HTTP 503",
        reason="signature",
        secret_body="x",
    )
    event = structlog_extra_processor(None, "warning", {"event": "rt_bus_delivery_retry", "_record": record})
    assert event["subscriber"] == "eds"
    assert event["event_id"] == "7b2c"
    assert event["attempt"] == 3
    assert event["status_code"] == 503
    assert event["error"] == "HTTP 503"
    assert event["reason"] == "signature"
    assert "secret_body" not in event  # чужие поля записи не копируются


def test_extra_processor_ignores_other_loggers_and_keeps_existing_keys() -> None:
    other = _record("uvicorn.error", status="started", path="/x")
    assert "status" not in structlog_extra_processor(None, "info", {"event": "x", "_record": other})
    own = _record("rt_bus.receiver", reason="from record")
    kept = structlog_extra_processor(None, "info", {"event": "x", "reason": "explicit", "_record": own})
    assert kept["reason"] == "explicit"
    # нативная запись structlog (без `_record`) проходит без изменений
    assert structlog_extra_processor(None, "info", {"event": "x"}) == {"event": "x"}
