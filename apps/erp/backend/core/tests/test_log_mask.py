"""FIX-66b: секреты не попадают в журнал и в Sentry (маска `core.log_mask`).

Токены в тестах явно фейковые (префикс `fix66b`), настоящих значений нет. Таблица «место → что утекало → как закрыто»
— `docs/runbooks/log-secrets.md`; тест на каждое место носит его имя.
"""

from __future__ import annotations

import io
import logging
import sys

import httpx
import pytest
from django.conf import settings

from core.log_mask import (
    NOISY_LOGGERS,
    REDACTED,
    SecretMaskFilter,
    mask_breadcrumb,
    mask_event,
    mask_secrets,
    mask_value,
)
from core.sentry_scrub import scrub_event

FAKE_BOT = "123456789:fix66b-FAKE_token_for_tests-0123456789ab"
FAKE_SIG = "fix66bFAKEsignature0123456789abcdef"
FAKE_KEY = "sk-fix66b-FAKE-gateway-key"
FAKE_JWT = "eyJfaXg2NmJmYWtl.eyJmaXg2NmJmYWtlcGF5bG9hZA.fix66bfakesig"


# ─── Маска: каждая ветка ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        # Telegram Bot API (httpx на INFO: «HTTP Request: GET https://api.telegram.org/bot<токен>/getMe»)
        (f'HTTP Request: GET https://api.telegram.org/bot{FAKE_BOT}/getMe "HTTP/1.1 200 OK"', FAKE_BOT),
        (f"url=/bot{FAKE_BOT}/sendMessage", FAKE_BOT),
        (f"токен {FAKE_BOT} в тексте без префикса bot", FAKE_BOT),
        # S3 presigned URL
        (
            f"GET https://s3.example.test/b/k?X-Amz-Algorithm=AWS4&X-Amz-Signature={FAKE_SIG}&X-Amz-Expires=600",
            FAKE_SIG,
        ),
        ("GET /b/k?X-Amz-Credential=fix66bAKIDFAKE%2F20261021%2Fus-east-1%2Fs3%2Faws4_request&x=1", "fix66bAKIDFAKE"),
        (f"?x-amz-security-token={FAKE_SIG}", FAKE_SIG),
        # Заголовки
        (f"Authorization: Bearer {FAKE_SIG}", FAKE_SIG),
        (f"X-Pairing-Proof: v1.1760000000.jti.{FAKE_SIG}", FAKE_SIG),  # доказательство bootstrap (M3-ERP-05)
        (f"headers={{'Authorization': 'Bearer {FAKE_SIG}', 'Accept': 'json'}}", FAKE_SIG),
        (f"authorization=Basic {FAKE_SIG}", FAKE_SIG),
        (f"X-Api-Key: {FAKE_SIG}", FAKE_SIG),
        (f"Request failed, bearer {FAKE_SIG} rejected", FAKE_SIG),
        (f"X-Telegram-Bot-Api-Secret-Token: {FAKE_SIG}", FAKE_SIG),
        # Ключи шлюза
        (f"Incorrect API key provided: {FAKE_KEY}", FAKE_KEY),
        # JWT (SSO)
        (f"SSO token {FAKE_JWT} rejected", FAKE_JWT),
        # userinfo в адресе
        ("connect to redis://:fix66bPASS@redis:6379/1 failed", "fix66bPASS"),
        ("GET https://fix66buser:fix66bPW@host.test/path", "fix66bPW"),
        # query: token=, code=, key=
        ("GET /api/x?token=fix66bTOKEN&b=1", "fix66bTOKEN"),
        ("GET /api/x?a=1&code=fix66bCODE", "fix66bCODE"),
        ("GET /api/x?key=fix66bKEY", "fix66bKEY"),
        ("GET /api/x?access_token=fix66bACCESS&refresh_token=fix66bREFRESH", "fix66bACCESS"),
        # тело JSON/repr
        ('{"access_token": "fix66bBODY", "ok": true}', "fix66bBODY"),
        ("{'password': 'fix66bPASSWORD'}", "fix66bPASSWORD"),
    ],
)
def test_secret_is_masked(text, secret):
    masked = mask_secrets(text)

    assert secret not in masked
    assert REDACTED in masked


