import json
import logging

import pytest
import structlog
from asgi_correlation_id import correlation_id

from app.config import Settings
from app.log import configure_logging


@pytest.fixture
def json_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"log_format": "json", "log_level": "INFO"})


def last_json_line(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    parsed: dict[str, object] = json.loads(lines[-1])
    return parsed


def test_structlog_event_is_json_with_request_id(
    json_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(json_settings)
    token = correlation_id.set("req-123")
    try:
        structlog.get_logger("test").info("lead_received", lead_id=42)
    finally:
        correlation_id.reset(token)
    record = last_json_line(capsys)
    assert record["event"] == "lead_received"
    assert record["lead_id"] == 42
    assert record["request_id"] == "req-123"
    assert record["level"] == "info"


def test_stdlib_logs_use_same_format(
    json_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(json_settings)
    logging.getLogger("uvicorn.error").warning("started")
    record = last_json_line(capsys)
    assert record["event"] == "started"
    assert record["logger"] == "uvicorn.error"


def test_reconfigure_does_not_duplicate_handlers(json_settings: Settings) -> None:
    configure_logging(json_settings)
    configure_logging(json_settings)
    names = [h.get_name() for h in logging.getLogger().handlers]
    assert names.count("structlog-stdout") == 1
