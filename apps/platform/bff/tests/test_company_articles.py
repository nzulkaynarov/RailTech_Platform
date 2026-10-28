"""Статьи компании (W18A-P5, B-079): прокси к CRM, права раздела `admin`, перевод ошибок.

CRM на respx: решения (черновик/опубликовано, журнал, границы длины) за CRM, здесь — права BFF
(читать опубликованные — любой сотрудник, черновики — `admin` от чтения, править — `admin` полный),
CSRF, форма запросов к CRM и перевод ошибок значений в 422 с полем и подкодом.
"""

import json
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL

ADMIN = f"{CRM_URL}/api/v1/company-articles"
MINE = f"{CRM_URL}/api/v1/me/company-articles"
NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC).isoformat().replace("+00:00", "Z")


def crm_article(article_id: int = 5, **over: Any) -> dict[str, Any]:
    return {
        "id": article_id,
        "title": "Кто согласует договор",
        "body": "## Шаги\n\n- юрист\n- директор",
        "language": "ru",
        "status": "draft",
        "created_by_name": "Админ",
        "updated_by_name": "Админ",
        "created_at": NOW,
        "updated_at": NOW,
        "published_at": None,
        **over,
    }


def error(status: int, code: str, reason: str | None = None, **details: Any) -> httpx.Response:
    body = {
        "code": code,
        "message": code,
        "details": {**({"reason": reason} if reason else {}), **details},
    }
    return httpx.Response(status, json=body)


