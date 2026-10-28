"""W-REL: версия Платформы («О системе»), отметки «Что нового» и версия в обращении."""

import json
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.release import release_label, release_of
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL, EDS_URL, ERP_URL

SHA = "1a2b3c4d5e6f708192a3b4c5d6e7f80912a3b4c5"


def settings_with(**env: str) -> Settings:
    return Settings(**env)  # type: ignore[arg-type]


# --- версия ---------------------------------------------------------------------------------------


def test_release_is_the_deploy_date_and_short_sha() -> None:
    release = release_of(
        settings_with(
            PLATFORM_RELEASE=SHA,
            PLATFORM_RELEASE_DATE="2026-10-28",
            PLATFORM_BUILD_SHA="ffffffffffffffffffffffffffffffffffffffff",
            PLATFORM_BUILD_DATE="2026-10-27",
        )
    )

    assert release.version == "2026.10.28"  # дата выкладки, не сборки
    assert release.sha == "1a2b3c4"  # тег выкладки, не sha сборки
    assert release_label(release) == "Платформа 2026.10.28 · 1a2b3c4"


def test_without_deploy_date_the_build_date_and_build_sha_are_used() -> None:
    release = release_of(
        settings_with(PLATFORM_BUILD_SHA=SHA, PLATFORM_BUILD_DATE="2026-10-27T09:15:00Z")
    )

    assert (release.version, release.sha) == ("2026.10.27", "1a2b3c4")


def test_local_build_is_dev_and_garbage_is_ignored() -> None:
    assert release_label(release_of(settings_with())) == "Платформа dev"
    odd = release_of(settings_with(PLATFORM_RELEASE="ci-only", PLATFORM_RELEASE_DATE="вчера"))
    assert (odd.version, odd.sha) == ("dev", None)


async def test_about_needs_a_session(web: Web) -> None:
    assert (await web.client.get("/api/v1/about")).status_code == 401


async def test_about_gives_the_release_and_each_service(
    web: Web, be: Backends, check: ContractChecker, settings: Settings
) -> None:
    settings.release, settings.release_date = SHA, "2026-10-28"
    be.router.get(f"{CRM_URL}/health").respond(200, json={"status": "ok"})
    be.router.get(f"{ERP_URL}/health/").respond(503)
    be.router.get(f"{EDS_URL}/health").respond(
        200, json={"status": "ok", "version": SHA, "checks": {"database": "ok"}}
    )
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/about")

    assert response.status_code == 200, response.text
    check(response, "/about", "get")
    body = response.json()
    assert body["release"] == {
        "version": "2026.10.28",
        "sha": "1a2b3c4",
        "released_at": "2026-10-28",
    }
    services = {s["key"]: s for s in body["services"]}
    assert [s["key"] for s in body["services"]] == ["bff", "crm", "erp", "eds"]
    assert services["bff"]["status"] == "ok"
    assert services["bff"]["version"]
    assert services["crm"] == {"key": "crm", "status": "ok"}  # health CRM версию не сообщает
    assert services["erp"] == {"key": "erp", "status": "fail"}
    assert services["eds"] == {"key": "eds", "status": "ok", "version": "1a2b3c4"}


async def test_about_without_eds_says_off(web: Web, be: Backends, check: ContractChecker) -> None:
    be.router.get(f"{CRM_URL}/health").respond(200)
    be.router.get(f"{ERP_URL}/health/").respond(200)
    await web.login(["MANAGER"])
    web.app.state.eds = None

    response = await web.client.get("/api/v1/about")

    check(response, "/about", "get")
    assert response.json()["release"] == {"version": "dev"}
    assert response.json()["services"][3] == {"key": "eds", "status": "disabled"}


# --- «Что нового» ---------------------------------------------------------------------------------


async def test_whats_new_marks_come_from_crm_and_are_saved_there(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    be.profile["whats_new_shown"] = None
    be.profile["whats_new_read"] = "2026-10-01"
    patches: list[dict[str, Any]] = []

    def patch_me(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        patches.append(body)
        be.profile.update(body)
        return httpx.Response(200, json=be.profile)

    be.crm_patch_me.mock(side_effect=patch_me)
    login = await web.login(["MANAGER"])
    me = login.json()["me"]
    assert (me["whats_new_shown"], me["whats_new_read"]) == (None, "2026-10-01")

    shown = await web.send("PUT", "/api/v1/me/whats-new", json={"shown": "2026-10-28"})

    assert shown.status_code == 200, shown.text
    check(shown, "/me/whats-new", "put")
    assert shown.json()["whats_new_shown"] == "2026-10-28"

    read = await web.send("PUT", "/api/v1/me/whats-new", json={"read": "2026-10-28"})
    assert read.json()["whats_new_read"] == "2026-10-28"
    assert patches == [{"whats_new_shown": "2026-10-28"}, {"whats_new_read": "2026-10-28"}]
    # Снимок сессии обновлён: следующий /me без похода в CRM знает об отметке.
    assert (await web.client.get("/api/v1/me")).json()["whats_new_read"] == "2026-10-28"


@pytest.mark.parametrize(
    "body", [{}, {"read": "вчера"}, {"shown": "2026-10-28", "extra": 1}, {"read": None}]
)
async def test_whats_new_rejects_empty_and_bad_marks(
    web: Web, be: Backends, body: dict[str, Any]
) -> None:
    await web.login(["MANAGER"])
    calls = len(be.crm_patch_me.calls)

    response = await web.send("PUT", "/api/v1/me/whats-new", json=body)

    assert response.status_code == 422
    assert len(be.crm_patch_me.calls) == calls


async def test_whats_new_needs_csrf(web: Web) -> None:
    await web.login(["MANAGER"])

    response = await web.send("PUT", "/api/v1/me/whats-new", json={"read": "2026-10-28"}, csrf="x")

    assert response.status_code == 403


async def test_profile_without_marks_gives_nulls(web: Web) -> None:
    me = (await web.login(["MANAGER"])).json()["me"]

    assert me["whats_new_shown"] is None
    assert me["whats_new_read"] is None


# --- версия в обращении ---------------------------------------------------------------------------


async def test_new_ticket_gets_the_version_line(web: Web, be: Backends, settings: Settings) -> None:
    settings.release, settings.release_date = SHA, "2026-10-28"
    sent: list[dict[str, Any]] = []

    def create(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(500)

    be.router.post(f"{CRM_URL}/api/v1/me/tickets").mock(side_effect=create)
    await web.login(["MANAGER"])

    await web.send("POST", "/api/v1/tickets", json={"subject": "error", "body": "  Сбой  "})
    await web.send("POST", "/api/v1/tickets", json={"subject": "error", "body": "я" * 3990})

    assert sent[0]["body"] == "Сбой\n\nВерсия: Платформа 2026.10.28 · 1a2b3c4"
    assert sent[1]["body"] == "я" * 3990  # строка не помещается в предел — текст как есть
