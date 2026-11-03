"""OPS-CONSOLE: Django admin ERP под `/console/erp` на домене Платформы, остальной ERP — без изменений."""

import pytest
from asgiref.sync import async_to_sync
from asgiref.testing import ApplicationCommunicator
from django.core.asgi import get_asgi_application

from core.console_mount import ConsolePrefixMount, console_prefix

PREFIX = "/console/erp"


def _get(path: str, prefix: str = PREFIX) -> tuple[int, dict[bytes, bytes], bytes]:
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

    async def run() -> tuple[int, dict[bytes, bytes], bytes]:
        comm = ApplicationCommunicator(app, scope)
        await comm.send_input({"type": "http.request", "body": b"", "more_body": False})
        start = await comm.receive_output(10)
        body = b""
        while True:
            message = await comm.receive_output(10)
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        return start["status"], {k.lower(): v for k, v in start["headers"]}, body

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
