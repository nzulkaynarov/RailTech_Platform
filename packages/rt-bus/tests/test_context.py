"""Корреляция: заголовки → контекст → лог (stdlib и structlog)."""

from __future__ import annotations

import logging

import pytest

from rt_bus import CorrelationFilter, correlation, correlation_from_headers, get_correlation_id, structlog_processor


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
