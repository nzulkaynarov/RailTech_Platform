"""FIX-66b: секреты не попадают в журнал CRM и в Sentry (маска `app.security.log_mask`).

Токены в тестах явно фейковые (префикс `fix66b`), настоящих значений нет. Таблица «место → что
утекало → как закрыто» — `docs/runbooks/log-secrets.md`; тест на каждое место носит его имя.
"""

import io
import json
import logging
import re
from pathlib import Path

import httpx
import pytest
import structlog

from app.config import Settings
from app.log import configure_logging
from app.security.log_mask import (
    NOISY_LOGGERS,
    REDACTED,
    SecretMaskFilter,
    mask_breadcrumb,
    mask_secrets,
    mask_sentry_event,
    mask_value,
)

FAKE_BOT = "123456789:fix66b-FAKE_token_for_tests-0123456789ab"
FAKE_SIG = "fix66bFAKEsignature0123456789abcdef"
FAKE_KEY = "sk-fix66b-FAKE-gateway-key"
FAKE_JWT = "eyJfaXg2NmJmYWtl.eyJmaXg2NmJmYWtlcGF5bG9hZA.fix66bfakesig"


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        (
            f'HTTP Request: GET https://api.telegram.org/bot{FAKE_BOT}/getMe "HTTP/1.1 200 OK"',
            FAKE_BOT,
        ),
        (f"url=/bot{FAKE_BOT}/sendMessage", FAKE_BOT),
        (f"токен {FAKE_BOT} в тексте без префикса bot", FAKE_BOT),
        (
            f"GET https://s3.example.test/b/k?X-Amz-Algorithm=AWS4&X-Amz-Signature={FAKE_SIG}&X-Amz-Expires=600",
            FAKE_SIG,
        ),
        (
            "GET /b/k?X-Amz-Credential=fix66bAKIDFAKE%2F20261021%2Fus-east-1%2Fs3%2Faws4&x=1",
            "fix66bAKIDFAKE",
        ),
        (f"?x-amz-security-token={FAKE_SIG}", FAKE_SIG),
        (f"Authorization: Bearer {FAKE_SIG}", FAKE_SIG),
        (f"X-Pairing-Proof: v1.1760000000.jti.{FAKE_SIG}", FAKE_SIG),  # bootstrap (M3-ERP-05)
        (f"headers={{'Authorization': 'Bearer {FAKE_SIG}', 'Accept': 'json'}}", FAKE_SIG),
        (f"authorization=Basic {FAKE_SIG}", FAKE_SIG),
        (f"X-Api-Key: {FAKE_SIG}", FAKE_SIG),
        (f"Request failed, bearer {FAKE_SIG} rejected", FAKE_SIG),
        (f"X-Telegram-Bot-Api-Secret-Token: {FAKE_SIG}", FAKE_SIG),
        (f"Incorrect API key provided: {FAKE_KEY}", FAKE_KEY),
        (f"SSO token {FAKE_JWT} rejected", FAKE_JWT),
        ("connect to redis://:fix66bPASS@redis:6379/1 failed", "fix66bPASS"),
        ("GET https://fix66buser:fix66bPW@host.test/path", "fix66bPW"),
        ("GET /api/x?token=fix66bTOKEN&b=1", "fix66bTOKEN"),
        ("GET /api/x?a=1&code=fix66bCODE", "fix66bCODE"),
        ("GET /api/x?key=fix66bKEY", "fix66bKEY"),
        ("GET /api/x?access_token=fix66bACCESS&refresh_token=fix66bREFRESH", "fix66bACCESS"),
        ('{"access_token": "fix66bBODY", "ok": true}', "fix66bBODY"),
        ("{'password': 'fix66bPASSWORD'}", "fix66bPASSWORD"),
    ],
)
def test_secret_is_masked(text: str, secret: str) -> None:
    masked = mask_secrets(text)

    assert secret not in masked
    assert REDACTED in masked