class CrmArticles:
    def __init__(self, be: Backends) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        router = be.router
        published = crm_article(status="published", published_at=NOW)
        router.get(MINE).mock(
            side_effect=lambda r: self._answer("mine", r, 200, {"items": [published]})
        )
        router.get(ADMIN).mock(
            side_effect=lambda r: self._answer(
                "list", r, 200, {"items": [crm_article(6), published]}
            )
        )
        router.post(ADMIN).mock(side_effect=lambda r: self._answer("create", r, 201, crm_article()))
        router.patch(url__regex=rf"^{ADMIN}/\d+$").mock(
            side_effect=lambda r: self._answer("update", r, 200, crm_article(title="Новое имя"))
        )
        router.post(url__regex=rf"^{ADMIN}/\d+/publish$").mock(
            side_effect=lambda r: self._answer("publish", r, 200, published)
        )
        router.post(url__regex=rf"^{ADMIN}/\d+/unpublish$").mock(
            side_effect=lambda r: self._answer("unpublish", r, 200, crm_article())
        )
        router.delete(url__regex=rf"^{ADMIN}/\d+$").mock(
            side_effect=lambda r: self._answer("delete", r, 204, None)
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
def crm(be: Backends) -> CrmArticles:
    return CrmArticles(be)


async def test_every_employee_reads_published_articles_for_help(
    web: Web, crm: CrmArticles, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/help/company-articles")

    assert response.status_code == 200, response.text
    check(response, "/help/company-articles", "get")
    [item] = response.json()["items"]
    assert (item["id"], item["status"], item["language"]) == (5, "published", "ru")
    assert item["body"].startswith("## Шаги")
    assert crm.last("mine")[0] == MINE


async def test_help_list_needs_a_session(web: Web, crm: CrmArticles) -> None:
    response = await web.client.get("/api/v1/help/company-articles")

    assert response.status_code == 401
    assert crm.calls == []


async def test_admin_list_with_drafts_is_for_admin_readers_only(
    web: Web, crm: CrmArticles, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    denied = await web.client.get("/api/v1/admin/company-articles")
    assert denied.status_code == 403
    assert crm.calls == []

    await web.login(["DIRECTOR"])  # директор читает черновики
    response = await web.client.get("/api/v1/admin/company-articles")

    assert response.status_code == 200, response.text
    check(response, "/admin/company-articles", "get")
    assert [a["status"] for a in response.json()["items"]] == ["draft", "published"]
    assert "published_at" not in response.json()["items"][0]


async def test_only_admin_full_creates_edits_publishes_and_deletes(
    web: Web, crm: CrmArticles, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    writes: list[tuple[Literal["POST", "PATCH", "DELETE"], str, dict[str, str] | None]] = [
        ("POST", "/api/v1/admin/company-articles", {"title": "Т", "body": "Текст"}),
        ("PATCH", "/api/v1/admin/company-articles/5", {"title": "Новое"}),
        ("POST", "/api/v1/admin/company-articles/5/publish", None),
        ("POST", "/api/v1/admin/company-articles/5/unpublish", None),
        ("DELETE", "/api/v1/admin/company-articles/5", None),
    ]
    for method, path, body in writes:
        denied = await web.send(method, path, json=body)
        assert denied.status_code == 403, (method, path)
    assert crm.calls == []

    await web.login(["ADMIN"])
    created = await web.send(
        "POST",
        "/api/v1/admin/company-articles",
        json={"title": "Кто согласует договор", "body": "## Шаги", "language": "uz"},
    )
    assert created.status_code == 201, created.text
    check(created, "/admin/company-articles", "post")
    assert crm.last("create")[1] == {
        "title": "Кто согласует договор",
        "body": "## Шаги",
        "language": "uz",
    }

    updated = await web.send("PATCH", "/api/v1/admin/company-articles/5", json={"title": "Новое"})
    check(updated, "/admin/company-articles/{id}", "patch")
    assert crm.last("update")[1] == {"title": "Новое"}
    assert crm.last("update")[0].endswith("/company-articles/5")

    published = await web.send("POST", "/api/v1/admin/company-articles/5/publish")
    check(published, "/admin/company-articles/{id}/publish", "post")
    assert published.json()["status"] == "published"
    back = await web.send("POST", "/api/v1/admin/company-articles/5/unpublish")
    check(back, "/admin/company-articles/{id}/unpublish", "post")
    assert back.json()["status"] == "draft"

    deleted = await web.send("DELETE", "/api/v1/admin/company-articles/5")
    assert deleted.status_code == 204
    check(deleted, "/admin/company-articles/{id}", "delete")
    assert crm.last("delete")[0].endswith("/company-articles/5")


async def test_writes_need_csrf_and_a_strict_body(web: Web, crm: CrmArticles) -> None:
    await web.login(["ADMIN"])

    no_csrf = await web.send(
        "POST", "/api/v1/admin/company-articles", json={"title": "Т", "body": "x"}, csrf="wrong"
    )
    assert no_csrf.status_code == 403
    extra = await web.send(
        "POST",
        "/api/v1/admin/company-articles",
        json={"title": "Т", "body": "x", "status": "published"},
    )
    assert extra.status_code == 422  # опубликовать при создании нельзя: отдельное действие
    bad_language = await web.send(
        "POST", "/api/v1/admin/company-articles", json={"title": "Т", "body": "x", "language": "de"}
    )
    assert bad_language.status_code == 422
    bad_id = await web.send("POST", "/api/v1/admin/company-articles/0/publish")
    assert bad_id.status_code == 422
    assert crm.calls == []


async def test_body_is_passed_through_untouched_including_html(web: Web, crm: CrmArticles) -> None:
    await web.login(["ADMIN"])
    text = "<script>alert(1)</script> [x](javascript:alert(1))"

    response = await web.send(
        "POST", "/api/v1/admin/company-articles", json={"title": "Т", "body": text}
    )

    assert response.status_code == 201
    assert (
        crm.last("create")[1]["body"] == text
    )  # BFF ничего не «чистит» молча: рендер SPA не исполняет HTML


async def test_value_errors_of_crm_become_422_with_field_and_reason(
    web: Web, be: Backends, crm: CrmArticles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    be.router.post(ADMIN).mock(
        return_value=error(422, "validation_failed", "article_title_empty", field="title")
    )

    response = await web.send(
        "POST", "/api/v1/admin/company-articles", json={"title": " ", "body": "x"}
    )

    assert response.status_code == 422
    check(response, "/admin/company-articles", "post")
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["message"] == "Напишите заголовок."
    assert body["details"] == {"fields": ["title"], "reason": "article_title_empty"}


async def test_unknown_article_is_a_404_on_every_action(
    web: Web, be: Backends, crm: CrmArticles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    be.router.patch(url__regex=rf"^{ADMIN}/\d+$").mock(return_value=error(404, "not_found"))
    be.router.post(url__regex=rf"^{ADMIN}/\d+/publish$").mock(return_value=error(404, "not_found"))
    be.router.delete(url__regex=rf"^{ADMIN}/\d+$").mock(return_value=error(404, "not_found"))

    patch = await web.send("PATCH", "/api/v1/admin/company-articles/99", json={"title": "Т"})
    publish = await web.send("POST", "/api/v1/admin/company-articles/99/publish")
    delete = await web.send("DELETE", "/api/v1/admin/company-articles/99")

    for response in (patch, publish, delete):
        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
    check(patch, "/admin/company-articles/{id}", "patch")


async def test_crm_down_is_a_503(web: Web, be: Backends, crm: CrmArticles) -> None:
    await web.login(["MANAGER"])
    be.router.get(MINE).mock(side_effect=httpx.ConnectError("down"))

    response = await web.client.get("/api/v1/help/company-articles")

    assert response.status_code == 503
    assert response.json()["source"] == "crm"
