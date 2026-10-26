"""Временный пароль без почты (W13-A4, контракт BFF 0.10.0): `POST /admin/users` и
`POST /admin/users/{id}/temporary-password`.

Пароль выдаёт CRM; BFF отдаёт его один раз и нигде не держит. Здесь — права (раздел `admin`
полный), перевод ответов CRM и главное свойство: пароль есть только в этом ответе — не в журнале,
не в Redis, не в следующих ответах.
"""

import json
import secrets
from collections.abc import Iterator, Mapping, MutableMapping
from typing import Any

import httpx
import pytest
import structlog

from app.logging import configure_logging
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.roles import ROLE_IDS, rid
from tests.test_admin_users import ADMIN_ID, CrmUsers, crm_user

INVITE = {
    "email": "new.employee@demo.example",
    "name": "Новый Сотрудник",
    "position": "Инженер",
    "role_ids": [rid("ENGINEER"), rid("SUPPLY")],
}


class Passwords:
    """CRM выдаёт новый случайный пароль на каждое создание и сброс; все выданные запоминаются."""

    def __init__(self, be: Backends, users: CrmUsers) -> None:
        self.users = users
        self.issued: list[str] = []
        self.reset_error: httpx.Response | None = None
        self.reset = be.router.post(url__regex=rf"{CRM_URL}/api/v1/users/\d+/reset-password$").mock(
            side_effect=self._reset
        )
        created = users._create
        users.create_route.side_effect = lambda request: self._with_password(created(request))

    def issue(self) -> str:
        password = "Tmp-" + secrets.token_urlsafe(12)
        self.issued.append(password)
        return password

    def _with_password(self, response: httpx.Response) -> httpx.Response:
        if response.status_code != 201:
            return response
        body = json.loads(response.content)
        body["temporary_password"] = self.issue()
        return httpx.Response(201, json=body)

    def _reset(self, request: httpx.Request) -> httpx.Response:
        if self.reset_error is not None:
            return self.reset_error
        user_id = int(request.url.path.split("/")[4])
        user = self.users.users.get(user_id)
        if user is None:
            return CrmUsers._error(404, "not_found")
        user["must_change_password"] = True
        return httpx.Response(200, json={"temporary_password": self.issue()})


@pytest.fixture
def crm(be: Backends) -> CrmUsers:
    fake = CrmUsers(be)
    fake.users = {
        ADMIN_ID: crm_user(ADMIN_ID, "Иван Тестов", ("ADMIN",), position="Админ"),
        11: crm_user(11, "Анна Демова", ("SUPPLY", "MANAGER")),
        12: crm_user(12, "Борис Приглашённый", ("ACCOUNTANT",), must_change_password=True),
    }
    return fake


@pytest.fixture
def pw(be: Backends, crm: CrmUsers) -> Passwords:
    return Passwords(be, crm)


