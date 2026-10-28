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


# --- FIX-66: токен бота не попадает в журнал через stdlib-логгеры (httpx пишет URL запроса) -------

FAKE_TOKEN = "123456:fake-log-token-AAAA"  # фиктивный


async def test_httpx_requests_to_telegram_never_leak_the_token(
    json_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    import httpx
    import respx

    from app.integrations import external_probes as probes

    configure_logging(
        json_settings
    )  # уровень INFO: httpx иначе пишет «HTTP Request: GET …/bot<token>/…»
    api = "https://api.telegram.org"
    with respx.mock:
        respx.get(f"{api}/bot{FAKE_TOKEN}/getMe").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {"username": "rt_bot"}})
        )
        respx.get(f"{api}/bot{FAKE_TOKEN}/getWebhookInfo").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {"url": ""}})
        )
        async with httpx.AsyncClient() as client:
            await probes.telegram(client, FAKE_TOKEN)
    out = capsys.readouterr().out
    assert FAKE_TOKEN not in out
    assert "/bot123456:" not in out
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


@pytest.mark.parametrize("logger_name", ["httpx", "aiogram.client", "anything.else"])
def test_bot_token_is_masked_in_any_stdlib_record(
    json_settings: Settings, capsys: pytest.CaptureFixture[str], logger_name: str
) -> None:
    """Страховка поверх уровней: даже если кто-то включит INFO у клиента, токен маскируется."""
    configure_logging(json_settings)
    logging.getLogger(logger_name).warning(
        "HTTP Request: %s %s", "GET", f"https://api.telegram.org/bot{FAKE_TOKEN}/getMe"
    )
    out = capsys.readouterr().out
    assert FAKE_TOKEN not in out
    assert "/bot123456:" not in out
    assert "/bot***/getMe" in out


# --- B-006: extra журнала шины доходит до JSON-журнала -----------------------------------------


def test_bus_extra_fields_reach_the_json_log(
    json_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(json_settings)
    logging.getLogger("rt_bus").warning(
        "rt_bus_delivery_retry",
        extra={
            "subscriber": "eds",
            "event_id": "e-1",
            "attempt": 2,
            "status_code": 503,
            "error": "HTTP 503",
        },
    )
    logging.getLogger("rt_bus.receiver").warning(
        "rt_bus_receive_rejected", extra={"status_code": 401, "reason": "signature mismatch"}
    )
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    retry, rejected = lines[-2], lines[-1]
    assert retry["event"] == "rt_bus_delivery_retry"
    assert (retry["subscriber"], retry["event_id"], retry["attempt"]) == ("eds", "e-1", 2)
    assert (retry["status_code"], retry["error"]) == (503, "HTTP 503")
    assert (rejected["status_code"], rejected["reason"]) == (401, "signature mismatch")


def test_extra_of_other_loggers_is_not_copied(
    json_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(json_settings)
    logging.getLogger("uvicorn.error").warning(
        "started", extra={"status": "x", "color_message": "y"}
    )
    record = last_json_line(capsys)
    assert "status" not in record
    assert "color_message" not in record
