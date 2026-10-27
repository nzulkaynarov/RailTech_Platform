"""«Забыли пароль?» на входе (W15-H6): ответ одинаков, лимит, перевод ошибок сброса.

Ссылку выпускает и отправляет CRM; BFF не знает, существует ли учётная запись, и не должен
выдавать это ни ответом, ни скоростью, ни кодом.
"""

import json
from typing import Any

import httpx
import pytest

from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL

FORGOT = f"{CRM_URL}/api/v1/auth/forgot-password"
RESET = f"{CRM_URL}/api/v1/auth/reset-password"
TOKEN = "t" * 43


class CrmReset:
    def __init__(self, web: Web) -> None:
        self.forgot_bodies: list[dict[str, Any]] = []
        self.reset_bodies: list[dict[str, Any]] = []
        self.forgot_status = 202
        self.reset_response = httpx.Response(204)
        self.down = False
        web.be.router.post(FORGOT).mock(side_effect=self._forgot)
        web.be.router.post(RESET).mock(side_effect=self._reset)

    def _forgot(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("crm down")
        self.forgot_bodies.append(json.loads(request.content))
        return httpx.Response(self.forgot_status, json={"accepted": True})

    def _reset(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("crm down")
        self.reset_bodies.append(json.loads(request.content))
        return self.reset_response


@pytest.fixture
def crm(web: Web) -> CrmReset:
    return CrmReset(web)


async def forgot(web: Web, identifier: str, ip: str = "203.0.113.5") -> httpx.Response:
    return await web.client.post(
        "/api/v1/auth/forgot-password",
        json={"identifier": identifier},
        headers={"X-Forwarded-For": ip},
    )


async def test_answer_is_identical_whatever_crm_says(
    web: Web, crm: CrmReset, check: ContractChecker
) -> None:
    known = await forgot(web, "ivan.test@example.org")
    crm.forgot_status = 404  # CRM «не знает» такого — клиент этого не должен заметить
    unknown = await forgot(web, "nobody@example.org")
    crm.forgot_status = 422
    odd = await forgot(web, "x")

    for response in (known, unknown, odd):
        check(response, "/auth/forgot-password", "post")
        assert (response.status_code, response.json()) == (202, {"accepted": True})
    assert [b["identifier"] for b in crm.forgot_bodies] == [
        "ivan.test@example.org", "nobody@example.org", "x",
    ]  # fmt: skip


async def test_no_session_is_needed_and_none_is_created(web: Web, crm: CrmReset) -> None:
    response = await forgot(web, "ivan.test@example.org")
    assert response.status_code == 202
    assert web.redis.session_keys() == []
    assert "set-cookie" not in response.headers


async def test_requests_are_rate_limited_per_address_and_per_ip(
    web: Web, crm: CrmReset, check: ContractChecker
) -> None:
    for _ in range(5):
        assert (await forgot(web, "ivan.test@example.org", ip="198.51.100.1")).status_code == 202
    blocked = await forgot(
        web, "ivan.test@example.org", ip="198.51.100.2"
    )  # другой IP, тот же адрес
    assert blocked.status_code == 429
    check(blocked, "/auth/forgot-password", "post")
    assert int(blocked.headers["retry-after"]) > 0
    assert len(crm.forgot_bodies) == 5  # шестой до CRM не дошёл

    # По IP тоже: чужие адреса с того же IP считаются вместе.
    for n in range(5):
        assert (await forgot(web, f"u{n}@example.org", ip="198.51.100.9")).status_code == 202
    assert (await forgot(web, "u9@example.org", ip="198.51.100.9")).status_code == 429


async def test_existing_and_missing_accounts_spend_one_budget(web: Web, crm: CrmReset) -> None:
    """Счётчик идёт по запросам, а не по найденным учёткам: перебор адресов упирается в лимит."""
    for n in range(5):
        await forgot(web, f"ghost{n}@example.org", ip="198.51.100.20")
    assert (await forgot(web, "ivan.test@example.org", ip="198.51.100.20")).status_code == 429


async def test_crm_down_is_503_not_a_silent_success(
    web: Web, crm: CrmReset, check: ContractChecker
) -> None:
    crm.down = True
    response = await forgot(web, "ivan.test@example.org")
    assert response.status_code == 503
    check(response, "/auth/forgot-password", "post")


@pytest.mark.parametrize("payload", [{}, {"identifier": ""}, {"identifier": "a", "x": 1}])
async def test_forgot_body_is_validated(web: Web, crm: CrmReset, payload: dict[str, Any]) -> None:
    response = await web.client.post("/api/v1/auth/forgot-password", json=payload)
    assert response.status_code == 422
    assert crm.forgot_bodies == []


async def test_reset_sets_the_password(web: Web, crm: CrmReset, check: ContractChecker) -> None:
    response = await web.client.post(
        "/api/v1/auth/reset-password", json={"token": TOKEN, "new_password": "Brand-new-secret-77"}
    )
    assert response.status_code == 204
    check(response, "/auth/reset-password", "post")
    assert crm.reset_bodies == [{"token": TOKEN, "new_password": "Brand-new-secret-77"}]
    assert "set-cookie" not in response.headers  # сброс не входит в систему сам


@pytest.mark.parametrize(
    ("reason", "field"), [("reset_token_invalid", "token"), ("weak_password", "new_password")]
)
async def test_reset_errors_keep_reason_and_field(
    web: Web, crm: CrmReset, check: ContractChecker, reason: str, field: str
) -> None:
    crm.reset_response = httpx.Response(
        422, json={"code": "validation_failed", "message": "x", "details": {"reason": reason}}
    )
    response = await web.client.post(
        "/api/v1/auth/reset-password", json={"token": TOKEN, "new_password": "Brand-new-secret-77"}
    )
    assert response.status_code == 422
    check(response, "/auth/reset-password", "post")
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["details"] == {"fields": [field], "reason": reason}


@pytest.mark.parametrize(
    "payload",
    [
        {"token": "short", "new_password": "Brand-new-secret-77"},
        {"token": TOKEN, "new_password": "short"},
        {"token": TOKEN, "new_password": "Short1abc"},  # 9 символов: политика CRM — от 10
        {"token": TOKEN},
    ],
)
async def test_reset_body_is_validated(web: Web, crm: CrmReset, payload: dict[str, Any]) -> None:
    response = await web.client.post("/api/v1/auth/reset-password", json=payload)
    assert response.status_code == 422
    assert crm.reset_bodies == []


async def test_reset_attempts_are_limited_per_ip(web: Web, crm: CrmReset) -> None:
    body = {"token": TOKEN, "new_password": "Brand-new-secret-77"}
    headers = {"X-Forwarded-For": "198.51.100.30"}
    for _ in range(20):
        r = await web.client.post("/api/v1/auth/reset-password", json=body, headers=headers)
        assert r.status_code == 204
    blocked = await web.client.post("/api/v1/auth/reset-password", json=body, headers=headers)
    assert blocked.status_code == 429