@pytest.mark.parametrize(
    "text",
    [
        "GET /api/v1/quotes/12/ 200 12ms",
        "channel_take_rejected code=NOT_FOUND",  # code= вне строки запроса — код ошибки
        "GET /api/v1/items?page=2&page_size=50&ordering=-id",
        "contact info@example.test wrote about the robot123:abc",
        "https://example.test/path?next=/a@b",
        "Привет, мир",
        "Basic configuration loaded",  # «Basic» вне заголовка Authorization — обычное слово
        "",
    ],
)
def test_text_without_secrets_is_untouched(text):
    assert mask_secrets(text) == text


def test_mask_keeps_the_rest_of_the_line():
    text = f'GET https://api.telegram.org/bot{FAKE_BOT}/getMe "HTTP/1.1 200 OK"'

    assert mask_secrets(text) == 'GET https://api.telegram.org/bot[REDACTED]/getMe "HTTP/1.1 200 OK"'


def test_mask_value_walks_nested_structures():
    value = {"url": f"https://x.test/bot{FAKE_BOT}/getMe", "list": [f"Bearer {FAKE_SIG}", 5], "n": 1}

    masked = mask_value(value)

    assert FAKE_BOT not in repr(masked) and FAKE_SIG not in repr(masked)
    assert masked["n"] == 1 and masked["list"][1] == 5


def test_mask_value_keeps_the_container_type():
    """tuple остаётся tuple (единообразно с CRM; `exc_info=(type, exc, tb)` иначе ломается)."""
    masked = mask_value((ValueError, f"Bearer {FAKE_SIG}", None))

    assert isinstance(masked, tuple)
    assert masked[0] is ValueError
    assert FAKE_SIG not in repr(masked)
    assert isinstance(mask_value([f"Bearer {FAKE_SIG}"]), list)


# ─── Фильтр записей журнала ───────────────────────────────────────────────────


def _handler_with_filter(name: str, level: int = logging.DEBUG) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretMaskFilter())
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(level)
    return logger, stream


@pytest.fixture
def fresh_logger():
    created = []

    def make(name):
        created.append(name)
        return _handler_with_filter(name)

    yield make
    for name in created:
        lg = logging.getLogger(name)
        lg.handlers, lg.propagate = [], True
        lg.setLevel(logging.NOTSET)


def test_filter_masks_message_args_extra_and_traceback(fresh_logger):
    logger, stream = fresh_logger("fix66b.filter")
    try:
        raise RuntimeError(f"call https://api.telegram.org/bot{FAKE_BOT}/getMe failed")
    except RuntimeError:
        logger.warning(
            "probe %s", f"https://s3.test/k?X-Amz-Signature={FAKE_SIG}", exc_info=True, extra={"u": FAKE_KEY}
        )

    out = stream.getvalue()
    assert FAKE_BOT not in out and FAKE_SIG not in out
    assert "probe https://s3.test/k?X-Amz-Signature=[REDACTED]" in out
    assert "Traceback" in out  # трассировка не потеряна, только секрет в ней


def test_filter_masks_extras_for_the_json_formatter():
    from core.logging import JSONFormatter

    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
    record.target = f"https://api.telegram.org/bot{FAKE_BOT}/getMe"

    SecretMaskFilter().filter(record)

    assert FAKE_BOT not in JSONFormatter().format(record)


def test_json_formatter_does_not_bypass_the_mask_for_tracebacks():
    """Прод пишет JSON (`DJANGO_LOG_FORMAT=json`): `JSONFormatter` форматировал исключение заново, мимо маски."""
    from core.logging import JSONFormatter

    try:
        raise RuntimeError(f"call https://api.telegram.org/bot{FAKE_BOT}/getMe failed")
    except RuntimeError:
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "boom", (), sys.exc_info())

    SecretMaskFilter().filter(record)
    line = JSONFormatter().format(record)

    assert FAKE_BOT not in line
    assert "bot[REDACTED]" in line


