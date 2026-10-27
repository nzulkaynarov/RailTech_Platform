"""Мост в старые экраны (W15-H1, контракт 0.18.0): адреса старых фронтов и вход в старый ERP.

CRM — на respx; адрес и токен — как их выдаёт CRM (`redirect_url` из `ERP_FRONTEND_URL`).
Проверяется вывод адресов из адреса Платформы, приоритет настройки, схема только от доверенного
прокси и то, что токен не уходит в журнал.
"""

import httpx
import pytest

from app.bridge_url import derive_public_url, valid_public_url
from app.client_ip import parse_networks
from app.config import Settings
from tests.conftest import ContractChecker, Web

NETWORKS = parse_networks("10.0.0.0/8")


class TestDerive:
    def test_platform_label_becomes_crm_and_erp_with_same_port(self) -> None:
        got = derive_public_url(
            "platform.localhost:8088", None, None, NETWORKS, sibling="crm", request_scheme="http"
        )
        assert got == "http://crm.localhost:8088"

    def test_scheme_from_forwarded_proto_only_for_trusted_peer(self) -> None:
        args = ("platform.example.org", "https")
        trusted = derive_public_url(
            args[0], args[1], "10.1.2.3", NETWORKS, sibling="erp", request_scheme="http"
        )
        stranger = derive_public_url(
            args[0], args[1], "203.0.113.9", NETWORKS, sibling="erp", request_scheme="http"
        )
        assert trusted == "https://erp.example.org"
        assert stranger == "http://erp.example.org"

    @pytest.mark.parametrize(
        "host",
        [
            None,
            "",
            "localhost:8000",
            "127.0.0.1:8088",
            "platform",
            "crm.example.org",
            "platform.example.org:99999",
            "platform.exa mple.org",
            "platform.example.org/evil",
            "platform.example.org@evil.example",
            "pla\ttform.example.org",
        ],
    )
    def test_host_that_is_not_platform_dot_domain_gives_nothing(self, host: str | None) -> None:
        got = derive_public_url(host, None, None, NETWORKS, sibling="crm", request_scheme="http")
        assert got is None

    @pytest.mark.parametrize(
        ("url", "ok"),
        [
            ("http://crm.localhost:8088", True),
            ("https://crm.example.org", True),
            ("https://crm.example.org/", True),
            ("ftp://crm.example.org", False),
            ("https://crm.example.org/path", False),
            ("https://user:pw@crm.example.org", False),
            ("https://crm.example.org:abc", False),
            ("crm.example.org", False),
        ],
    )
    def test_configured_url_shape(self, url: str, ok: bool) -> None:
        assert valid_public_url(url) is ok

    def test_bad_configured_url_stops_startup(self) -> None:
        with pytest.raises(ValueError, match="публичный адрес"):
            Settings(PLATFORM_CRM_PUBLIC_URL="https://crm.example.org/path")


async def test_bridge_needs_session(web: Web) -> None:
    got = await web.client.get("/api/v1/bridge")
    assert got.status_code == 401


async def test_urls_derived_from_platform_host(web: Web, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    got = await web.client.get("/api/v1/bridge", headers={"Host": "platform.railtech.example:8088"})
    check(got, "/bridge", "get")
    assert got.json() == {
        "crm_url": "https://crm.railtech.example:8088",
        "erp_url": "https://erp.railtech.example:8088",
        "erp_sso": True,
    }
    assert got.headers["cache-control"] == "no-store"


async def test_no_urls_when_host_is_not_platform(web: Web, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    got = await web.client.get("/api/v1/bridge", headers={"Host": "intranet.example"})
    check(got, "/bridge", "get")
    assert got.json() == {"crm_url": None, "erp_url": None, "erp_sso": True}


async def test_configured_urls_win_over_derived(web: Web) -> None:
    web.app.state.settings = Settings(
        PLATFORM_CRM_PUBLIC_URL="https://old-crm.example.org/",
        PLATFORM_ERP_PUBLIC_URL="",
    )
    await web.login(["MANAGER"])
    got = await web.client.get("/api/v1/bridge", headers={"Host": "platform.example.org"})
    assert got.json()["crm_url"] == "https://old-crm.example.org"
    assert got.json()["erp_url"] == "https://erp.example.org"


async def test_erp_sso_false_without_erp_access(web: Web, check: ContractChecker) -> None:
    web.be.profile["platform_access"] = ["crm"]
    await web.login(["MANAGER"])
    got = await web.client.get("/api/v1/bridge")
    check(got, "/bridge", "get")
    assert got.json()["erp_sso"] is False
    denied = await web.send("POST", "/api/v1/bridge/erp-sso")
    check(denied, "/bridge/erp-sso", "post")
    assert denied.status_code == 403
    assert denied.json()["details"]["reason"] == "platform_access_denied"


async def test_erp_sso_gives_exchange_url_with_one_time_token(
    web: Web, check: ContractChecker, capsys: pytest.CaptureFixture[str]
) -> None:
    await web.login(["MANAGER"])
    before = web.be.crm_sso.call_count
    got = await web.send("POST", "/api/v1/bridge/erp-sso")
    check(got, "/bridge/erp-sso", "post")
    assert got.json() == {"url": "http://erp.test/sso#token=sso-token-1"}
    assert got.headers["cache-control"] == "no-store"
    assert web.be.crm_sso.call_count == before + 1
    sent: httpx.Request = web.be.crm_sso.calls.last.request
    assert sent.headers["authorization"].startswith("Bearer crm-access-")
    assert "sso-token-1" not in capsys.readouterr().out


async def test_erp_sso_requires_csrf(web: Web) -> None:
    await web.login(["MANAGER"])
    got = await web.send("POST", "/api/v1/bridge/erp-sso", csrf="wrong")
    assert got.status_code == 403
    assert got.json()["code"] == "CSRF_FAILED"


async def test_erp_sso_disabled_in_crm_is_forbidden_with_reason(
    web: Web, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    web.be.sso_status = 403
    got = await web.send("POST", "/api/v1/bridge/erp-sso")
    check(got, "/bridge/erp-sso", "post")
    assert got.status_code == 403
    assert got.json()["details"]["reason"] == "sso_disabled"


async def test_erp_sso_crm_down_is_503(web: Web, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    web.be.sso_status = 500
    got = await web.send("POST", "/api/v1/bridge/erp-sso")
    check(got, "/bridge/erp-sso", "post")
    assert got.status_code == 503


async def test_forbidden_until_temporary_password_is_changed(
    web: Web, check: ContractChecker
) -> None:
    web.be.must_change = True
    await web.login(["MANAGER"])
    got = await web.client.get("/api/v1/bridge")
    check(got, "/bridge", "get")
    assert got.status_code == 403
    assert got.json()["details"]["reason"] == "password_change_required"
