"""Первый запуск (W13-A4, BFF 0.10.0; W13C-F1, 0.15.0): администратор, чек-лист, компания.

CRM и ERP — на respx; ответы BFF проверяются по схемам platform-bff.yaml. Решения (код первого
запуска, пароль, право, «компания уже есть») за бэкендами: здесь проверяется вызов, перевод в
контракт, права по разделу `admin` и то, что вход после создания администратора — обычный.
"""

import json
from typing import Any

import httpx
import pytest

from app.cookies import CSRF_COOKIE
from tests.backends import PASSWORD, Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL, ERP_URL
from tests.integrations_support import erp_status
from tests.test_admin_users import CrmUsers, crm_user

ADMIN_ID = 7
FIRST_ADMIN = {
    "code": "abcd-efgh-jkmn-pqrs",
    "name": "Первый Админ",
    "email": "ivan.test@example.org",
    "password": PASSWORD,
}


def crm_error(status: int, code: str, reason: str | None = None, **details: Any) -> httpx.Response:
    body_details = {**({"reason": reason} if reason else {}), **details}
    return httpx.Response(status, json={"code": code, "message": code, "details": body_details})


class SetupCrm:
    """`/api/v1/setup/*`, коннекторы и пользователи CRM; `setup/status/`, `setup/company/` ERP."""

    def __init__(self, be: Backends, users: CrmUsers) -> None:
        self.be = be
        self.users = users
        self.needs_setup = True
        self.admin_response: httpx.Response | None = None
        self.checklist_items = {"bot": True, "models": False}
        self.erp_configured = True
        self.checklist_response: httpx.Response | None = None
        self.smtp_configured = False
        self.down: set[str] = set()
        self.erp_status: httpx.Response = httpx.Response(
            200, json={"setup_required": True, "can_setup": True}
        )
        self.company_response: httpx.Response = httpx.Response(
            201, json={"id": 5, "name": "ООО Демо"}
        )
        router = be.router
        self.state = router.get(f"{CRM_URL}/api/v1/setup/state").mock(side_effect=self._state)
        self.admin = router.post(f"{CRM_URL}/api/v1/setup/admin").mock(side_effect=self._admin)
        self.checklist = router.get(f"{CRM_URL}/api/v1/setup/checklist").mock(
            side_effect=self._checklist
        )
        self.erp = router.get(f"{CRM_URL}/api/v1/integrations/erp").mock(side_effect=self._erp)
        self.erp_setup_status = router.get(f"{ERP_URL}/api/v1/setup/status/").mock(
            side_effect=lambda request: self.erp_status
        )
        self.erp_company = router.post(f"{ERP_URL}/api/v1/setup/company/").mock(
            side_effect=lambda request: self.company_response
        )

    def _guard(self, name: str) -> httpx.Response | None:
        if name in self.down:
            raise httpx.ConnectError(f"{name} down")
        return None

    def _state(self, request: httpx.Request) -> httpx.Response:
        return self._guard("state") or httpx.Response(200, json={"needs_setup": self.needs_setup})

    def _admin(self, request: httpx.Request) -> httpx.Response:
        if (early := self._guard("admin")) is not None:
            return early
        if self.admin_response is not None:
            return self.admin_response
        return self.be._token_response()

    def _checklist(self, request: httpx.Request) -> httpx.Response:
        if (early := self._guard("checklist")) is not None:
            return early
        if self.checklist_response is not None:
            return self.checklist_response
        keys = [
            "company",
            "business_hours",
            "models",
            "bot",
            "channel",
            "kb",
            "team",
            "test_dialog",
            "erp",
            "mail",
            "first_employee",
        ]
        # Шаги Платформы CRM считает сама (W13C-F1): коннектор ERP, SMTP, ещё один сотрудник.
        colleague = any(
            u.get("is_active", True) and u["id"] != ADMIN_ID for u in self.users.users.values()
        )
        facts = {
            **self.checklist_items,
            "erp": self.erp_configured,
            "mail": self.smtp_configured,
            "first_employee": colleague,
        }
        items: list[dict[str, Any]] = [
            {"key": key, "done": facts.get(key, False), "link": f"/{key}"} for key in keys
        ]
        done = sum(1 for i in items if i["done"])
        return httpx.Response(200, json={"items": items, "done": done, "total": len(items)})

    def _erp(self, request: httpx.Request) -> httpx.Response:
        if (early := self._guard("erp")) is not None:
            return early
        return httpx.Response(200, json=erp_status(configured=self.erp_configured))