def test_filter_never_drops_or_raises_on_broken_records():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "%s %s", ("only-one",), None)

    assert SecretMaskFilter().filter(record) is True


# ─── Настройка LOGGING ────────────────────────────────────────────────────────


def test_console_handler_carries_the_mask_filter():
    assert "mask_secrets" in settings.LOGGING["handlers"]["console"]["filters"]
    assert settings.LOGGING["filters"]["mask_secrets"]["()"] == "core.log_mask.SecretMaskFilter"


@pytest.mark.parametrize("name", NOISY_LOGGERS)
def test_noisy_http_libraries_are_quiet_by_default(name):
    """httpx/httpcore/urllib3/requests/botocore/... на INFO печатают URL каждого запроса — только WARNING и выше."""
    assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


def test_the_real_console_handler_masks_what_it_prints(monkeypatch):
    """Сквозной: запись в логгер библиотеки через настоящий `console` из LOGGING (а не свой обработчик теста)."""
    console = next(h for h in logging.getLogger().handlers if h.get_name() == "console")
    stream = io.StringIO()
    monkeypatch.setattr(console, "stream", stream)
    lg = logging.getLogger("fix66b.httpx_like")

    lg.warning('HTTP Request: GET https://api.telegram.org/bot%s/getMe "HTTP/1.1 200 OK"', FAKE_BOT)

    assert FAKE_BOT not in stream.getvalue()
    assert "bot[REDACTED]/getMe" in stream.getvalue()


def test_httpx_request_log_never_shows_the_bot_token_even_if_level_is_raised(monkeypatch):
    """Даже если кто-то включил httpx на INFO (DJANGO_LOG_LEVEL=DEBUG и т. п.), токен из пути маскируется."""
    console = next(h for h in logging.getLogger().handlers if h.get_name() == "console")
    stream = io.StringIO()
    monkeypatch.setattr(console, "stream", stream)
    httpx_logger = logging.getLogger("httpx")
    monkeypatch.setattr(httpx_logger, "level", logging.INFO)

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as client:
        client.get(f"https://api.telegram.org/bot{FAKE_BOT}/getMe")

    printed = stream.getvalue()
    assert "HTTP Request: GET" in printed  # запись есть (уровень поднят), но без токена
    assert FAKE_BOT not in printed


# ─── Celery: воркер подменяет обработчики корневого логгера ───────────────────


def test_celery_worker_loggers_get_the_mask_filter():
    """Celery на старте воркера/Beat заменяет обработчики корня своими (`worker_hijack_root_logger`) — фильтр из
    Django LOGGING на них не распространяется. Сигналы `after_setup_*logger` вешают маску на новые обработчики."""
    from celery.signals import after_setup_logger, after_setup_task_logger

    import core.celery  # noqa: F401 — подключает обработчики сигналов

    for signal in (after_setup_logger, after_setup_task_logger):
        logger = logging.getLogger(f"fix66b.celery.{signal.name}")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.handlers, logger.propagate = [handler], False
        try:
            signal.send(
                sender=None, logger=logger, loglevel=logging.INFO, logfile=None, format="%(message)s", colorize=False
            )
            logger.warning("Task retry: Bearer %s", FAKE_SIG)
        finally:
            logger.handlers, logger.propagate = [], True
        assert FAKE_SIG not in stream.getvalue(), signal.name


# ─── Sentry ───────────────────────────────────────────────────────────────────


