"""Профиль /me (W15-H6, контракт 0.21.0): поля, фото, Telegram сам, замещение — только про себя.

CRM на respx: решения (значения, лимиты, срок кода) за CRM, здесь — перевод, права «только свой
профиль» и отдача фото без публичных ссылок на S3.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.roles import NAMES

ME = f"{CRM_URL}/api/v1/me"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
MULTIPART = "multipart/form-data; boundary=xyz"


def part(payload: bytes, mime: str, name: str = "avatar") -> bytes:
    head = (
        f'--xyz\r\nContent-Disposition: form-data; name="{name}"; filename="a"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode()
    return head + payload + b"\r\n--xyz--\r\n"


class CrmProfile:
    """CRM: `/me` с профильными полями и все новые ручки `/me/*`."""

    def __init__(self, be: Backends) -> None:
        self.be = be
        self.extra: dict[str, Any] = {
            "phone": "+998901234567",
            "timezone": "Asia/Tashkent",
            "email_signature": "С уважением, Иван",
            "tg_user_id": 555001,
            "tg_username": "ivan_t",
            "avatar_version": None,
            "deputy_user_id": None,
            "deputy_from": None,
            "deputy_to": None,
            "deputy_name": None,
        }
        self.covering: list[dict[str, Any]] = []
        self.patches: list[dict[str, Any]] = []
        self.uploads: list[tuple[bytes, str]] = []
        self.refuse: tuple[int, dict[str, Any]] | None = None
        self.down = False
        self.avatar_file: httpx.Response = httpx.Response(404, json={"code": "not_found"})
        base = be.router
        be.crm_me.mock(side_effect=self._get)
        be.crm_patch_me.mock(side_effect=self._patch)
        base.get(f"{ME}/covering").mock(side_effect=lambda _r: self._json(self.covering))
        base.put(f"{ME}/avatar").mock(side_effect=self._upload)
        base.delete(f"{ME}/avatar").mock(side_effect=self._drop_avatar)
        self.link = base.post(f"{ME}/telegram-link").mock(side_effect=self._link)
        base.delete(f"{ME}/telegram-link").mock(side_effect=self._unlink)
        base.get(f"{ME}/deputy-candidates").mock(
            side_effect=lambda _r: self._json(
                [{"id": 11, "full_name": "Азиз К.", "position": None}]
            )
        )
        base.put(f"{ME}/deputy").mock(side_effect=self._set_deputy)
        base.delete(f"{ME}/deputy").mock(side_effect=self._clear_deputy)
        base.get(url__regex=rf"^{CRM_URL}/api/v1/staff/\d+/avatar$").mock(
            side_effect=lambda _r: self.avatar_file
        )

    def _out(self) -> dict[str, Any]:
        return {**self.be.profile, **self.extra}

    def _json(self, body: Any, status: int = 200) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("crm down")
        if self.refuse is not None:
            code, payload = self.refuse
            return httpx.Response(code, json=payload)
        return httpx.Response(status, json=body)

    def _get(self, request: httpx.Request) -> httpx.Response:
        base = self.be._me(request)
        if base.status_code != 200:
            return base
        return httpx.Response(200, json={**base.json(), **self.extra})

    def _patch(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.patches.append(body)
        if self.refuse is not None or self.down:
            return self._json(None)
        if "full_name" in body:
            self.be.profile["full_name"] = body["full_name"]
        if "language" in body:
            self.be.profile["language"] = body["language"]
        self.extra.update({k: v or None for k, v in body.items() if k in self.extra})
        return httpx.Response(200, json=self._out())

    def _upload(self, request: httpx.Request) -> httpx.Response:
        self.uploads.append((request.content, request.headers.get("content-type", "")))
        if self.refuse is not None:
            return self._json(None)
        self.extra["avatar_version"] = 1790000000
        return httpx.Response(200, json=self._out())

    def _drop_avatar(self, _r: httpx.Request) -> httpx.Response:
        self.extra["avatar_version"] = None
        return self._json(self._out())

    def _link(self, _r: httpx.Request) -> httpx.Response:
        return self._json(
            {
                "url": "https://t.me/rt_demo_bot?start=staff_AAAAAAAAAAAAAAAA",
                "expires_at": "2026-10-27T10:10:00Z",
            }
        )

    def _unlink(self, _r: httpx.Request) -> httpx.Response:
        self.extra.update(tg_user_id=None, tg_username=None)
        return self._json(self._out())

    def _set_deputy(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.patches.append(body)
        if self.refuse is not None:
            return self._json(None)
        self.extra.update(
            deputy_user_id=body["deputy_user_id"],
            deputy_from=body["date_from"],
            deputy_to=body["date_to"],
            deputy_name="Азиз К.",
        )
        return httpx.Response(200, json=self._out())

    def _clear_deputy(self, _r: httpx.Request) -> httpx.Response:
        self.extra.update(deputy_user_id=None, deputy_from=None, deputy_to=None, deputy_name=None)
        return self._json(self._out())


@pytest.fixture
def crm(be: Backends) -> CrmProfile:
    return CrmProfile(be)


def refusal(status: int, reason: str, field: str | None = None) -> tuple[int, dict[str, Any]]:
    details: dict[str, Any] = {"reason": reason}
    if field:
        details["field"] = field
    return status, {"code": "validation_failed", "message": "x", "details": details}


@pytest.mark.parametrize("role", list(NAMES))
async def test_every_employee_reads_own_profile(
    web: Web, crm: CrmProfile, check: ContractChecker, role: str
) -> None:
    await web.login([role])
    response = await web.client.get("/api/v1/me/profile")
    assert response.status_code == 200
    check(response, "/me/profile", "get")
    body = response.json()
    assert body["name"] == "Иван Тестов"
    assert body["position"] == "Менеджер по продажам"
    assert body["phone"] == "+998901234567"
    assert body["timezone"] == "Asia/Tashkent"
    assert body["telegram"] == {"linked": True, "username": "ivan_t"}
    assert body["covering"] == []
    assert "deputy" not in body
    assert "avatar_url" not in body
    assert "555001" not in response.text  # числовой id Telegram наружу не идёт


async def test_profile_shows_deputy_covering_and_photo(
    web: Web, crm: CrmProfile, check: ContractChecker
) -> None:
    crm.extra.update(
        avatar_version=1790000000,
        deputy_user_id=11,
        deputy_from="2026-11-01",
        deputy_to="2026-11-10",
        deputy_name="Азиз К.",
    )
    crm.covering = [
        {
            "user_id": 12,
            "full_name": "Мадина Р.",
            "date_from": "2026-10-20",
            "date_to": "2026-11-02",
        }
    ]
    await web.login(["MANAGER"])
    response = await web.client.get("/api/v1/me/profile")
    check(response, "/me/profile", "get")
    body = response.json()
    assert body["avatar_url"] == "/api/v1/staff/7/avatar?v=1790000000"
    assert body["deputy"] == {
        "user_id": "11", "name": "Азиз К.", "date_from": "2026-11-01", "date_to": "2026-11-10",
    }  # fmt: skip
    assert [c["name"] for c in body["covering"]] == ["Мадина Р."]


async def test_profile_without_telegram(web: Web, crm: CrmProfile, check: ContractChecker) -> None:
    crm.extra.update(tg_user_id=None, tg_username=None)
    await web.login(["MANAGER"])
    response = await web.client.get("/api/v1/me/profile")
    check(response, "/me/profile", "get")
    assert response.json()["telegram"] == {"linked": False}


async def test_update_maps_name_and_refreshes_the_session(
    web: Web, crm: CrmProfile, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    response = await web.send(
        "PATCH",
        "/api/v1/me/profile",
        json={"name": "Иван П.", "phone": "", "language": "uz", "timezone": "Asia/Samarkand"},
    )
    assert response.status_code == 200, response.text
    check(response, "/me/profile", "patch")
    # CRM получила `full_name`, а не `name`; ничего лишнего.
    assert crm.patches == [
        {"full_name": "Иван П.", "phone": "", "language": "uz", "timezone": "Asia/Samarkand"}
    ]
    assert "phone" not in response.json()
    me = (await web.client.get("/api/v1/me")).json()
    assert (me["name"], me["language"]) == ("Иван П.", "uz")  # сессия не отстаёт от профиля


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"name": ""},
        {"name": "   "},
        {"position": "Директор"},
        {"user_id": "9"},
        {"roles": []},
    ],
)
async def test_update_accepts_only_own_editable_fields(
    web: Web, crm: CrmProfile, check: ContractChecker, payload: dict[str, Any]
) -> None:
    await web.login(["MANAGER"])
    response = await web.send("PATCH", "/api/v1/me/profile", json=payload)
    assert response.status_code == 422
    check(response, "/me/profile", "patch")
    assert crm.patches == []  # до CRM не дошло


@pytest.mark.parametrize(
    ("reason", "field", "expected"),
    [
        ("phone_invalid", "phone", ["phone"]),
        ("timezone_unknown", "timezone", ["timezone"]),
        ("signature_invalid", "email_signature", ["email_signature"]),
    ],
)
async def test_value_errors_name_field_and_reason(
    web: Web,
    crm: CrmProfile,
    check: ContractChecker,
    reason: str,
    field: str,
    expected: list[str],
) -> None:
    await web.login(["MANAGER"])
    crm.refuse = refusal(422, reason, field)
    response = await web.send("PATCH", "/api/v1/me/profile", json={field: "x"})
    assert response.status_code == 422
    check(response, "/me/profile", "patch")
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["details"] == {"fields": expected, "reason": reason}


async def test_profile_requires_csrf_and_session(web: Web, crm: CrmProfile) -> None:
    assert (await web.client.get("/api/v1/me/profile")).status_code == 401
    await web.login(["MANAGER"])
    bad = await web.send("PATCH", "/api/v1/me/profile", json={"name": "X"}, csrf="wrong")
    assert bad.status_code == 403
    assert crm.patches == []


async def test_crm_down_is_503(web: Web, crm: CrmProfile, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    crm.down = True
    response = await web.send("PATCH", "/api/v1/me/profile", json={"name": "X"})
    assert response.status_code == 503
    check(response, "/me/profile", "patch")


async def upload(web: Web, payload: bytes, mime: str) -> httpx.Response:
    return await web.client.request(
        "PUT",
        "/api/v1/me/avatar",
        content=part(payload, mime),
        headers={"content-type": MULTIPART, "x-csrf-token": web.csrf},
    )


async def test_avatar_upload_goes_to_crm_and_shows_in_me(
    web: Web, crm: CrmProfile, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    response = await upload(web, PNG, "image/png")
    assert response.status_code == 200, response.text
    check(response, "/me/avatar", "put")
    assert response.json()["avatar_url"] == "/api/v1/staff/7/avatar?v=1790000000"
    ((sent, content_type),) = crm.uploads
    assert PNG in sent
    assert content_type == MULTIPART
    me = (await web.client.get("/api/v1/me")).json()
    assert me["avatar_url"] == "/api/v1/staff/7/avatar?v=1790000000"

    removed = await web.send("DELETE", "/api/v1/me/avatar")
    check(removed, "/me/avatar", "delete")
    assert "avatar_url" not in removed.json()


async def test_unsupported_avatar_type_never_reaches_crm(
    web: Web, crm: CrmProfile, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    response = await upload(web, b"\x00" * 10, "image/svg+xml")
    assert response.status_code == 422
    check(response, "/me/avatar", "put")
    assert response.json()["details"] == {"fields": ["avatar"], "reason": "avatar_unsupported_type"}
    assert crm.uploads == []


async def test_oversized_avatar_is_cut_off_with_413(
    web: Web, crm: CrmProfile, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    response = await upload(web, b"\x00" * (1024 * 1024 + 70000), "image/png")
    assert response.status_code == 413
    check(response, "/me/avatar", "put")
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert response.json()["details"]["reason"] == "avatar_too_large"
    assert crm.uploads == []


async def test_oversized_avatar_without_content_length_is_cut_off_while_streaming(
    web: Web, crm: CrmProfile
) -> None:
    await web.login(["MANAGER"])

    async def body() -> AsyncIterator[bytes]:
        yield part(b"", "image/png")[: -len(b"\r\n--xyz--\r\n")]
        for _ in range(30):
            yield b"\x00" * 65536

    response = await web.client.request(
        "PUT",
        "/api/v1/me/avatar",
        content=body(),
        headers={"content-type": MULTIPART, "x-csrf-token": web.csrf},
    )
    assert response.status_code == 413
    assert crm.uploads == []


async def test_crm_413_is_translated(web: Web, crm: CrmProfile) -> None:
    await web.login(["MANAGER"])
    crm.refuse = (413, {"code": "payload_too_large", "message": "x", "details": {}})
    response = await upload(web, PNG, "image/png")
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


async def test_avatar_must_be_multipart(web: Web, crm: CrmProfile) -> None:
    await web.login(["MANAGER"])
    response = await web.client.request(
        "PUT",
        "/api/v1/me/avatar",
        content=PNG,
        headers={"content-type": "image/png", "x-csrf-token": web.csrf},
    )
    assert response.status_code == 422
    assert crm.uploads == []


async def test_crm_content_check_is_translated(web: Web, crm: CrmProfile) -> None:
    await web.login(["MANAGER"])
    crm.refuse = refusal(422, "avatar_type_mismatch", "avatar")
    response = await upload(web, PNG, "image/png")
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "avatar_type_mismatch"


async def test_staff_avatar_is_served_through_bff_with_safe_headers(
    web: Web, crm: CrmProfile
) -> None:
    await web.login(["MANAGER"])
    crm.avatar_file = httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})
    response = await web.client.get("/api/v1/staff/12/avatar")
    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"].startswith("private")
    assert "s3" not in response.text.lower()


async def test_staff_avatar_missing_or_not_an_image_is_404(
    web: Web, crm: CrmProfile, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    missing = await web.client.get("/api/v1/staff/12/avatar")
    check(missing, "/staff/{id}/avatar", "get")
    assert missing.status_code == 404
    crm.avatar_file = httpx.Response(
        200, content=b"<script>", headers={"content-type": "text/html"}
    )
    assert (await web.client.get("/api/v1/staff/12/avatar")).status_code == 404
    assert (await web.client.get("/api/v1/staff/abc/avatar")).status_code == 422


async def test_staff_avatar_needs_a_session(web: Web, crm: CrmProfile) -> None:
    assert (await web.client.get("/api/v1/staff/12/avatar")).status_code == 401


async def test_telegram_link_roundtrip(web: Web, crm: CrmProfile, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    made = await web.send("POST", "/api/v1/me/telegram-link")
    check(made, "/me/telegram-link", "post")
    assert made.json()["url"].startswith("https://t.me/rt_demo_bot?start=staff_")
    removed = await web.send("DELETE", "/api/v1/me/telegram-link")
    check(removed, "/me/telegram-link", "delete")
    assert removed.json()["telegram"] == {"linked": False}


@pytest.mark.parametrize(
    ("reason", "code"), [("bot_not_configured", "NOT_CONFIGURED"), ("bot_not_running", "CONFLICT")]
)
async def test_telegram_link_needs_a_bot(
    web: Web, crm: CrmProfile, check: ContractChecker, reason: str, code: str
) -> None:
    await web.login(["MANAGER"])
    crm.refuse = (409, {"code": "conflict", "message": "x", "details": {"reason": reason}})
    response = await web.send("POST", "/api/v1/me/telegram-link")
    assert response.status_code == 409
    check(response, "/me/telegram-link", "post")
    assert response.json()["code"] == code
    assert response.json()["details"]["reason"] == reason


async def test_deputy_roundtrip(web: Web, crm: CrmProfile, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    candidates = await web.client.get("/api/v1/me/deputy-candidates")
    check(candidates, "/me/deputy-candidates", "get")
    assert candidates.json() == [{"id": "11", "name": "Азиз К."}]

    saved = await web.send(
        "PUT",
        "/api/v1/me/deputy",
        json={"deputy_id": "11", "date_from": "2026-11-01", "date_to": "2026-11-10"},
    )
    assert saved.status_code == 200, saved.text
    check(saved, "/me/deputy", "put")
    assert crm.patches[-1] == {
        "deputy_user_id": 11, "date_from": "2026-11-01", "date_to": "2026-11-10",
    }  # fmt: skip
    assert saved.json()["deputy"]["name"] == "Азиз К."

    cleared = await web.send("DELETE", "/api/v1/me/deputy")
    check(cleared, "/me/deputy", "delete")
    assert "deputy" not in cleared.json()


@pytest.mark.parametrize(
    "reason",
    ["deputy_is_self", "deputy_period_reversed", "deputy_period_past", "deputy_not_colleague"],
)
async def test_deputy_errors_keep_the_reason(
    web: Web, crm: CrmProfile, check: ContractChecker, reason: str
) -> None:
    await web.login(["MANAGER"])
    crm.refuse = refusal(422, reason, "deputy_user_id")
    response = await web.send(
        "PUT",
        "/api/v1/me/deputy",
        json={"deputy_id": "11", "date_from": "2026-11-01", "date_to": "2026-11-10"},
    )
    assert response.status_code == 422
    check(response, "/me/deputy", "put")
    assert response.json()["details"] == {"fields": ["deputy_id"], "reason": reason}


@pytest.mark.parametrize(
    "payload",
    [
        {"deputy_id": "x", "date_from": "2026-11-01", "date_to": "2026-11-10"},
        {"deputy_id": "11", "date_from": "01.11.2026", "date_to": "2026-11-10"},
        {"deputy_id": "11", "date_from": "2026-11-01"},
    ],
)
async def test_deputy_body_is_validated(web: Web, crm: CrmProfile, payload: dict[str, str]) -> None:
    await web.login(["MANAGER"])
    assert (await web.send("PUT", "/api/v1/me/deputy", json=payload)).status_code == 422
    assert crm.patches == []
