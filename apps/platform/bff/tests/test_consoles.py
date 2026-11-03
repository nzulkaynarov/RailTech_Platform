"""OPS-CONSOLE: служебные консоли через Платформу — список и проверка Caddy `forward_auth`."""

import httpx
import pytest

from app.api.consoles import AUDIT_WINDOW_SECONDS, enabled_consoles
from app.config import Settings
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL

AUDIT = f"{CRM_URL}/api/v1/audit/console-open"


@pytest.fixture(autouse=True)
def consoles_on(settings: Settings) -> None:
    settings.consoles = "litellm,erp"


def assert_no_store(response: httpx.Response) -> None:
    assert response.headers.get("cache-control") == "no-store", response.headers


def test_enabled_consoles_keep_catalog_order_and_drop_unknown() -> None:
    assert enabled_consoles(" erp , litellm,rustfs,,") == ["litellm", "erp"]
    assert enabled_consoles("") == []


async def test_anonymous_gets_401_and_nothing_is_cached(web: Web, check: ContractChecker) -> None:
    response = await web.client.get("/api/v1/consoles/litellm/auth")

    assert response.status_code == 401
    check(response, "/consoles/{key}/auth", "get")
    assert_no_store(response)


@pytest.mark.parametrize("role", ["MANAGER", "DIRECTOR"])
async def test_employee_without_admin_full_gets_403(
    web: Web, check: ContractChecker, role: str
) -> None:
    await web.login([role])

    response = await web.client.get("/api/v1/consoles/litellm/auth")

    assert response.status_code == 403
    check(response, "/consoles/{key}/auth", "get")
    assert_no_store(response)
    listing = await web.client.get("/api/v1/admin/consoles")
    assert listing.status_code == 403


async def test_admin_passes_and_the_first_open_is_audited_once(
    web: Web, check: ContractChecker
) -> None:
    audit = web.be.router.post(AUDIT).respond(204)
    await web.login(["ADMIN"])

    first = await web.client.get("/api/v1/consoles/litellm/auth")
    again = await web.client.get("/api/v1/consoles/litellm/auth")

    assert (first.status_code, again.status_code) == (204, 204)
    check(first, "/consoles/{key}/auth", "get")
    assert_no_store(first)
    assert audit.call_count == 1
    assert audit.calls.last.request.content == b'{"console":"litellm"}'
    # Окно прошло — новое открытие, новая запись; другая консоль — своя запись.
    web.clock.t += AUDIT_WINDOW_SECONDS + 1
    await web.client.get("/api/v1/consoles/litellm/auth")
    await web.client.get("/api/v1/consoles/erp/auth")
    assert audit.call_count == 3


async def test_journal_failure_does_not_close_the_console_and_is_retried(web: Web) -> None:
    audit = web.be.router.post(AUDIT).mock(side_effect=[httpx.Response(503), httpx.Response(204)])
    await web.login(["ADMIN"])

    assert (await web.client.get("/api/v1/consoles/erp/auth")).status_code == 204
    assert (await web.client.get("/api/v1/consoles/erp/auth")).status_code == 204
    assert audit.call_count == 2


async def test_disabled_or_unknown_console_is_404(
    web: Web, check: ContractChecker, settings: Settings
) -> None:
    settings.consoles = "litellm"
    await web.login(["ADMIN"])

    for key in ("erp", "rustfs"):
        response = await web.client.get(f"/api/v1/consoles/{key}/auth")
        assert response.status_code == 404, key
        assert_no_store(response)
    check(response, "/consoles/{key}/auth", "get")


async def test_admin_lists_enabled_consoles(
    web: Web, check: ContractChecker, settings: Settings
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/admin/consoles")

    assert response.status_code == 200
    check(response, "/admin/consoles", "get")
    assert response.json() == {
        "items": [
            {"key": "litellm", "url": "/console/litellm/ui/"},
            {"key": "erp", "url": "/console/erp/admin/"},
        ]
    }
    settings.consoles = ""
    assert (await web.client.get("/api/v1/admin/consoles")).json() == {"items": []}


async def test_temporary_password_closes_the_console(web: Web) -> None:
    web.be.must_change = True
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/consoles/litellm/auth")

    assert response.status_code == 403
    assert response.json()["details"]["reason"] == "password_change_required"