@pytest.mark.parametrize(
    "text",
    [
        "GET /api/v1/leads/12 200",
        "channel_take_rejected code=NOT_FOUND",  # code= вне строки запроса — код ошибки
        "GET /api/v1/items?page=2&page_size=50&ordering=-id",
        "contact info@example.test wrote about the robot123:abc",
        "https://example.test/path?next=/a@b",
        "Привет, мир",
        "Basic configuration loaded",  # «Basic» вне заголовка Authorization — обычное слово
        "",
    ],
)
def test_text_without_secrets_is_untouched(text: str) -> None:
    assert mask_secrets(text) == text


def test_mask_keeps_the_rest_of_the_line() -> None:
    text = f'GET https://api.telegram.org/bot{FAKE_BOT}/getMe "HTTP/1.1 200 OK"'

    assert (
        mask_secrets(text) == 'GET https://api.telegram.org/bot[REDACTED]/getMe "HTTP/1.1 200 OK"'
    )


def test_mask_value_walks_nested_structures() -> None:
    value = {
        "url": f"https://x.test/bot{FAKE_BOT}/getMe",
        "list": [f"Bearer {FAKE_SIG}", 5],
        "n": 1,
    }

    masked = mask_value(value)

    assert FAKE_BOT not in repr(masked)
    assert FAKE_SIG not in repr(masked)
    assert masked["n"] == 1
    assert masked["list"][1] == 5


def test_mask_value_keeps_the_container_type() -> None:
    """tuple остаётся tuple: `exc_info=(type, exc, tb)` иначе перестаёт быть кортежем."""
    masked = mask_value((ValueError, f"Bearer {FAKE_SIG}", None))

    assert isinstance(masked, tuple)
    assert masked[0] is ValueError
    assert FAKE_SIG not in repr(masked)
    assert isinstance(mask_value([f"Bearer {FAKE_SIG}"]), list)


# ─── stdlib-фильтр ────────────────────────────────────────────────────────────


def test_filter_masks_message_args_extra_and_traceback() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretMaskFilter())
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("fix66b.filter")
    logger.handlers, logger.propagate = [handler], False
    try:
        try:
            raise RuntimeError(f"call https://api.telegram.org/bot{FAKE_BOT}/getMe failed")
        except RuntimeError:
            logger.warning(
                "probe %s",
                f"https://s3.test/k?X-Amz-Signature={FAKE_SIG}",
                exc_info=True,
                extra={"u": FAKE_KEY},
            )
    finally:
        logger.handlers, logger.propagate = [], True

    out = stream.getvalue()
    assert FAKE_BOT not in out
    assert FAKE_SIG not in out
    assert "probe https://s3.test/k?X-Amz-Signature=[REDACTED]" in out
    assert "Traceback" in out


def test_filter_never_drops_or_raises_on_broken_records() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "%s %s", ("only-one",), None)

    assert SecretMaskFilter().filter(record) is True


# ─── Конвейер журнала CRM (structlog + stdlib) ────────────────────────────────


@pytest.fixture
def json_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"log_format": "json", "log_level": "INFO"})


def _lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


@pytest.mark.parametrize("name", NOISY_LOGGERS)
def test_noisy_http_libraries_are_quiet_after_configure(json_settings: Settings, name: str) -> None:
    configure_logging(json_settings)

    assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


