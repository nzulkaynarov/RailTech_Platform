"""Admin · Журнал аудита и журнал изменений роли (W13-A6, контракт 0.12.0): `GET /admin/audit`,
`GET /admin/roles/{id}/journal`.

CRM — на respx (`GET /api/v1/audit` с состоянием записей); ответы BFF проверяются по схемам
platform-bff.yaml. Решения о праве `audit:read` — за CRM: здесь — перевод параметров, форма ответа,
вырезание секретов и права раздела `admin` (директор читает, остальные — 403).
"""

from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL

AUDIT = f"{CRM_URL}/api/v1/audit"
AT = "2026-10-26T08:30:00Z"


def entry(
    entry_id: int, action: str, entity_type: str, entity_id: str | None, **extra: Any
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "actor_user_id": 7,
        "actor_type": "user",
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before": None,
        "after": None,
        "ip": "10.0.0.5",
        "created_at": AT,
        "actor_name": "Иван Тестов",
        **extra,
    }


class CrmAudit:
    """`GET /api/v1/audit` CRM: записи в памяти, фильтры как у CRM."""

    def __init__(self, be: Backends) -> None:
        self.rows: list[dict[str, Any]] = []
        self.status = 200
        self.down = False
        self.route = be.router.get(AUDIT).mock(side_effect=self._list)
        # Роли, которые есть в CRM (`GET /platform-roles/{id}`); остальные — 404.
        self.roles = {"3", "9", "10"}
        self.role_route = be.router.get(url__regex=rf"{CRM_URL}/api/v1/platform-roles/\d+$").mock(
            side_effect=self._role
        )

    def _role(self, request: httpx.Request) -> httpx.Response:
        role_id = request.url.path.rsplit("/", 1)[-1]
        if role_id not in self.roles:
            return httpx.Response(404, json={"code": "not_found", "message": "role", "details": {}})
        return httpx.Response(200, json={"id": int(role_id), "name": "Роль"})

    def _list(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("crm down")
        if self.status != 200:
            return httpx.Response(
                self.status, json={"code": "forbidden", "message": "no", "details": {}}
            )
        q = request.url.params
        rows = self.rows
        if actor := q.get("actor_user_id"):
            rows = [r for r in rows if str(r["actor_user_id"]) == actor]
        if action := q.get("action"):
            rows = [r for r in rows if r["action"].startswith(action)]
        for prefix in q.get_list("exclude_actions"):
            rows = [r for r in rows if not r["action"].startswith(prefix)]
        if kind := q.get("entity_type"):
            rows = [r for r in rows if r["entity_type"] == kind]
        if entity := q.get("entity_id"):
            rows = [r for r in rows if r["entity_id"] == entity]
        limit, offset = int(q.get("limit", 50)), int(q.get("offset", 0))
        return httpx.Response(
            200, json={"items": rows[offset : offset + limit], "total": len(rows)}
        )

    def last_params(self) -> httpx.QueryParams:
        return self.route.calls.last.request.url.params


@pytest.fixture
def audit(be: Backends) -> CrmAudit:
    fake = CrmAudit(be)
    fake.rows = [
        entry(5, "user.update", "user", "11", before={"roles": ["a"]}, after={"roles": ["b"]}),
        entry(4, "auth.login", "user", "7"),
        entry(3, "auth.login_failed", "user", "9", actor_user_id=None, actor_type="system"),
        entry(2, "platform_role.update", "platform_role", "9", actor_user_id=8),
        entry(1, "settings.update", "settings", None, actor_type="bot", actor_user_id=None),
    ]
    return fake


# --- журнал аудита ---


async def test_audit_page_maps_crm_entries(
    web: Web, audit: CrmAudit, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/admin/audit")

    assert response.status_code == 200
    check(response, "/admin/audit", "get")
    body = response.json()
    # Входы по умолчанию скрыты; новые записи первыми — порядок CRM.
    assert [e["id"] for e in body["items"]] == ["5", "2", "1"]
    assert (body["total"], body["limit"], body["offset"]) == (3, 50, 0)
    first = body["items"][0]
    assert first["at"] == AT
    assert first["actor_type"] == "user"
    assert first["actor_id"] == "7"
    assert first["actor_name"] == "Иван Тестов"
    assert first["action"] == "user.update"
    assert first["entity_type"] == "user"
    assert first["entity_id"] == "11"
    assert first["before"] == {"roles": ["a"]}
    assert first["after"] == {"roles": ["b"]}
    assert first["ip"] == "10.0.0.5"
    bot = body["items"][2]
    assert bot["actor_type"] == "bot"
    assert not {"actor_id", "entity_id", "before"} & bot.keys()
    sent = audit.route.calls.last.request
    assert sent.headers["authorization"].startswith("Bearer crm-access-")
    assert audit.last_params().get_list("exclude_actions") == ["auth.login", "sso.exchange"]


async def test_audit_include_logins(web: Web, audit: CrmAudit, check: ContractChecker) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/admin/audit", params={"include_logins": "true"})

    check(response, "/admin/audit", "get")
    assert [e["id"] for e in response.json()["items"]] == ["5", "4", "3", "2", "1"]
    assert audit.last_params().get_list("exclude_actions") == []


async def test_audit_filters_are_translated_for_crm(web: Web, audit: CrmAudit) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get(
        "/api/v1/admin/audit",
        params={
            "actor_id": "8",
            "action": "platform_role",
            "entity_type": "platform_role",
            "entity_id": "9",
            "from": "2026-10-01T00:00:00+05:00",
            "to": "2026-11-01T00:00:00+05:00",
            "limit": 20,
            "offset": 40,
        },
    )

    assert response.status_code == 200
    q = audit.last_params()
    assert q["actor_user_id"] == "8"
    assert q["action"] == "platform_role"
    assert q["entity_type"] == "platform_role"
    assert q["entity_id"] == "9"
    assert q["created_from"] == "2026-10-01T00:00:00+05:00"
    assert q["created_to"] == "2026-11-01T00:00:00+05:00"
    assert (q["limit"], q["offset"]) == ("20", "40")
    assert [e["id"] for e in response.json()["items"]] == []
    assert (response.json()["limit"], response.json()["offset"]) == (20, 40)


async def test_audit_filter_by_actor_and_action(web: Web, audit: CrmAudit) -> None:
    await web.login(["ADMIN"])

    by_actor = (await web.client.get("/api/v1/admin/audit", params={"actor_id": "8"})).json()
    by_action = (await web.client.get("/api/v1/admin/audit", params={"action": "user"})).json()

    assert [e["id"] for e in by_actor["items"]] == ["2"]
    assert [e["id"] for e in by_action["items"]] == ["5"]


async def test_audit_pagination(web: Web, audit: CrmAudit) -> None:
    await web.login(["ADMIN"])

    page = (await web.client.get("/api/v1/admin/audit", params={"limit": 2, "offset": 2})).json()

    assert [e["id"] for e in page["items"]] == ["1"]
    assert page["total"] == 3
    assert (page["limit"], page["offset"]) == (2, 2)


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"actor_id": "abc"},
        {"from": "вчера"},
        {"action": "x" * 65},
    ],
)
async def test_audit_params_are_validated(
    web: Web, audit: CrmAudit, params: dict[str, Any]
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/admin/audit", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert audit.route.call_count == 0


async def test_audit_secrets_are_redacted(
    web: Web, audit: CrmAudit, check: ContractChecker
) -> None:
    audit.rows = [
        entry(
            1,
            "integrations.smtp",
            "integration_secret",
            "smtp",
            after={
                "host": "smtp.demo.example",
                "password": "swordfish",
                "api_key": "sk-123",
                "bot_token": "123:ABC",
                "password_last4": "fish",
                "nested": {"client_secret": "s3", "items": [{"token": "t"}]},
                "token": "",
            },
        )
    ]
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/admin/audit")

    check(response, "/admin/audit", "get")
    assert "swordfish" not in response.text
    assert "sk-123" not in response.text
    assert response.json()["items"][0]["after"] == {
        "host": "smtp.demo.example",
        "password": "***",
        "api_key": "***",
        "bot_token": "***",
        "password_last4": "fish",
        "nested": {"client_secret": "***", "items": [{"token": "***"}]},
        "token": "",
    }


async def test_secrets_in_role_snapshots_are_not_leaked_either(web: Web, audit: CrmAudit) -> None:
    audit.rows = [
        entry(1, "settings.update", "settings", None, before={"api_key": ["k1"]}, after={"key": 7})
    ]
    await web.login(["DIRECTOR"])

    body = (await web.client.get("/api/v1/admin/audit")).json()["items"][0]

    assert body["before"] == {"api_key": "***"}
    assert body["after"] == {"key": "***"}


async def test_audit_unknown_actor_type_is_system(web: Web, audit: CrmAudit) -> None:
    audit.rows = [entry(1, "x.y", "z", "1", actor_type="robot")]
    await web.login(["ADMIN"])

    body = (await web.client.get("/api/v1/admin/audit")).json()

    assert body["items"][0]["actor_type"] == "system"


# --- доступ по матрице ---


@pytest.mark.parametrize("role", ["MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"])
async def test_roles_without_admin_section_get_403(
    web: Web, audit: CrmAudit, check: ContractChecker, role: str
) -> None:
    await web.login([role])

    listing = await web.client.get("/api/v1/admin/audit")
    journal = await web.client.get("/api/v1/admin/roles/9/journal")

    for response, path in ((listing, "/admin/audit"), (journal, "/admin/roles/{id}/journal")):
        assert response.status_code == 403
        check(response, path, "get")
        assert response.json()["code"] == "FORBIDDEN"
        assert response.json()["source"] == "bff"
        assert response.json()["details"] == {"resource": "admin", "need": "read"}
    assert audit.route.call_count == 0


async def test_director_reads_the_journal(
    web: Web, audit: CrmAudit, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])

    listing = await web.client.get("/api/v1/admin/audit")
    journal = await web.client.get("/api/v1/admin/roles/9/journal")

    assert listing.status_code == journal.status_code == 200
    check(listing, "/admin/audit", "get")
    check(journal, "/admin/roles/{id}/journal", "get")


