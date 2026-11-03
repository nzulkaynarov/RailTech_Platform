"""OPS-CONSOLE: Django admin ERP под `/console/erp` на домене Платформы, остальной ERP — без изменений."""

import pytest
from asgiref.sync import async_to_sync
from asgiref.testing import ApplicationCommunicator
from django.core.asgi import get_asgi_application

from core.console_mount import ConsolePrefixMount, console_prefix, scope_cookie_path

PREFIX = "/console/erp"


def _get(path: str, prefix: str = PREFIX) -> tuple[int, dict[bytes, bytes], bytes]:
    status, headers, body = _raw(path, prefix)
    return status, {k.lower(): v for k, v in headers}, body


def _set_cookies(path: str, prefix: str = PREFIX) -> list[str]:
    _, headers, _ = _raw(path, prefix)
    return [v.decode() for k, v in headers if k.lower() == b"set-cookie"]


def _raw(path: str, prefix: str = PREFIX) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    app = ConsolePrefixMount(get_asgi_application(), prefix)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }

    async def run() -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        comm = ApplicationCommunicator(app, scope)
        await comm.send_input({"type": "http.request", "body": b"", "more_body": False})
        start = await comm.receive_output(10)
        body = b""
        while True:
            message = await comm.receive_output(10)
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        return start["status"], list(start["headers"]), body

    return async_to_sync(run)()


@pytest.mark.django_db
def test_admin_under_prefix_builds_links_and_redirects_under_prefix():
    status, headers, _ = _get(f"{PREFIX}/admin/")
    assert status == 302
    assert headers[b"location"].decode().startswith(f"{PREFIX}/admin/login/")

    status, _, body = _get(f"{PREFIX}/admin/login/")
    assert status == 200
    page = body.decode()
    assert f'action="{PREFIX}/admin/login/' in page or f"{PREFIX}/admin/login/" in page
    assert f"{PREFIX}/static/" in page


@pytest.mark.django_db
def test_only_admin_and_static_are_open_under_prefix():
    for path in (f"{PREFIX}/api/v1/health", f"{PREFIX}/api/integration/v1/health", f"{PREFIX}/bus/v1/events", PREFIX):
        status, _, _ = _get(path)
        assert status == 404, path


@pytest.mark.django_db
def test_requests_without_prefix_are_unchanged():
    status, headers, _ = _get("/admin/")
    assert status == 302
    assert headers[b"location"].decode().startswith("/admin/login/")
    # Обёртка выключена — префикс не распознаётся вовсе.
    status, _, _ = _get(f"{PREFIX}/admin/", prefix="")
    assert status == 404


def test_prefix_comes_from_environment(monkeypatch):
    monkeypatch.setenv("ERP_CONSOLE_PREFIX", "/console/erp/")
    assert console_prefix() == "/console/erp"
    monkeypatch.setenv("ERP_CONSOLE_PREFIX", "")
    assert console_prefix() == ""
    monkeypatch.setenv("ERP_CONSOLE_PREFIX", "console/erp")
    with pytest.raises(ValueError):
        console_prefix()


@pytest.mark.django_db
def test_console_cookies_are_scoped_to_the_prefix():
    """Сессия и CSRF Django admin под префиксом не видны SPA Платформы на Path=/."""
    cookies = _set_cookies(f"{PREFIX}/admin/login/")
    assert cookies, "страница входа ставит csrftoken"
    for cookie in cookies:
        assert f"Path={PREFIX}" in cookie, cookie
        assert "Path=/;" not in cookie and not cookie.endswith("Path=/"), cookie
    # Без префикса — прежний путь.
    plain = _set_cookies("/admin/login/")
    assert plain and all("Path=/" in c and PREFIX not in c for c in plain), plain


def test_scope_cookie_path_rewrites_only_root_path():
    assert (
        scope_cookie_path(b"csrftoken=a; Path=/; SameSite=Lax", PREFIX)
        == b"csrftoken=a; Path=/console/erp; SameSite=Lax"
    )
    assert scope_cookie_path(b"sessionid=b; HttpOnly; path=/", PREFIX) == b"sessionid=b; HttpOnly; path=/console/erp"
    assert scope_cookie_path(b"x=/; Path=/other", PREFIX) == b"x=/; Path=/other"
    assert scope_cookie_path(b"x=y; Path=/console/erp", PREFIX) == b"x=y; Path=/console/erp"