def test_stdlib_record_with_bot_token_is_masked(
    json_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """httpx на INFO: «HTTP Request: GET https://api.telegram.org/bot<токен>/getMe» (ревью #130)."""
    configure_logging(json_settings)

    logging.getLogger("some.lib").info(
        'HTTP Request: GET https://api.telegram.org/bot%s/getMe "200 OK"', FAKE_BOT
    )

    out = capsys.readouterr().out
    assert FAKE_BOT not in out
    assert "123456789" not in out
    # `MaskBotToken` (FIX-66) срабатывает раньше (`bot***`), общая маска — страховка.
    assert re.search(r"bot(\*\*\*|\[REDACTED\])/getMe", out)


def test_httpx_request_log_never_shows_the_bot_token_even_if_level_is_raised(
    json_settings: Settings, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_logging(json_settings)
    monkeypatch.setattr(logging.getLogger("httpx"), "level", logging.INFO)

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as client:
        client.get(f"https://api.telegram.org/bot{FAKE_BOT}/getMe")

    out = capsys.readouterr().out
    assert "HTTP Request: GET" in out
    assert FAKE_BOT not in out
    assert "AAH" not in out


def test_structlog_kwargs_are_masked_before_pii(
    json_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """PII-маска превращает «123456789» в [number], оставляя хвост токена — наша идёт раньше."""
    configure_logging(json_settings)

    structlog.get_logger("t").info(
        "probe", url=f"https://api.telegram.org/bot{FAKE_BOT}/getMe", note=FAKE_KEY
    )

    out = capsys.readouterr().out
    assert "fix66b-FAKE" not in out
    assert _lines_from(out)[-1]["url"] == "https://api.telegram.org/bot[REDACTED]/getMe"


def _lines_from(out: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_traceback_text_is_masked(
    json_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """`pii` считает `exception` безопасным ключом — текст исключения с URL уходил как есть."""
    configure_logging(json_settings)
    try:
        raise httpx.HTTPStatusError(
            f"Client error '401' for url 'https://api.telegram.org/bot{FAKE_BOT}/getMe'",
            request=httpx.Request("GET", f"https://api.telegram.org/bot{FAKE_BOT}/getMe"),
            response=httpx.Response(401),
        )
    except httpx.HTTPStatusError:
        structlog.get_logger("t").warning("probe_failed", exc_info=True)

    record = _lines(capsys)[-1]
    assert FAKE_BOT not in json.dumps(record)
    assert "fix66b-FAKE" not in json.dumps(record)
    assert "Traceback" in str(record["exception"])


def _raise_with_secret() -> ValueError:
    try:
        raise ValueError(f"upstream said Authorization: Bearer {FAKE_SIG} is bad")
    except ValueError as exc:
        return exc


@pytest.mark.parametrize(
    "as_tuple", [False, True], ids=["exc_info=exc", "exc_info=(type, exc, tb)"]
)
def test_stdlib_exc_info_outside_except_keeps_traceback_and_masks_it(
    json_settings: Settings, capsys: pytest.CaptureFixture[str], as_tuple: bool
) -> None:
    """Вне блока except `format_exc_info` берёт exc_info из записи: маска не ломает кортеж."""
    configure_logging(json_settings)
    exc = _raise_with_secret()
    exc_info = (type(exc), exc, exc.__traceback__) if as_tuple else exc

    logging.getLogger("t").warning("x failed", exc_info=exc_info)

    record = _lines(capsys)[-1]
    assert "Traceback" in str(record["exception"])
    assert "_raise_with_secret" in str(record["exception"])
    assert "ValueError" in str(record["exception"])
    assert FAKE_SIG not in json.dumps(record)


def test_uvicorn_access_line_with_query_secrets_is_masked(
    json_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(json_settings)

    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "10.0.0.1:1",
        "GET",
        f"/api/v1/x?token={FAKE_SIG}&page=1",
        "1.1",
        200,
    )

    out = capsys.readouterr().out
    assert FAKE_SIG not in out
    assert "page=1" in out


def test_console_renderer_is_masked_too(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(settings.model_copy(update={"log_format": "console", "log_level": "INFO"}))

    logging.getLogger("x").info("GET /b?X-Amz-Signature=%s", FAKE_SIG)

    assert FAKE_SIG not in capsys.readouterr().out


# ─── Sentry ───────────────────────────────────────────────────────────────────


def _event_with_secrets() -> dict[str, object]:
    return {
        "message": f"call failed: https://api.telegram.org/bot{FAKE_BOT}/getMe",
        "request": {
            "url": f"https://crm.test/api/x?token={FAKE_SIG}",
            "query_string": f"code={FAKE_SIG}&page=1",
            "headers": {
                "Authorization": f"Bearer {FAKE_SIG}",
                "Cookie": "refresh=fix66b",
                "Accept": "json",
            },
        },
        "exception": {
            "values": [
                {
                    "type": "HTTPStatusError",
                    "value": f"Client error '401' for url 'https://s3.test/k?X-Amz-Signature={FAKE_SIG}'",
                    "stacktrace": {
                        "frames": [{"vars": {"url": f"https://x.test/bot{FAKE_BOT}/getMe"}}]
                    },
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
                    "data": {
                        "url": f"https://api.telegram.org/bot{FAKE_BOT}/getMe",
                        "http.query": f"token={FAKE_SIG}",
                    },
                }
            ]
        },
    }


def test_sentry_event_after_hook_has_no_secrets() -> None:
    event = mask_sentry_event(_event_with_secrets())

    dumped = repr(event)
    for secret in (FAKE_BOT, FAKE_SIG, FAKE_KEY):
        assert secret not in dumped
    assert event["request"]["headers"]["Accept"] == "json"
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
def test_sentry_event_pairing_proof_header_is_redacted(headers: object) -> None:
    """M3-CRM-10: `X-Pairing-Proof` (доказательство bootstrap) не попадает в событие Sentry."""
    event = mask_sentry_event({"request": {"url": "https://crm.test/api/x", "headers": headers}})

    assert FAKE_SIG not in repr(event)
    request_headers = event["request"]["headers"]
    pairs = request_headers.items() if isinstance(request_headers, dict) else request_headers
    by_name = {str(name).lower(): value for name, value in pairs}
    assert by_name["x-pairing-proof"] == REDACTED
    assert by_name["accept"] == "json"


def test_sentry_event_hook_accepts_breadcrumbs_as_bare_list() -> None:
    event = {
        "breadcrumbs": [
            {"message": f"GET /bot{FAKE_BOT}/getMe", "data": {"url": f"/bot{FAKE_BOT}/x"}}
        ]
    }

    assert FAKE_BOT not in repr(mask_sentry_event(event))


def test_sentry_breadcrumb_hook_masks_url_message_and_data() -> None:
    crumb = {
        "type": "http",
        "message": f"POST https://x.test/k?X-Amz-Signature={FAKE_SIG}",
        "data": {"url": f"https://api.telegram.org/bot{FAKE_BOT}/getMe", "status_code": 200},
    }

    result = mask_breadcrumb(crumb, {})

    assert FAKE_SIG not in repr(result)
    assert FAKE_BOT not in repr(result)
    assert result["data"]["status_code"] == 200


def test_sentry_hooks_survive_garbage() -> None:
    assert (
        mask_sentry_event({"request": "not-a-dict", "breadcrumbs": 5, "exception": []}) is not None
    )
    assert mask_breadcrumb(None) is None


def test_sentry_init_in_crm_must_pass_both_hooks() -> None:
    """Sentry в CRM не подключён. Если подключат — `sentry_sdk.init` обязан получить оба хука."""
    app_dir = Path(__file__).resolve().parents[3] / "app"
    for path in app_dir.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if re.search(r"\bsentry_sdk\.init\(", source):
            assert "before_send=mask_sentry_event" in source, path
            assert "before_breadcrumb=mask_breadcrumb" in source, path


def test_structlog_secret_named_fields_are_redacted(
    json_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(json_settings)

    structlog.get_logger("t").info("login", access_token="fix66bOPAQUE", tokens_in=5, lead_id=7)

    record = _lines(capsys)[-1]
    assert record["access_token"] == REDACTED
    assert record["tokens_in"] == 5
    assert record["lead_id"] == 7
