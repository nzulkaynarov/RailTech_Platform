"""«Настройки · Оферта и политика» (ДВ-5): прокси к ERP, права `company.settings`, отказы ERP.

ERP на respx: решения (один действующий на вид, неизменность опубликованного, акцепты) за
ERP; здесь — права BFF (читает и правит директор и администратор, менеджер не входит), CSRF,
форма запросов к ERP и перевод отказов в 409/422 с подкодом.
"""

import json
from typing import Any, Literal

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL

EDITIONS = f"{ERP_URL}/api/v1/settings/legal-editions/"
ACCEPTANCES = f"{ERP_URL}/api/v1/settings/legal-acceptances/"
NOW = "2026-11-23T09:00:00Z"


def lang(ru: str) -> dict[str, str]:
    return {"ru": ru, "uz": f"{ru} (uz)", "en": f"{ru} (en)"}


def content(lead: str = "Правила {{company.name}}") -> dict[str, Any]:
    return {
        "title": lang("Условия"),
        "lead": lang(lead),
        "sections": [{"title": lang("1. Общие"), "body": lang("Текст")}],
    }


def erp_row(edition_id: int = 5, **over: Any) -> dict[str, Any]:
    return {
        "id": edition_id,
        "kind": "terms",
        "label": "2026-11-23",
        "status": "draft",
        "created_at": NOW,
        "published_at": None,
        "published_by": "",
        "retired_at": None,
        "acceptances_count": 0,
        **over,
    }


def erp_detail(edition_id: int = 5, **over: Any) -> dict[str, Any]:
    rendered = content("Правила ООО Тест")
    return {**erp_row(edition_id, **over), "content": content(), "rendered": rendered}


class ErpLegal:
    def __init__(self, be: Backends) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        router = be.router
        router.get(EDITIONS).mock(
            side_effect=lambda r: self._answer(
                "list", r, 200, {"results": [erp_row(), erp_row(6, kind="privacy")]}
            )
        )
        router.post(EDITIONS).mock(
            side_effect=lambda r: self._answer("create", r, 201, erp_detail())
        )
        router.get(url__regex=rf"^{EDITIONS}\d+/$").mock(
            side_effect=lambda r: self._answer("get", r, 200, erp_detail())
        )
        router.patch(url__regex=rf"^{EDITIONS}\d+/$").mock(
            side_effect=lambda r: self._answer("update", r, 200, erp_detail(label="2026-12-01"))
        )
        router.delete(url__regex=rf"^{EDITIONS}\d+/$").mock(
            side_effect=lambda r: self._answer("delete", r, 204, None)
        )
        router.post(url__regex=rf"^{EDITIONS}\d+/publish/$").mock(
            side_effect=lambda r: self._answer(
                "publish",
                r,
                200,
                erp_detail(status="current", published_at=NOW, published_by="Директор Д."),
            )
        )
        router.get(ACCEPTANCES).mock(
            side_effect=lambda r: self._answer(
                "acceptances",
                r,
                200,
                {
                    "count": 1,
                    "results": [
                        {
                            "id": 9,
                            "accepted_at": NOW,
                            "kind": "terms",
                            "edition": "2026-11-23",
                            "edition_id": 5,
                            "language": "uz",
                            "auth_method": "magic_link",
                            "contact": {"id": 3, "name": "Азамат", "email": "a@client.uz"},
                            "company": {"id": 4, "name": "ООО Клиент"},
                        }
                    ],
                },
            )
        )

    def _answer(self, name: str, request: httpx.Request, status: int, body: Any) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        self.calls.append((name, str(request.url), payload))
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    def last(self, name: str) -> tuple[str, Any]:
        for call in reversed(self.calls):
            if call[0] == name:
                return call[1], call[2]
        raise AssertionError(f"нет вызова {name}")


@pytest.fixture
def erp(be: Backends) -> ErpLegal:
    return ErpLegal(be)


async def test_readers_see_editions_text_and_acceptance_log(
    web: Web, erp: ErpLegal, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])

    listing = await web.client.get("/api/v1/admin/legal-editions")
    assert listing.status_code == 200, listing.text
    check(listing, "/admin/legal-editions", "get")
    assert [(i["id"], i["kind"], i["status"]) for i in listing.json()["items"]] == [
        ("5", "terms", "draft"),
        ("6", "privacy", "draft"),
    ]
    assert "published_at" not in listing.json()["items"][0]

    detail = await web.client.get("/api/v1/admin/legal-editions/5")
    check(detail, "/admin/legal-editions/{id}", "get")
    assert detail.json()["content"]["lead"]["ru"] == "Правила {{company.name}}"
    assert detail.json()["rendered"]["lead"]["ru"] == "Правила ООО Тест"

    log = await web.client.get(
        "/api/v1/admin/legal-acceptances?edition=5&q=азамат&page=2&page_size=10"
    )
    assert log.status_code == 200, log.text
    check(log, "/admin/legal-acceptances", "get")
    assert log.json()["total"] == 1
    assert log.json()["items"][0]["language"] == "uz"
    assert log.json()["items"][0]["contact"] == {
        "id": "3",
        "name": "Азамат",
        "email": "a@client.uz",
    }
    url = erp.last("acceptances")[0]
    assert "edition=5" in url
    assert "page=2" in url
    assert "page_size=10" in url