def _event_with_secrets() -> dict:
    return {
        "message": f"call failed: https://api.telegram.org/bot{FAKE_BOT}/getMe",
        "request": {
            "url": f"https://erp.test/api/x?token={FAKE_SIG}",
            "query_string": f"code={FAKE_SIG}&page=1",
            "headers": {"Authorization": f"Bearer {FAKE_SIG}", "Cookie": "sessionid=fix66b", "Accept": "json"},
            "data": {"password": "fix66b"},
        },
        "exception": {
            "values": [
                {
                    "type": "HTTPStatusError",
                    "value": f"Client error '401' for url 'https://s3.test/k?X-Amz-Signature={FAKE_SIG}'",
                    "stacktrace": {"frames": [{"vars": {"url": f"https://x.test/bot{FAKE_BOT}/getMe"}}]},
                }
            ]
        },
        "logentry": {"message": "GET %s", "formatted": f"GET {FAKE_KEY}", "params": [FAKE_KEY]},
        "extra": {"note": f"Authorization: Bearer {FAKE_SIG}"},
        "breadcrumbs": {
            "values": [
                {
                    "category": "httplib",
                    "message": f"GET https://api.telegram.org/bot{FAKE_BOT}/getMe",
                    "data": {"url": f"https://api.telegram.org/bot{FAKE_BOT}/getMe", "http.query": f"token={FAKE_SIG}"},
                }
            ]
        },
    }


def test_sentry_event_after_hook_has_no_secrets():
    event = scrub_event(_event_with_secrets())

    dumped = repr(event)
    for secret in (FAKE_BOT, FAKE_SIG, FAKE_KEY):
        assert secret not in dumped
    assert event["request"]["headers"]["Accept"] == "json"  # лишнего не затёрто
    assert event["request"]["headers"]["Authorization"] == REDACTED
    assert "page=1" in event["request"]["query_string"]
    assert event["exception"]["values"][0]["type"] == "HTTPStatusError"


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Pairing-Proof": f"v1.1760000000.jti.{FAKE_SIG}", "Accept": "json"},
        {"x-pairing-proof": f"v1.1760000000.jti.{FAKE_SIG}", "Accept": "json"},
        [["X-Pairing-Proof", f"v1.1760000000.jti.{FAKE_SIG}"], ["Accept", "json"]],
    ],
    ids=["dict-canonical-case", "dict-lowercase", "list-of-pairs"],
)
def test_sentry_event_pairing_proof_header_is_redacted(headers):
    """M3-ERP-05: доказательство bootstrap (`X-Pairing-Proof`) не попадает в событие Sentry ни в каком виде заголовков."""
    event = scrub_event({"request": {"url": "https://erp.test/api/integration/v1/pairing/accept", "headers": headers}})

    assert FAKE_SIG not in repr(event)
    request_headers = event["request"]["headers"]
    pairs = request_headers.items() if isinstance(request_headers, dict) else request_headers
    by_name = {str(name).lower(): value for name, value in pairs}
    assert by_name["x-pairing-proof"] == REDACTED
    assert by_name["accept"] == "json"  # лишнего не затёрто


def test_sentry_event_hook_accepts_breadcrumbs_as_bare_list():
    event = {"breadcrumbs": [{"message": f"GET /bot{FAKE_BOT}/getMe", "data": {"url": f"/bot{FAKE_BOT}/x"}}]}

    assert FAKE_BOT not in repr(mask_event(event))


def test_sentry_breadcrumb_hook_masks_url_message_and_data():
    crumb = {
        "type": "http",
        "category": "httplib",
        "message": f"POST https://x.test/k?X-Amz-Signature={FAKE_SIG}",
        "data": {"url": f"https://api.telegram.org/bot{FAKE_BOT}/getMe", "status_code": 200},
    }

    result = mask_breadcrumb(crumb, {})

    assert FAKE_SIG not in repr(result) and FAKE_BOT not in repr(result)
    assert result["data"]["status_code"] == 200


def test_sentry_hooks_are_wired_in_settings_when_dsn_is_set():
    """Хуки подключены к `sentry_sdk.init`: проверка по исходнику настроек (в тестах DSN не задан — SDK не стартует)."""
    source = (settings.BASE_DIR / "core" / "settings" / "observability.py").read_text(encoding="utf-8")

    assert "before_send=scrub_event" in source
    assert "before_breadcrumb=mask_breadcrumb" in source


def test_sentry_hook_survives_garbage():
    assert scrub_event({"request": "not-a-dict", "breadcrumbs": 5, "exception": []}) is not None
    assert mask_breadcrumb(None) is None