@pytest.fixture
def journal(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Журнал BFF на уровне DEBUG: записи модулей собираются в список, ничего не печатается."""
    events: list[dict[str, Any]] = []

    def collect(_: Any, __: str, event: MutableMapping[str, Any]) -> Mapping[str, Any]:
        events.append(dict(event))
        raise structlog.DropEvent

    structlog.configure(
        processors=[collect],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        cache_logger_on_first_use=False,
    )
    # Логгеры модулей кэшируют настройку при первом использовании: берём свежие на время теста.
    for module in ("app.api.auth", "app.api.setup", "app.auth", "app.errors", "app.session"):
        monkeypatch.setattr(f"{module}.log", structlog.get_logger())
    try:
        yield events
    finally:
        configure_logging("WARNING")


def nowhere(secret: str, web: Web, *, journal: list[dict[str, Any]]) -> None:
    """Пароля нет ни в Redis (сессии, лимиты, кэш), ни в журнале BFF."""
    assert not [k for k, v in web.redis.values.items() if secret in k or secret in v]
    assert secret not in json.dumps(journal, ensure_ascii=False, default=str)


# --- POST /admin/users ----------------------------------------------------------------------


async def test_create_without_mail_returns_the_password_once(
    web: Web, crm: CrmUsers, pw: Passwords, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/admin/users", json=INVITE)

    assert response.status_code == 201
    check(response, "/admin/users", "post")
    body = response.json()
    assert body["temporary_password"] == pw.issued[0]
    assert body["employee"]["name"] == "Новый Сотрудник"
    assert body["employee"]["status"] == "invited"  # пароль временный — сотрудник «Приглашён»
    assert [r["name"] for r in body["employee"]["roles"]] == ["Гл. инженер", "Снабженец"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert json.loads(crm.create_route.calls.last.request.content) == {
        "email": "new.employee@demo.example",
        "full_name": "Новый Сотрудник",
        "platform_role_ids": [ROLE_IDS["ENGINEER"], ROLE_IDS["SUPPLY"]],
        "position": "Инженер",
    }
    assert crm.invite_route.call_count == 0  # письма нет


async def test_the_password_is_not_in_logs_not_in_redis_not_in_the_next_response(
    web: Web,
    crm: CrmUsers,
    pw: Passwords,
    journal: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level("DEBUG")
    await web.login(["ADMIN"])

    created = await web.send("POST", "/api/v1/admin/users", json=INVITE)
    secret = created.json()["temporary_password"]
    new_id = created.json()["employee"]["id"]
    again = [
        await web.client.get("/api/v1/admin/users"),
        await web.client.get(f"/api/v1/admin/users/{new_id}"),
        await web.client.get("/api/v1/auth/session"),
        await web.client.get("/api/v1/me"),
    ]

    assert secret in created.text
    for response in again:
        assert response.status_code == 200
        assert secret not in response.text
    assert "temporary_password" not in "".join(r.text for r in again)
    assert any(e.get("event") == "login_succeeded" for e in journal)  # журнал действительно ведётся
    nowhere(secret, web, journal=journal)
    assert secret not in caplog.text
    out = capsys.readouterr()
    assert secret not in out.out + out.err


async def test_a_failed_create_leaks_no_password_in_the_error(
    web: Web, crm: CrmUsers, pw: Passwords, journal: list[dict[str, Any]]
) -> None:
    await web.login(["ADMIN"])
    crm.create_error = CrmUsers._error(409, "conflict", reason="email_taken", field="email")

    response = await web.send("POST", "/api/v1/admin/users", json=INVITE)

    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_EXISTS"
    assert "temporary_password" not in response.text
    assert pw.issued == []


async def test_create_with_a_taken_email_is_a_named_conflict(
    web: Web, crm: CrmUsers, pw: Passwords, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.create_error = CrmUsers._error(409, "conflict", reason="email_taken", field="email")

    response = await web.send("POST", "/api/v1/admin/users", json=INVITE)

    check(response, "/admin/users", "post")


async def test_create_when_crm_returns_no_password_is_503(
    web: Web, crm: CrmUsers, pw: Passwords
) -> None:
    await web.login(["ADMIN"])
    crm.create_route.side_effect = lambda request: httpx.Response(
        201, json={"user": crm_user(50, "Пустой Пароль")}
    )

    response = await web.send("POST", "/api/v1/admin/users", json=INVITE)

    assert response.status_code == 503
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {**INVITE, "role_ids": []},
        {**INVITE, "email": "no-at-sign"},
        {**INVITE, "name": "   "},
        {**INVITE, "password": "x"},
    ],
)
async def test_create_body_is_validated(
    web: Web, crm: CrmUsers, pw: Passwords, payload: dict[str, Any]
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/admin/users", json=payload)

    assert response.status_code == 422
    assert crm.create_route.call_count == 0


@pytest.mark.parametrize("role", ["DIRECTOR", "MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"])
async def test_create_needs_the_full_admin_section(
    web: Web, crm: CrmUsers, pw: Passwords, check: ContractChecker, role: str
) -> None:
    await web.login([role])

    response = await web.send("POST", "/api/v1/admin/users", json=INVITE)

    assert response.status_code == 403
    check(response, "/admin/users", "post")
    assert response.json()["details"] == {"resource": "admin", "need": "full"}
    assert crm.create_route.call_count == 0
    assert "temporary_password" not in response.text


async def test_create_needs_csrf_and_a_session(web: Web, crm: CrmUsers, pw: Passwords) -> None:
    anonymous = await web.client.post("/api/v1/admin/users", json=INVITE)
    await web.login(["ADMIN"])
    no_csrf = await web.send("POST", "/api/v1/admin/users", json=INVITE, csrf="wrong-token")

    assert anonymous.status_code == 401
    assert no_csrf.status_code == 403
    assert no_csrf.json()["code"] == "CSRF_FAILED"
    assert crm.create_route.call_count == 0


# --- POST /admin/users/{id}/temporary-password ----------------------------------------------


async def test_issue_resets_the_password_in_crm_and_shows_it_once(
    web: Web, crm: CrmUsers, pw: Passwords, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/admin/users/11/temporary-password")

    assert response.status_code == 200
    check(response, "/admin/users/{id}/temporary-password", "post")
    body = response.json()
    assert body["temporary_password"] == pw.issued[0]
    assert body["employee"]["id"] == "11"
    assert body["employee"]["status"] == "invited"  # CRM потребует смену пароля при входе
    assert response.headers["cache-control"] == "no-store"
    assert pw.reset.calls.last.request.url.path == "/api/v1/users/11/reset-password"
    assert crm.invite_route.call_count == 0


async def test_every_issue_gives_a_new_password_and_the_old_one_is_gone(
    web: Web, crm: CrmUsers, pw: Passwords, journal: list[dict[str, Any]]
) -> None:
    await web.login(["ADMIN"])

    first = await web.send("POST", "/api/v1/admin/users/12/temporary-password")
    second = await web.send("POST", "/api/v1/admin/users/12/temporary-password")

    one, two = first.json()["temporary_password"], second.json()["temporary_password"]
    assert one != two
    assert one not in second.text
    listing = await web.client.get("/api/v1/admin/users")
    assert one not in listing.text
    assert two not in listing.text
    for secret in (one, two):
        nowhere(secret, web, journal=journal)


async def test_issue_password_survives_a_failed_reread(
    web: Web, crm: CrmUsers, pw: Passwords
) -> None:
    """Пароль выдан и нигде не хранится: сбой перечитывания сотрудника его не теряет."""
    await web.login(["ADMIN"])
    calls = {"n": 0}
    original = crm._get

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 2:
            raise httpx.ConnectError("crm down")
        return original(request)

    crm.get_route.side_effect = flaky

    response = await web.send("POST", "/api/v1/admin/users/11/temporary-password")

    assert response.status_code == 200
    assert response.json()["temporary_password"] == pw.issued[0]
    assert response.json()["employee"]["status"] == "invited"


async def test_own_password_is_changed_in_the_profile(
    web: Web, crm: CrmUsers, pw: Passwords, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", f"/api/v1/admin/users/{ADMIN_ID}/temporary-password")

    assert response.status_code == 409
    check(response, "/admin/users/{id}/temporary-password", "post")
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["details"]["reason"] == "own_account"
    assert pw.reset.call_count == 0


async def test_issue_for_an_unknown_employee_is_404(
    web: Web, crm: CrmUsers, pw: Passwords, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/admin/users/999/temporary-password")

    assert response.status_code == 404
    check(response, "/admin/users/{id}/temporary-password", "post")
    assert pw.reset.call_count == 0


async def test_issue_id_must_be_numeric(web: Web, crm: CrmUsers, pw: Passwords) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/admin/users/abc/temporary-password")

    assert response.status_code == 422
    assert pw.reset.call_count == 0


async def test_issue_when_crm_refuses(
    web: Web, crm: CrmUsers, pw: Passwords, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    pw.reset_error = CrmUsers._error(403, "forbidden")

    response = await web.send("POST", "/api/v1/admin/users/11/temporary-password")

    assert response.status_code == 403
    check(response, "/admin/users/{id}/temporary-password", "post")
    assert response.json()["source"] == "crm"
    assert "temporary_password" not in response.text


async def test_issue_when_crm_is_down_is_503(
    web: Web, crm: CrmUsers, pw: Passwords, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.down = True

    response = await web.send("POST", "/api/v1/admin/users/11/temporary-password")

    assert response.status_code == 503
    check(response, "/admin/users/{id}/temporary-password", "post")


@pytest.mark.parametrize("role", ["DIRECTOR", "MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"])
async def test_issue_needs_the_full_admin_section(
    web: Web, crm: CrmUsers, pw: Passwords, check: ContractChecker, role: str
) -> None:
    await web.login([role])

    response = await web.send("POST", "/api/v1/admin/users/11/temporary-password")

    assert response.status_code == 403
    check(response, "/admin/users/{id}/temporary-password", "post")
    assert response.json()["details"] == {"resource": "admin", "need": "full"}
    assert pw.reset.call_count == 0
    assert crm.get_route.call_count == 0


async def test_issue_needs_csrf_and_a_session(web: Web, crm: CrmUsers, pw: Passwords) -> None:
    anonymous = await web.client.post("/api/v1/admin/users/11/temporary-password")
    await web.login(["ADMIN"])
    no_csrf = await web.send(
        "POST", "/api/v1/admin/users/11/temporary-password", csrf="wrong-token"
    )

    assert anonymous.status_code == 401
    assert no_csrf.status_code == 403
    assert pw.reset.call_count == 0
