"""ДВ-3: `GET /api/v1/setup/logo` — логотип своей компании без сессии.

Источник — публичные адреса портала ERP.
"""

import httpx

from tests.backends import Backends
from tests.conftest import Web
from tests.consts import ERP_URL

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>'
LOGO = "/media/companies/5/logo/a1.svg"


def _operator(be: Backends, logo_url: str | None) -> None:
    be.router.get(f"{ERP_URL}/api/portal/v1/operator").mock(
        return_value=httpx.Response(
            200, json={"name": "RailTech", "bot_username": None, "logo_url": logo_url}
        )
    )


async def test_logo_is_public_with_safe_headers(web: Web, be: Backends) -> None:
    _operator(be, LOGO)
    file = be.router.get(f"{ERP_URL}{LOGO}").mock(
        return_value=httpx.Response(200, content=SVG, headers={"content-type": "image/svg+xml"})
    )

    response = await web.client.get("/api/v1/setup/logo")

    assert response.status_code == 200
    assert response.content == SVG
    assert response.headers["content-type"] == "image/svg+xml"
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "authorization" not in file.calls.last.request.headers


async def test_no_logo_is_204_not_an_error(web: Web, be: Backends) -> None:
    _operator(be, None)

    response = await web.client.get("/api/v1/setup/logo")

    assert response.status_code == 204
    assert response.content == b""


async def test_foreign_path_is_not_fetched(web: Web, be: Backends) -> None:
    _operator(be, "/media/deals/1/secret.pdf")
    secret = be.router.get(f"{ERP_URL}/media/deals/1/secret.pdf").mock(
        return_value=httpx.Response(200)
    )

    response = await web.client.get("/api/v1/setup/logo")

    assert response.status_code == 204
    assert not secret.called


async def test_not_an_image_is_204(web: Web, be: Backends) -> None:
    _operator(be, LOGO)
    be.router.get(f"{ERP_URL}{LOGO}").mock(
        return_value=httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
    )

    assert (await web.client.get("/api/v1/setup/logo")).status_code == 204


async def test_logo_from_portal_address_is_served(web: Web, be: Backends) -> None:
    """ERP отдаёт адрес `/api/portal/v1/operator/logo?v=<версия>`, не путь в media."""
    path = "/api/portal/v1/operator/logo?v=a1b2c3d4e5"
    _operator(be, path)
    be.router.get(f"{ERP_URL}{path}").mock(
        return_value=httpx.Response(
            200, content=b"RIFFwebp", headers={"content-type": "image/webp"}
        )
    )

    response = await web.client.get("/api/v1/setup/logo")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