# ─── Места из аудита (см. docs/runbooks/log-secrets.md) ───────────────────────


def _delivery_error_after_echo(body: str, status: int = 502) -> str:
    """Один сеанс доставки события подписчику, который отвечает `body`; возвращает `last_error` строки DLQ/повтора."""
    from django.db import transaction
    from integration.bus import get_bus
    from integration.bus_http import SecretMaskingTransport
    from integration.models import CrmClientMapping
    from integration.services import events
    from parties.models import Company
    from rt_bus.django.models import Delivery

    company = Company.objects.create(name="ООО FIX66b", inn="223456780")
    CrmClientMapping.objects.create(company=company, crm_client_id=66)
    with transaction.atomic():
        event = events.publish_event("invite.sent", company.id, {"channels": ["email"]})
    bus = get_bus()
    previous = bus._http
    bus._http = httpx.Client(
        transport=SecretMaskingTransport(httpx.MockTransport(lambda request: httpx.Response(status, text=body)))
    )
    try:
        bus.pump()
    finally:
        bus._http = previous
    return Delivery.objects.get(event_id=event.id, subscriber="crm").last_error or ""


@pytest.mark.django_db(transaction=True)
def test_bus_delivery_error_hides_secrets_from_the_subscribers_echo():
    """Журнал доставки шины пишет ответ подписчика; в нём бывает эхо заголовков запроса (FIX-66b)."""
    error = _delivery_error_after_echo(f"proxy rejected Authorization: Bearer {FAKE_SIG} for {FAKE_KEY}")
    assert error.startswith("HTTP 502")
    assert FAKE_SIG not in error and FAKE_KEY not in error


def test_telegram_init_data_validation_does_not_log_the_bot_token(caplog, settings):
    """Портал читает токен бота для проверки подписи initData; ни токен, ни производный ключ в журнал не уходят."""
    from portal.services.telegram_auth import validate_and_parse_init_data
    from rest_framework.exceptions import AuthenticationFailed

    settings.TELEGRAM_BOT_TOKEN = FAKE_BOT
    caplog.set_level(logging.DEBUG)

    with pytest.raises(AuthenticationFailed):
        validate_and_parse_init_data("auth_date=1&user=%7B%7D&hash=deadbeef")
    with pytest.raises(AuthenticationFailed):
        validate_and_parse_init_data("auth_date=9999999999&user=%7B%7D&hash=deadbeef")

    assert FAKE_BOT not in caplog.text


def test_ai_gateway_error_log_hides_the_key_echoed_by_the_gateway(monkeypatch):
    """LiteLLM на 401 эхом возвращает часть ключа в `error`; `_log_outcome` пишет его в журнал (до 300 символов)."""
    from ai.services import gateway
    from ai.services.ledger import CallUsage

    console = next(h for h in logging.getLogger().handlers if h.get_name() == "console")
    stream = io.StringIO()
    monkeypatch.setattr(console, "stream", stream)
    call = type("Call", (), {"feature": "intake"})()
    response = gateway.TransportResponse(
        status_code=401,
        headers={},
        payload={"error": f"Authentication Error: Incorrect API key provided: {FAKE_KEY}"},
    )

    gateway._log_outcome(call, "error", response, CallUsage(latency_ms=1))

    assert FAKE_KEY not in stream.getvalue()
    assert "AI intake error (http=401)" in stream.getvalue()


@pytest.mark.django_db(transaction=True)
def test_bus_error_masks_secret_cut_by_the_truncation():
    """Секрет на границе усечения ответа: маскировать нужно ДО усечения, иначе хвост <8 знаков уцелеет."""
    # Лимит библиотеки — 500 знаков вместе с префиксом «HTTP 502: »: «Bearer » и первые знаки подписи попадают в границу усечения.
    body = "a" * 477 + f" Bearer {FAKE_SIG}"
    error = _delivery_error_after_echo(body)
    assert FAKE_SIG[:4] not in error
    assert "Bearer [" in error  # маркер (обрезанный границей), а не знаки подписи