async def test_journal_cannot_be_changed(web: Web, audit: CrmAudit) -> None:
    """Эндпоинтов записи нет: ни администратор, ни директор не меняют журнал."""
    await web.login(["ADMIN"])

    for method in ("POST", "PATCH", "PUT", "DELETE"):
        response = await web.send(method, "/api/v1/admin/audit", json={})
        assert response.status_code == 405


async def test_audit_requires_session(web: Web, audit: CrmAudit, check: ContractChecker) -> None:
    response = await web.client.get("/api/v1/admin/audit")

    assert response.status_code == 401
    check(response, "/admin/audit", "get")


async def test_audit_crm_refusal_is_forbidden_from_crm(
    web: Web, audit: CrmAudit, check: ContractChecker
) -> None:
    audit.status = 403
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/admin/audit")

    assert response.status_code == 403
    check(response, "/admin/audit", "get")
    assert response.json()["source"] == "crm"


async def test_audit_crm_unavailable_is_503(
    web: Web, audit: CrmAudit, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    audit.down = True

    response = await web.client.get("/api/v1/admin/audit")

    assert response.status_code == 503
    check(response, "/admin/audit", "get")
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"


# --- журнал изменений роли ---


def snapshot(name: str, access: dict[str, str], fields: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": "",
        "access": access,
        "restricted_fields": fields or [],
    }


async def test_role_journal_maps_role_changes(
    web: Web, audit: CrmAudit, check: ContractChecker
) -> None:
    audit.rows = [
        entry(
            12,
            "platform_role.update",
            "platform_role",
            "9",
            before=snapshot("Закупки", {"erp.stock": "read"}),
            after=snapshot(
                "Закупки", {"erp.stock": "full", "crm.leads": "read"}, ["supplier_prices"]
            ),
        ),
        entry(11, "platform_role.create", "platform_role", "9", after=snapshot("Закупки", {})),
        entry(10, "platform_role.update", "platform_role", "10", after=snapshot("Другая", {})),
        entry(9, "user.update", "user", "9"),
    ]
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/admin/roles/9/journal")

    assert response.status_code == 200
    check(response, "/admin/roles/{id}/journal", "get")
    body = response.json()
    assert body["total"] == 2
    update, create = body["items"]
    assert update["id"] == "12"
    assert update["action"] == "update"
    assert update["actor_id"] == "7"
    assert update["actor_name"] == "Иван Тестов"
    assert update["before"] == snapshot("Закупки", {"erp.stock": "read"})
    assert update["after"] == snapshot(
        "Закупки", {"erp.stock": "full", "crm.leads": "read"}, ["supplier_prices"]
    )
    assert create["action"] == "create"
    assert "before" not in create
    q = audit.last_params()
    assert (q["entity_type"], q["entity_id"]) == ("platform_role", "9")
    assert not q.get_list("exclude_actions")


async def test_role_journal_tolerates_broken_snapshots(web: Web, audit: CrmAudit) -> None:
    audit.rows = [
        entry(
            1,
            "platform_role.update",
            "platform_role",
            "9",
            actor_user_id=None,
            actor_name=None,
            before={
                "name": "Роль",
                "access": {"a": "full", "b": "weird"},
                "restricted_fields": ["x"],
            },
            after="не словарь",
        )
    ]
    await web.login(["ADMIN"])

    item = (await web.client.get("/api/v1/admin/roles/9/journal")).json()["items"][0]

    assert item["before"] == {
        "name": "Роль",
        "description": "",
        "access": {"a": "full"},
        "restricted_fields": [],
    }
    assert not {"after", "actor_id", "actor_name"} & item.keys()


async def test_role_journal_paginates_and_validates_id(web: Web, audit: CrmAudit) -> None:
    await web.login(["ADMIN"])

    page = await web.client.get("/api/v1/admin/roles/9/journal", params={"limit": 5, "offset": 10})
    bad = await web.client.get("/api/v1/admin/roles/abc/journal")

    assert page.status_code == 200
    assert (audit.last_params()["limit"], audit.last_params()["offset"]) == ("5", "10")
    assert bad.status_code == 422


async def test_role_journal_of_unknown_role_is_404(
    web: Web, audit: CrmAudit, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/admin/roles/999/journal")

    assert response.status_code == 404
    check(response, "/admin/roles/{id}/journal", "get")
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["source"] == "crm"
    assert audit.route.call_count == 0


async def test_director_gets_404_for_unknown_role_too(web: Web, audit: CrmAudit) -> None:
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/admin/roles/999/journal")

    assert response.status_code == 404