def crm_checklist_without(*missing: str) -> httpx.Response:
    """Ответ CRM `/setup/checklist` без названных шагов (старая CRM или сбой проверки)."""
    keys = ["bot", "erp", "mail", "models", "first_employee"]
    items = [
        {"key": key, "done": key in {"bot", "erp"}, "link": f"/{key}"}
        for key in keys
        if key not in missing
    ]
    done = sum(1 for i in items if i["done"])
    return httpx.Response(200, json={"items": items, "done": done, "total": len(items)})


@pytest.fixture
def crm_users(be: Backends) -> CrmUsers:
    fake = CrmUsers(be)
    fake.users = {
        ADMIN_ID: crm_user(ADMIN_ID, "Иван Тестов", ("ADMIN",), position="Админ"),
    }
    return fake


@pytest.fixture
def crm(be: Backends, crm_users: CrmUsers) -> SetupCrm:
    return SetupCrm(be, crm_users)


def payload() -> dict[str, str]:
    return dict(FIRST_ADMIN)


# --- GET /setup/state -----------------------------------------------------------------------


async def test_state_is_public_and_not_cached(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    response = await web.client.get("/api/v1/setup/state")

    assert response.status_code == 200
    check(response, "/setup/state", "get")
    assert response.json() == {"needs_admin": True}
    assert response.headers["cache-control"] == "no-store"
    # токена нет: сотрудника ещё не существует
    assert "authorization" not in crm.state.calls.last.request.headers


async def test_state_when_the_admin_exists(web: Web, crm: SetupCrm) -> None:
    crm.needs_setup = False

    response = await web.client.get("/api/v1/setup/state")

    assert response.json() == {"needs_admin": False}


async def test_state_when_crm_is_down(web: Web, crm: SetupCrm, check: ContractChecker) -> None:
    crm.down.add("state")

    response = await web.client.get("/api/v1/setup/state")

    assert response.status_code == 503
    check(response, "/setup/state", "get")
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"
    assert response.json()["source"] == "crm"


# --- POST /setup/admin ----------------------------------------------------------------------


async def test_first_admin_is_created_and_signed_in(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    web.be.set_roles(["ADMIN"])

    response = await web.client.post("/api/v1/setup/admin", json=payload())

    assert response.status_code == 200
    check(response, "/setup/admin", "post")
    assert response.json()["me"]["email"] == "ivan.test@example.org"
    assert response.cookies.get("rt_pf_session")
    assert response.cookies.get(CSRF_COOKIE)
    # поля CRM: имя уходит как `full_name`, код — как введён (нормализует CRM)
    sent = json.loads(crm.admin.calls.last.request.content)
    assert sent == {
        "code": "abcd-efgh-jkmn-pqrs",
        "email": "ivan.test@example.org",
        "full_name": "Первый Админ",
        "password": PASSWORD,
    }
    # сессию открыл обычный вход; семья токенов, открытая самой CRM при создании, погашена
    assert web.be.crm_login.call_count == 1
    assert web.be.crm_logout.call_count == 1
    assert web.be.crm_logout.calls.last.request.headers["cookie"] == "rt_refresh=crm-refresh-1"
    session = await web.client.get("/api/v1/auth/session")
    assert session.status_code == 200
    assert session.json()["me"]["roles"][0]["code"] == "ADMIN"


async def test_first_admin_without_a_session_cookie_needs_no_csrf(web: Web, crm: SetupCrm) -> None:
    web.be.set_roles(["ADMIN"])

    response = await web.client.post("/api/v1/setup/admin", json=payload())

    assert response.status_code == 200


async def test_forwarded_ip_reaches_crm(web: Web, crm: SetupCrm) -> None:
    web.be.set_roles(["ADMIN"])

    await web.client.post(
        "/api/v1/setup/admin", json=payload(), headers={"X-Forwarded-For": "203.0.113.9"}
    )

    assert crm.admin.calls.last.request.headers["x-forwarded-for"] == "203.0.113.9"


@pytest.mark.parametrize(
    ("crm_response", "status", "code"),
    [
        (
            crm_error(422, "validation_failed", "setup_code_invalid", field="code"),
            422,
            "SETUP_CODE_INVALID",
        ),
        (
            crm_error(422, "validation_failed", "setup_code_expired", field="code"),
            422,
            "SETUP_CODE_EXPIRED",
        ),
        (crm_error(422, "validation_failed", "setup_locked", field="code"), 429, "SETUP_LOCKED"),
        (crm_error(409, "conflict", "setup_done"), 409, "SETUP_DONE"),
    ],
)
async def test_setup_refusals_are_named_codes(
    web: Web,
    crm: SetupCrm,
    check: ContractChecker,
    crm_response: httpx.Response,
    status: int,
    code: str,
) -> None:
    crm.admin_response = crm_response

    response = await web.client.post("/api/v1/setup/admin", json=payload())

    assert response.status_code == status
    check(response, "/setup/admin", "post")
    assert response.json()["code"] == code
    assert response.json()["source"] == "crm"
    assert not response.cookies.get("rt_pf_session")
    assert web.be.crm_login.call_count == 0  # без администратора входить не во что


async def test_locked_code_says_when_to_retry(web: Web, crm: SetupCrm) -> None:
    crm.admin_response = crm_error(422, "validation_failed", "setup_locked", field="code")

    response = await web.client.post("/api/v1/setup/admin", json=payload())

    assert response.headers["retry-after"] == "900"


async def test_weak_password_names_the_field(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    crm.admin_response = crm_error(422, "validation_failed", "weak_password", field="password")

    response = await web.client.post("/api/v1/setup/admin", json=payload())

    assert response.status_code == 422
    check(response, "/setup/admin", "post")
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["details"]["fields"] == ["password"]
    assert response.json()["details"]["reason"] == "weak_password"


async def test_crm_down_during_setup_is_503(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    crm.down.add("admin")

    response = await web.client.post("/api/v1/setup/admin", json=payload())

    assert response.status_code == 503
    check(response, "/setup/admin", "post")


async def test_wrong_codes_count_against_the_login_limit(web: Web, crm: SetupCrm) -> None:
    """Перебор кода ограничивает и BFF (сверх блокировки CRM): 11-я попытка в минуту — 429."""
    crm.admin_response = crm_error(422, "validation_failed", "setup_code_invalid", field="code")

    statuses = [
        (await web.client.post("/api/v1/setup/admin", json=payload())).status_code
        for _ in range(12)
    ]

    assert statuses == [422] * 10 + [429] * 2
    assert crm.admin.call_count == 10


async def test_weak_password_attempts_do_not_burn_the_limit(web: Web, crm: SetupCrm) -> None:
    crm.admin_response = crm_error(422, "validation_failed", "weak_password", field="password")

    statuses = {
        (await web.client.post("/api/v1/setup/admin", json=payload())).status_code
        for _ in range(12)
    }

    assert statuses == {422}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {**FIRST_ADMIN, "name": "   "},
        {**FIRST_ADMIN, "email": "no-at-sign"},
        {**FIRST_ADMIN, "password": ""},
        {**FIRST_ADMIN, "code": ""},
        {**FIRST_ADMIN, "role": "ADMIN"},
    ],
)
async def test_setup_admin_body_is_validated(web: Web, crm: SetupCrm, body: dict[str, Any]) -> None:
    response = await web.client.post("/api/v1/setup/admin", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert crm.admin.call_count == 0


async def test_setup_failure_is_journaled_without_secrets(
    web: Web, crm: SetupCrm, capsys: pytest.CaptureFixture[str]
) -> None:
    crm.admin_response = crm_error(422, "validation_failed", "setup_code_invalid", field="code")

    await web.client.post("/api/v1/setup/admin", json=payload())

    out = capsys.readouterr().out
    assert "setup_admin_failed" in out
    assert FIRST_ADMIN["code"] not in out
    assert PASSWORD not in out
    assert "ivan.test@example.org" not in out


# --- GET /setup/checklist -------------------------------------------------------------------


def steps(response: httpx.Response) -> dict[str, str]:
    return {s["key"]: s["state"] for s in response.json()["steps"]}


async def test_checklist_summarises_five_steps(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.users.users[11] = crm_user(11, "Анна Демова")

    response = await web.client.get("/api/v1/setup/checklist")

    assert response.status_code == 200
    check(response, "/setup/checklist", "get")
    body = response.json()
    assert [s["key"] for s in body["steps"]] == ["erp", "bot", "mail", "models", "first_employee"]
    # все пять шагов приносит CRM /setup/checklist; BFF сам ничего не вычисляет
    assert steps(response) == {
        "erp": "done",  # коннектор ERP задан
        "bot": "done",
        "mail": "todo",  # SMTP не настроен
        "models": "todo",
        "first_employee": "done",  # в CRM есть активный сотрудник кроме администратора
    }
    assert (body["done"], body["total"]) == (3, 5)
    assert body["company"] == {"required": True, "can_setup": True}
    assert body["company_blocker"] is None
    assert crm.users.list_route.call_count == 0  # «первый сотрудник» — из чек-листа CRM
    assert response.headers["cache-control"] == "no-store"
    assert crm.checklist.calls.last.request.headers["authorization"].startswith(
        "Bearer crm-access-"
    )
    assert crm.erp_setup_status.calls.last.request.headers["authorization"].startswith("Bearer ")


async def test_checklist_everything_done(web: Web, crm: SetupCrm) -> None:
    await web.login(["ADMIN"])
    crm.checklist_items = {"bot": True, "models": True}
    crm.smtp_configured = True
    crm.users.users[11] = crm_user(11, "Анна Демова")
    crm.erp_status = httpx.Response(200, json={"setup_required": False, "can_setup": False})

    response = await web.client.get("/api/v1/setup/checklist")

    assert set(steps(response).values()) == {"done"}
    assert response.json()["done"] == 5
    assert response.json()["company"] == {"required": False, "can_setup": False}


async def test_first_employee_ignores_oneself_and_disabled_users(web: Web, crm: SetupCrm) -> None:
    await web.login(["ADMIN"])
    crm.users.users[13] = crm_user(13, "Виктор Отключённый", is_active=False)

    response = await web.client.get("/api/v1/setup/checklist")

    assert steps(response)["first_employee"] == "todo"


async def test_a_step_without_an_answer_is_unknown_not_an_error(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.checklist_response = crm_checklist_without("mail", "models")

    response = await web.client.get("/api/v1/setup/checklist")

    assert response.status_code == 200
    check(response, "/setup/checklist", "get")
    states = steps(response)
    assert states["mail"] == states["models"] == "unknown"
    assert states["bot"] == states["erp"] == "done"


async def test_checklist_when_erp_does_not_answer_says_so(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    """ERP сопряжена, но молчит: компании нет, причина — «не ответила», а не «подключите»."""
    await web.login(["ADMIN"])
    crm.erp_status = httpx.Response(503, json={"detail": "down"})

    response = await web.client.get("/api/v1/setup/checklist")

    assert response.status_code == 200
    check(response, "/setup/checklist", "get")
    assert response.json()["company"] is None
    assert response.json()["company_blocker"] == "erp_unavailable"
    assert steps(response)["bot"] == "done"
    assert steps(response)["erp"] == "done"


async def test_checklist_with_hanging_erp_is_200_and_erp_unavailable(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    """Сопряжённая ERP висит (таймаут): чек-лист не падает, шаг компании — «ERP не ответила»."""
    await web.login(["ADMIN"])
    crm.erp_setup_status.mock(side_effect=httpx.ReadTimeout("erp is hanging"))

    response = await web.client.get("/api/v1/setup/checklist")

    assert response.status_code == 200
    check(response, "/setup/checklist", "get")
    assert response.json()["company"] is None
    assert response.json()["company_blocker"] == "erp_unavailable"
    assert steps(response)["erp"] == "done"


async def test_checklist_without_pairing_does_not_ask_erp(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    """ERP не сопряжена: компания невозможна, причина — «сначала подключите ERP»; ERP не дёргаем."""
    await web.login(["ADMIN"])
    crm.erp_configured = False

    response = await web.client.get("/api/v1/setup/checklist")

    assert response.status_code == 200
    check(response, "/setup/checklist", "get")
    body = response.json()
    assert body["company"] is None
    assert body["company_blocker"] == "erp_not_connected"
    assert steps(response)["erp"] == "todo"
    assert crm.erp_setup_status.call_count == 0


async def test_checklist_when_crm_answers_nothing_is_503(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.down.add("checklist")

    response = await web.client.get("/api/v1/setup/checklist")

    assert response.status_code == 503
    check(response, "/setup/checklist", "get")
    assert response.json()["source"] == "crm"


@pytest.mark.parametrize("role", ["DIRECTOR", "MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"])
async def test_checklist_needs_the_full_admin_section(
    web: Web, crm: SetupCrm, check: ContractChecker, role: str
) -> None:
    await web.login([role])

    response = await web.client.get("/api/v1/setup/checklist")

    assert response.status_code == 403
    check(response, "/setup/checklist", "get")
    assert response.json()["code"] == "FORBIDDEN"
    assert response.json()["source"] == "bff"
    assert crm.checklist.call_count == 0
    assert crm.erp_setup_status.call_count == 0


async def test_checklist_requires_a_session(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    response = await web.client.get("/api/v1/setup/checklist")

    assert response.status_code == 401
    check(response, "/setup/checklist", "get")


# --- POST /setup/company --------------------------------------------------------------------


COMPANY = {
    "name": "  ООО Демо  ",
    "inn": "123456789",
    "legal_address": "г. Ташкент, ул. Демо, 1",
    "phone": "",
    "email": "  ",
}


async def test_company_is_created_in_erp_with_the_admin_token(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/setup/company", json=COMPANY)

    assert response.status_code == 201
    check(response, "/setup/company", "post")
    assert response.json() == {"id": 5, "name": "ООО Демо"}
    request = crm.erp_company.calls.last.request
    assert request.headers["authorization"].startswith("Bearer ")
    # пустые поля в ERP не уходят, пробелы срезаны
    assert json.loads(request.content) == {
        "name": "ООО Демо",
        "inn": "123456789",
        "legal_address": "г. Ташкент, ул. Демо, 1",
    }


async def test_company_that_already_exists_is_409(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.company_response = httpx.Response(409, json={"detail": "OWN_COMPANY_ALREADY_EXISTS"})

    response = await web.send("POST", "/api/v1/setup/company", json=COMPANY)

    assert response.status_code == 409
    check(response, "/setup/company", "post")
    assert response.json()["code"] == "OWN_COMPANY_ALREADY_EXISTS"
    assert response.json()["source"] == "erp"


async def test_company_form_errors_come_from_erp(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.company_response = httpx.Response(422, json={"inn": ["Такой ИНН уже есть."], "name": ["x"]})

    response = await web.send("POST", "/api/v1/setup/company", json=COMPANY)

    assert response.status_code == 422
    check(response, "/setup/company", "post")
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["details"]["fields"] == ["inn", "name"]
    assert response.json()["details"]["messages"]["inn"] == "Такой ИНН уже есть."


async def test_company_forbidden_for_a_non_superuser_in_erp(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.company_response = httpx.Response(403, json={"detail": "PLATFORM_ADMIN_REQUIRED"})

    response = await web.send("POST", "/api/v1/setup/company", json=COMPANY)

    assert response.status_code == 403
    check(response, "/setup/company", "post")
    assert response.json()["source"] == "erp"
    assert "администратор ERP" in response.json()["message"]


async def test_company_when_erp_is_not_reachable_is_503(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.company_response = httpx.Response(503, json={"detail": "down"})

    response = await web.send("POST", "/api/v1/setup/company", json=COMPANY)

    assert response.status_code == 503
    check(response, "/setup/company", "post")
    assert response.json()["source"] == "erp"


async def test_company_without_pairing_is_409_erp_not_connected(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    """C2A-G-1: ERP не сопряжена -> 409 с объяснением; вызов ERP не уходит, экран не висит."""
    await web.login(["ADMIN"])
    crm.erp_configured = False

    response = await web.send("POST", "/api/v1/setup/company", json=COMPANY)

    assert response.status_code == 409
    check(response, "/setup/company", "post")
    body = response.json()
    assert body["code"] == "ERP_NOT_CONNECTED"
    assert body["source"] == "bff"
    assert "Сначала подключите ERP" in body["message"]
    assert body["details"]["link"] == "/admin/integrations?card=erp&panel=open"
    assert crm.erp_company.call_count == 0


async def test_company_with_pairing_but_erp_down_stays_503(
    web: Web, crm: SetupCrm, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.erp_configured = True
    crm.company_response = httpx.Response(503, json={"detail": "down"})

    response = await web.send("POST", "/api/v1/setup/company", json=COMPANY)

    assert response.status_code == 503
    check(response, "/setup/company", "post")
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"
    assert crm.erp_company.call_count == 1


async def test_company_when_crm_cannot_tell_asks_erp_anyway(web: Web, crm: SetupCrm) -> None:
    """CRM молчит про коннектор — не блокируем: ответ даёт сама ERP."""
    await web.login(["ADMIN"])
    crm.down.add("erp")

    response = await web.send("POST", "/api/v1/setup/company", json=COMPANY)

    assert response.status_code == 201


async def test_company_without_erp_access_is_403_from_the_session(web: Web, crm: SetupCrm) -> None:
    web.be.profile["platform_access"] = ["crm"]
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/setup/company", json=COMPANY)

    assert response.status_code == 403
    assert response.json()["details"]["reason"] == "erp_not_granted"
    assert crm.erp_company.call_count == 0


@pytest.mark.parametrize("role", ["DIRECTOR", "MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"])
async def test_company_needs_the_full_admin_section(
    web: Web, crm: SetupCrm, check: ContractChecker, role: str
) -> None:
    await web.login([role])

    response = await web.send("POST", "/api/v1/setup/company", json=COMPANY)

    assert response.status_code == 403
    check(response, "/setup/company", "post")
    assert response.json()["details"] == {"resource": "admin", "need": "full"}
    assert crm.erp_company.call_count == 0


async def test_company_needs_csrf(web: Web, crm: SetupCrm, check: ContractChecker) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/setup/company", json=COMPANY, csrf="wrong-token")

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert crm.erp_company.call_count == 0


@pytest.mark.parametrize(
    "body",
    [{}, {"name": ""}, {"name": "   "}, {"name": "Х", "inn": "1" * 21}, {"name": "Х", "x": 1}],
)
async def test_company_body_is_validated(web: Web, crm: SetupCrm, body: dict[str, Any]) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/setup/company", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert crm.erp_company.call_count == 0