async def test_a_manager_has_no_section(web: Web, erp: ErpLegal) -> None:
    await web.login(["MANAGER"])
    for method, path in (
        ("GET", "/api/v1/admin/legal-editions"),
        ("GET", "/api/v1/admin/legal-editions/5"),
        ("GET", "/api/v1/admin/legal-acceptances"),
    ):
        assert (await web.client.request(method, path)).status_code == 403
    writes: list[tuple[Literal["POST", "PATCH", "DELETE"], str, dict[str, Any] | None]] = [
        ("POST", "/api/v1/admin/legal-editions", {"kind": "terms"}),
        ("PATCH", "/api/v1/admin/legal-editions/5", {"label": "x"}),
        ("POST", "/api/v1/admin/legal-editions/5/publish", None),
        ("DELETE", "/api/v1/admin/legal-editions/5", None),
    ]
    for method, path, body in writes:
        assert (await web.send(method, path, json=body)).status_code == 403
    assert erp.calls == []


async def test_director_creates_edits_publishes_and_discards(
    web: Web, erp: ErpLegal, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])

    created = await web.send("POST", "/api/v1/admin/legal-editions", json={"kind": "terms"})
    assert created.status_code == 201, created.text
    check(created, "/admin/legal-editions", "post")
    assert erp.last("create")[1] == {"kind": "terms"}

    patched = await web.send(
        "PATCH",
        "/api/v1/admin/legal-editions/5",
        json={"label": "2026-12-01", "content": content("Новое")},
    )
    assert patched.status_code == 200, patched.text
    check(patched, "/admin/legal-editions/{id}", "patch")
    assert erp.last("update")[1]["content"]["lead"]["ru"] == "Новое"
    assert erp.last("update")[1]["label"] == "2026-12-01"

    published = await web.send("POST", "/api/v1/admin/legal-editions/5/publish")
    assert published.status_code == 200, published.text
    check(published, "/admin/legal-editions/{id}/publish", "post")
    assert published.json()["status"] == "current"
    assert published.json()["published_by"] == "Директор Д."

    deleted = await web.send("DELETE", "/api/v1/admin/legal-editions/5")
    assert deleted.status_code == 204
    check(deleted, "/admin/legal-editions/{id}", "delete")


async def test_writes_need_csrf_and_a_strict_body(web: Web, erp: ErpLegal) -> None:
    await web.login(["ADMIN"])
    assert (
        await web.send("POST", "/api/v1/admin/legal-editions", json={"kind": "terms"}, csrf="wrong")
    ).status_code == 403
    assert (
        await web.send("POST", "/api/v1/admin/legal-editions", json={"kind": "cookies"})
    ).status_code == 422
    assert (await web.send("PATCH", "/api/v1/admin/legal-editions/5", json={})).status_code == 422
    assert (
        await web.send("PATCH", "/api/v1/admin/legal-editions/5", json={"status": "current"})
    ).status_code == 422
    assert (await web.send("POST", "/api/v1/admin/legal-editions/abc/publish")).status_code == 422
    assert erp.calls == []


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("LEGAL_DRAFT_EXISTS", "legal_draft_exists"),
        ("LEGAL_EDITION_PUBLISHED", "legal_edition_published"),
        ("LEGAL_LABEL_TAKEN", "legal_label_taken"),
    ],
)
async def test_erp_conflicts_become_409_with_a_reason(
    web: Web, be: Backends, erp: ErpLegal, check: ContractChecker, code: str, reason: str
) -> None:
    await web.login(["ADMIN"])
    be.router.post(url__regex=rf"^{EDITIONS}\d+/publish/$").mock(
        return_value=httpx.Response(409, json={"detail": code})
    )

    response = await web.send("POST", "/api/v1/admin/legal-editions/5/publish")

    assert response.status_code == 409
    check(response, "/admin/legal-editions/{id}/publish", "post")
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["details"]["reason"] == reason


async def test_erp_refusal_of_the_text_is_a_422(web: Web, be: Backends, erp: ErpLegal) -> None:
    await web.login(["ADMIN"])
    be.router.patch(url__regex=rf"^{EDITIONS}\d+/$").mock(
        return_value=httpx.Response(400, json={"detail": "VALIDATION_ERROR"})
    )

    response = await web.send("PATCH", "/api/v1/admin/legal-editions/5", json={"label": "x"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
