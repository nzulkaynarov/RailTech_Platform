"""Admin · Компания (W13-A3, контракт 0.8.0): `/admin/company*` — прокси к ERP с токеном сотрудника.

ERP — на respx; ответы BFF проверяются по схемам platform-bff.yaml. Решения (права `settings.edit`,
администратор платформы, «строка используется») — за ERP: здесь проверяется перевод в контракт,
поиск своей компании по профилю сотрудника, вырезание маржи и то, что без раздела
`company.settings` BFF не вызывает ERP вообще.
"""

import json
from typing import Any

import httpx
import pytest
import respx

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.roles import custom

API = f"{ERP_URL}/api/v1"
CID = 3
COMPANY = f"{API}/accounts/companies/{CID}"
NOW = "2026-10-26T09:00:00Z"


def erp_company(be: Backends, own: int | None = CID) -> respx.Route:
    """Статус первого запуска ERP: id своей компании — 3 (`own_company_id`)."""
    body = {"setup_required": own is None, "can_setup": False, "own_company_id": own}
    return be.router.get(f"{API}/setup/status/").mock(return_value=httpx.Response(200, json=body))


@pytest.fixture
def erp(be: Backends) -> respx.MockRouter:
    erp_company(be)
    return be.router


def sent(route: respx.Route) -> Any:
    return json.loads(route.calls.last.request.content)


def company_json(**extra: Any) -> dict[str, Any]:
    return {
        "id": CID,
        "name": "ООО «Демо Рейл»",
        "inn": "123456789",
        "bank_account": "20208000900000000001",
        "mfo": "00001",
        "legal_address": "г. Демоград, ул. Вымышленная, 1",
        "phone": "+998 00 000 00 00",
        "contact_person": "Демо Директоров",
        "website": "",
        "email": "info@demo.example",
        "country": 1,
        "has_iso9001": False,
        "logo": None,
        "trust_score": 90,
        **extra,
    }


# --- права: без раздела BFF не ходит в ERP ------------------------------------------------------

READS: tuple[tuple[str, str], ...] = (
    ("GET", "/admin/company"),
    ("GET", "/admin/company/brand"),
    ("GET", "/admin/company/numbering"),
    ("GET", "/admin/company/quote-defaults"),
    ("GET", "/admin/company/charge-types"),
    ("GET", "/admin/company/charge-templates"),
    ("GET", "/admin/company/document-templates"),
    ("GET", "/admin/company/document-templates/placeholders"),
    ("GET", "/admin/company/email-templates"),
    ("GET", "/admin/company/reference/countries"),
    ("GET", "/admin/company/categories"),
    ("GET", "/admin/company/category-requests"),
    ("GET", "/admin/company/platform-settings"),
    ("GET", "/admin/company/fx-rate"),
    ("POST", "/admin/company/brand/preview"),
    ("POST", "/admin/company/numbering/preview"),
    ("POST", "/admin/company/document-templates/preview"),
    ("POST", "/admin/company/email-templates/5/preview"),
)
WRITES: tuple[tuple[str, str], ...] = (
    ("PATCH", "/admin/company"),
    ("POST", "/admin/company/logo"),
    ("DELETE", "/admin/company/logo"),
    ("PATCH", "/admin/company/brand"),
    ("POST", "/admin/company/brand/logo"),
    ("PATCH", "/admin/company/numbering"),
    ("PATCH", "/admin/company/quote-defaults"),
    ("POST", "/admin/company/charge-templates"),
    ("PATCH", "/admin/company/charge-templates/5"),
    ("DELETE", "/admin/company/charge-templates/5"),
    ("POST", "/admin/company/document-templates"),
    ("PATCH", "/admin/company/document-templates/5"),
    ("DELETE", "/admin/company/document-templates/5"),
    ("POST", "/admin/company/document-templates/5/copy"),
    ("POST", "/admin/company/email-templates"),
    ("PATCH", "/admin/company/email-templates/5"),
    ("DELETE", "/admin/company/email-templates/5"),
    ("POST", "/admin/company/reference/units"),
    ("PATCH", "/admin/company/reference/units/5"),
    ("DELETE", "/admin/company/reference/units/5"),
    ("POST", "/admin/company/categories"),
    ("PATCH", "/admin/company/categories/5"),
    ("DELETE", "/admin/company/categories/5"),
    ("POST", "/admin/company/category-requests/5/approve"),
    ("POST", "/admin/company/category-requests/5/reject"),
    ("PATCH", "/admin/company/platform-settings"),
    ("POST", "/admin/company/fx-rate"),
)


async def call(web: Web, method: str, path: str, body: Any = None) -> httpx.Response:
    return await web.client.request(
        method,
        f"/api/v1{path}",
        json=body if body is not None else ({} if method != "GET" else None),
        headers={"X-CSRF-Token": web.csrf},
    )


@pytest.mark.parametrize("role", ["MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"])
async def test_without_company_settings_every_endpoint_is_403_and_erp_is_untouched(
    web: Web, erp: respx.MockRouter, role: str
) -> None:
    """Шаблонные роли раздела `company.settings` не имеют: 403 в BFF, до ERP запрос не доходит."""
    await web.login([role])

    for method, path in (*READS, *WRITES):
        response = await call(web, method, path)
        assert response.status_code == 403, (method, path)
        assert response.json()["details"]["resource"] == "company.settings", (method, path)
    erp_data_calls = [
        c
        for c in erp.calls
        if c.request.url.host == "erp.test" and "/auth/" not in c.request.url.path
    ]
    assert erp_data_calls == []


async def test_read_level_reads_but_does_not_change(
    web: Web, be: Backends, erp: respx.MockRouter, check: ContractChecker
) -> None:
    """Роль с `company.settings: read` читает и считает предпросмотры, но не меняет."""
    reader = custom(50, "Читатель настроек", {"company.settings": "read"})
    await web.login([reader])
    erp.get(f"{COMPANY}/").mock(return_value=httpx.Response(200, json=company_json()))
    erp.post(f"{COMPANY}/document-profile/preview/").mock(
        return_value=httpx.Response(200, text="<html>образец</html>")
    )

    assert (await call(web, "GET", "/admin/company")).status_code == 200
    preview = await call(web, "POST", "/admin/company/brand/preview", {"kind": "quote"})
    assert preview.status_code == 200
    for method, path in WRITES:
        response = await call(web, method, path)
        assert response.status_code == 403, (method, path)
        assert response.json()["details"] == {"resource": "company.settings", "need": "full"}


async def test_write_without_csrf_is_rejected(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["ADMIN"])

    response = await web.client.patch("/api/v1/admin/company", json={"name": "Х"})

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"


# --- своя компания -----------------------------------------------------------------------------


async def test_company_is_found_by_own_company_id_of_erp(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    route = erp.get(f"{COMPANY}/").mock(return_value=httpx.Response(200, json=company_json()))

    response = await web.client.get("/api/v1/admin/company")

    assert response.status_code == 200
    check(response, "/admin/company", "get")
    body = response.json()
    assert body["name"] == "ООО «Демо Рейл»"
    assert body["inn"] == "123456789"
    assert body["logo_url"] is None
    assert "trust_score" not in body
    assert route.call_count == 1
    assert route.calls.last.request.headers["authorization"].startswith("Bearer ")


async def test_company_from_membership_when_erp_has_no_own_company_id(
    web: Web, be: Backends
) -> None:
    """Старая ERP без `own_company_id` в статусе: основное активное членство сотрудника."""
    await web.login(["ADMIN"])
    be.router.get(f"{API}/setup/status/").mock(
        return_value=httpx.Response(200, json={"setup_required": False, "can_setup": False})
    )
    be.router.get(f"{API}/accounts/me/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "primary_company": None,
                "memberships": [
                    {"company": 9, "is_primary": False, "is_active": False},
                    {"company": 4, "is_primary": False, "is_active": True},
                    {"company": 3, "is_primary": True, "is_active": True},
                ],
            },
        )
    )
    route = be.router.get(f"{COMPANY}/").mock(return_value=httpx.Response(200, json=company_json()))

    assert (await web.client.get("/api/v1/admin/company")).status_code == 200
    assert route.call_count == 1


async def test_own_company_comes_from_setup_status_not_from_membership(
    web: Web, be: Backends, erp: respx.MockRouter
) -> None:
    """Администратор без членства (суперпользователь): профиль не нужен, id — из `setup/status/`."""
    await web.login(["ADMIN"])
    me = be.router.get(f"{API}/accounts/me/").mock(return_value=httpx.Response(200, json={}))
    be.router.get(f"{COMPANY}/").mock(return_value=httpx.Response(200, json=company_json()))

    response = await web.client.get("/api/v1/admin/company")

    assert response.status_code == 200
    assert me.call_count == 0


async def test_company_not_set_when_erp_has_no_own_company(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    """`own_company_id = null` — своей компании нет: 409 `COMPANY_NOT_SET` (первый запуск)."""
    await web.login(["DIRECTOR"])
    erp_company(be, own=None)

    response = await web.client.get("/api/v1/admin/company")

    assert response.status_code == 409
    check(response, "/admin/company", "get")
    assert response.json()["code"] == "COMPANY_NOT_SET"
    assert response.json()["source"] == "erp"


async def test_update_company_sends_only_the_changed_fields(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    route = erp.patch(f"{COMPANY}/").mock(
        return_value=httpx.Response(200, json=company_json(phone="+998 11 111 11 11"))
    )

    response = await web.send(
        "PATCH", "/api/v1/admin/company", json={"phone": "+998 11 111 11 11", "inn": None}
    )

    assert response.status_code == 200
    check(response, "/admin/company", "patch")
    assert sent(route) == {"phone": "+998 11 111 11 11", "inn": None}


async def test_update_company_erp_validation_is_422_with_fields(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.patch(f"{COMPANY}/").mock(
        return_value=httpx.Response(400, json={"inn": ["Введите 9 цифр."]})
    )

    response = await web.send("PATCH", "/api/v1/admin/company", json={"inn": "12"})

    assert response.status_code == 422
    check(response, "/admin/company", "patch")
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["source"] == "erp"
    assert body["details"]["fields"] == ["inn"]


async def test_update_company_rejects_empty_and_unknown_fields(
    web: Web, erp: respx.MockRouter
) -> None:
    await web.login(["DIRECTOR"])

    empty = await web.send("PATCH", "/api/v1/admin/company", json={})
    unknown = await web.send("PATCH", "/api/v1/admin/company", json={"trust_score": 100})
    null_name = await web.send("PATCH", "/api/v1/admin/company", json={"name": None})

    assert (empty.status_code, unknown.status_code, null_name.status_code) == (422, 422, 422)


async def test_erp_unavailable_is_503_from_erp(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["DIRECTOR"])
    erp.get(f"{COMPANY}/").mock(return_value=httpx.Response(500))

    response = await web.client.get("/api/v1/admin/company")

    assert response.status_code == 503
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"
    assert response.json()["source"] == "erp"


async def test_erp_forbidden_passes_through_as_erp_403(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    """Право на операцию решает ERP: отказ `settings.edit` — 403 с источником `erp`."""
    await web.login(["DIRECTOR"])
    erp.get(f"{COMPANY}/").mock(return_value=httpx.Response(403, json={"detail": "FORBIDDEN"}))

    response = await web.client.get("/api/v1/admin/company")

    assert response.status_code == 403
    assert response.json()["source"] == "erp"
    assert response.json()["details"]["backend_status"] == 403


# --- логотип -----------------------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


async def upload(
    web: Web, path: str, *, name: str = "logo.png", data: bytes = PNG
) -> httpx.Response:
    return await web.client.post(
        f"/api/v1{path}",
        files={"logo": (name, data, "image/png")},
        headers={"X-CSRF-Token": web.csrf},
    )


async def test_company_logo_is_forwarded_as_multipart(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    route = erp.post(f"{COMPANY}/upload-logo/").mock(
        return_value=httpx.Response(
            200, json=company_json(logo="https://erp-backend:8000/media/companies/3/logo/a1b2.png")
        )
    )

    response = await upload(web, "/admin/company/logo")

    assert response.status_code == 200
    check(response, "/admin/company/logo", "post")
    assert response.json()["logo_url"].startswith("/api/v1/admin/company/logo/image?v=")
    request = route.calls.last.request
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert PNG in request.content
    assert b'name="logo"' in request.content


async def test_logo_must_be_multipart_and_not_too_big(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["DIRECTOR"])
    route = erp.post(f"{COMPANY}/upload-logo/").mock(return_value=httpx.Response(200, json={}))

    wrong_type = await web.send("POST", "/api/v1/admin/company/logo", json={"logo": "x"})
    too_big = await upload(web, "/admin/company/logo", data=b"0" * (2 * 1024 * 1024 + 70_000))

    for response in (wrong_type, too_big):
        assert response.status_code == 422
        assert response.json()["details"]["fields"] == ["logo"]
    assert wrong_type.json()["details"]["reason"] == "multipart_required"
    assert too_big.json()["details"]["reason"] == "file_too_large"
    assert route.call_count == 0


async def test_logo_type_must_be_an_image_from_the_list(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["DIRECTOR"])
    route = erp.post(f"{COMPANY}/upload-logo/").mock(return_value=httpx.Response(200, json={}))

    html = await web.client.post(
        "/api/v1/admin/company/logo",
        files={"logo": ("logo.html", b"<script>1</script>", "text/html")},
        headers={"X-CSRF-Token": web.csrf},
    )
    other_field = await web.client.post(
        "/api/v1/admin/company/logo",
        files={"file": ("logo.png", PNG, "image/png")},
        headers={"X-CSRF-Token": web.csrf},
    )

    for response in (html, other_field):
        assert response.status_code == 422
        assert response.json()["details"] == {"fields": ["logo"], "reason": "unsupported_type"}
    assert route.call_count == 0


@pytest.mark.parametrize("mime", ["image/png", "image/jpeg", "image/webp", "image/svg+xml"])
async def test_logo_accepts_the_listed_types(web: Web, erp: respx.MockRouter, mime: str) -> None:
    await web.login(["DIRECTOR"])
    route = erp.post(f"{COMPANY}/upload-logo/").mock(
        return_value=httpx.Response(200, json=company_json())
    )

    response = await web.client.post(
        "/api/v1/admin/company/logo",
        files={"logo": ("logo", PNG, mime)},
        headers={"X-CSRF-Token": web.csrf},
    )

    assert response.status_code == 200
    assert route.call_count == 1


async def test_logo_images_are_served_by_the_bff_not_by_erp_address(
    web: Web, erp: respx.MockRouter
) -> None:
    """CSP не пускает адрес ERP: файл отдаёт BFF с защитными заголовками, чужие пути не берутся."""
    await web.login(["DIRECTOR"])
    erp.get(f"{COMPANY}/").mock(
        return_value=httpx.Response(
            200, json=company_json(logo="http://erp-backend:8000/media/companies/3/logo/a1b2.svg")
        )
    )
    erp.get(f"{COMPANY}/document-profile/").mock(
        return_value=httpx.Response(
            200,
            json=brand_json(
                logo_url="http://erp-backend:8000/media/companies/3/doc-profile/logo/c.png"
            ),
        )
    )
    file = erp.get(f"{ERP_URL}/media/companies/3/logo/a1b2.svg").mock(
        return_value=httpx.Response(
            200, content=b"<svg/>", headers={"content-type": "image/svg+xml"}
        )
    )
    erp.get(f"{ERP_URL}/media/companies/3/doc-profile/logo/c.png").mock(
        return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
    )

    company = await web.client.get("/api/v1/admin/company/logo/image")
    brand = await web.client.get("/api/v1/admin/company/brand/logo/image")

    assert (company.status_code, company.content) == (200, b"<svg/>")
    assert company.headers["content-type"] == "image/svg+xml"
    assert "sandbox" in company.headers["content-security-policy"]
    assert company.headers["x-content-type-options"] == "nosniff"
    assert company.headers["content-disposition"] == "inline"
    assert (brand.status_code, brand.content) == (200, PNG)
    assert file.call_count == 1


async def test_logo_image_404_when_no_logo_or_foreign_path(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["DIRECTOR"])
    erp.get(f"{COMPANY}/").mock(return_value=httpx.Response(200, json=company_json(logo=None)))
    erp.get(f"{COMPANY}/document-profile/").mock(
        return_value=httpx.Response(
            200,
            json=brand_json(
                logo_url="http://erp-backend:8000/media/companies/3/documents/secret.pdf"
            ),
        )
    )
    secret = erp.get(f"{ERP_URL}/media/companies/3/documents/secret.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF")
    )

    company = await web.client.get("/api/v1/admin/company/logo/image")
    brand = await web.client.get("/api/v1/admin/company/brand/logo/image")

    assert (company.status_code, brand.status_code) == (404, 404)
    assert secret.call_count == 0


async def test_logo_image_takes_only_own_company_files_within_the_size_cap(
    web: Web, erp: respx.MockRouter
) -> None:
    await web.login(["DIRECTOR"])
    erp.get(f"{COMPANY}/").mock(
        return_value=httpx.Response(
            200, json=company_json(logo="http://erp-backend:8000/media/companies/8/logo/other.png")
        )
    )
    erp.get(f"{COMPANY}/document-profile/").mock(
        return_value=httpx.Response(
            200,
            json=brand_json(
                logo_url="http://erp-backend:8000/media/companies/3/doc-profile/logo/big.png"
            ),
        )
    )
    foreign = erp.get(f"{ERP_URL}/media/companies/8/logo/other.png").mock(
        return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
    )
    erp.get(f"{ERP_URL}/media/companies/3/doc-profile/logo/big.png").mock(
        return_value=httpx.Response(
            200, content=b"0" * (5 * 1024 * 1024 + 1), headers={"content-type": "image/png"}
        )
    )

    company = await web.client.get("/api/v1/admin/company/logo/image")
    brand = await web.client.get("/api/v1/admin/company/brand/logo/image")

    assert (company.status_code, brand.status_code) == (404, 404)
    assert foreign.call_count == 0


async def test_logo_image_without_own_company_is_409(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp_company(be, own=None)

    for path in ("/admin/company/logo/image", "/admin/company/brand/logo/image"):
        response = await web.client.get(f"/api/v1{path}")
        assert response.status_code == 409
        check(response, path, "get")
        assert response.json()["code"] == "COMPANY_NOT_SET"


async def test_logo_image_needs_the_company_section(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["MANAGER"])

    for path in ("/admin/company/logo/image", "/admin/company/brand/logo/image"):
        assert (await web.client.get(f"/api/v1{path}")).status_code == 403


async def test_brand_preview_inlines_erp_logos_as_data(web: Web, erp: respx.MockRouter) -> None:
    """Образец под CSP Платформы: логотип ERP встроен данными, чужие картинки не трогаются."""
    await web.login(["DIRECTOR"])
    html = (
        '<img src="http://erp-backend:8000/media/companies/3/doc-profile/logo/c.png">'
        '<img src="https://other.example/media/companies/3/documents/x.png">'
    )
    erp.post(f"{COMPANY}/document-profile/preview/").mock(
        return_value=httpx.Response(200, text=html)
    )
    erp.get(f"{ERP_URL}/media/companies/3/doc-profile/logo/c.png").mock(
        return_value=httpx.Response(200, content=b"PNGDATA", headers={"content-type": "image/png"})
    )

    response = await web.send("POST", "/api/v1/admin/company/brand/preview", json={"kind": "quote"})

    body = response.json()["html"]
    assert 'src="data:image/png;base64,UE5HREFUQQ=="' in body
    assert "https://other.example/media/companies/3/documents/x.png" in body


async def test_delete_company_logo(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["DIRECTOR"])
    route = erp.delete(f"{COMPANY}/delete-logo/").mock(return_value=httpx.Response(204))

    response = await web.send("DELETE", "/api/v1/admin/company/logo")

    assert response.status_code == 204
    assert route.call_count == 1


# --- бланк и бренд -----------------------------------------------------------------------------


def brand_json(**extra: Any) -> dict[str, Any]:
    return {
        "id": 1,
        "company": CID,
        "logo": None,
        "logo_url": None,
        "legal_name": "ООО «Демо Рейл»",
        "inn": "123456789",
        "legal_address": "",
        "bank_details": "",
        "signatory_name": "Демо Директоров",
        "signatory_position": "Директор",
        "footer_text": "Спасибо за сотрудничество",
        "accent_color": "#1d4ed8",
        "secondary_color": "#475569",
        "layout_preset": "boxed",
        "font_family": "serif",
        "cover_letter_text": "",
        "show_cover_letter": True,
        "contract_acceptance_text": "",
        "contract_liability_text": "",
        "contract_extra_terms_text": "",
        "act_closing_text": "",
        "show_bank_in_header": False,
        "use_company_defaults": True,
        "show_logo": True,
        "show_lead_time": True,
        "show_fx_note": False,
        "inherited_preview": {
            "legal_address": "г. Демоград, ул. Вымышленная, 1",
            "bank": "р/с 2020…",
        },
        "created_at": NOW,
        "updated_at": NOW,
        **extra,
    }


async def test_brand_profile_get_patch_and_logo(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    erp.get(f"{COMPANY}/document-profile/").mock(
        return_value=httpx.Response(200, json=brand_json())
    )
    patch = erp.patch(f"{COMPANY}/document-profile/").mock(
        return_value=httpx.Response(200, json=brand_json(accent_color="#047857"))
    )
    logo = erp.post(f"{COMPANY}/document-profile/upload-logo/").mock(
        return_value=httpx.Response(
            200,
            json=brand_json(
                logo_url="https://erp-backend:8000/media/companies/3/doc-profile/logo/c3d4.png"
            ),
        )
    )

    got = await web.client.get("/api/v1/admin/company/brand")
    changed = await web.send(
        "PATCH", "/api/v1/admin/company/brand", json={"accent_color": "#047857"}
    )
    uploaded = await upload(web, "/admin/company/brand/logo")

    check(got, "/admin/company/brand", "get")
    check(changed, "/admin/company/brand", "patch")
    check(uploaded, "/admin/company/brand/logo", "post")
    assert got.json()["layout_preset"] == "boxed"
    assert got.json()["inherited"]["legal_address"].startswith("г. Демоград")
    assert changed.json()["accent_color"] == "#047857"
    assert sent(patch) == {"accent_color": "#047857"}
    assert uploaded.json()["logo_url"].startswith("/api/v1/admin/company/brand/logo/image?v=")
    assert logo.call_count == 1


async def test_brand_unknown_choice_falls_back_and_bad_color_is_422(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    erp.get(f"{COMPANY}/document-profile/").mock(
        return_value=httpx.Response(200, json=brand_json(layout_preset="", font_family=None))
    )
    erp.patch(f"{COMPANY}/document-profile/").mock(
        return_value=httpx.Response(400, json={"detail": "INVALID_ACCENT_COLOR"})
    )

    got = await web.client.get("/api/v1/admin/company/brand")
    bad = await web.send("PATCH", "/api/v1/admin/company/brand", json={"accent_color": "red"})

    check(got, "/admin/company/brand", "get")
    assert (got.json()["layout_preset"], got.json()["font_family"]) == ("light", "sans")
    assert bad.status_code == 422
    assert bad.json()["details"]["reason"] == "invalid_accent_color"


async def test_brand_preview_maps_kind_and_forwards_the_unsaved_draft(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    route = erp.post(f"{COMPANY}/document-profile/preview/").mock(
        return_value=httpx.Response(200, text="<html><body>Образец КП</body></html>")
    )

    response = await web.send(
        "POST",
        "/api/v1/admin/company/brand/preview",
        json={"kind": "letter", "draft": {"accent_color": "#047857"}},
    )

    assert response.status_code == 200
    check(response, "/admin/company/brand/preview", "post")
    assert response.json()["html"] == "<html><body>Образец КП</body></html>"
    assert sent(route) == {"doc_type": "DOC", "draft": {"accent_color": "#047857"}}
    unknown = await web.send("POST", "/api/v1/admin/company/brand/preview", json={"kind": "KP"})
    assert unknown.status_code == 422


# --- нумерация ---------------------------------------------------------------------------------


def scheme_json(**extra: Any) -> dict[str, Any]:
    return {
        "pattern": "{prefix}{type}-{YYYY}-{seq}",
        "padding": 5,
        "reset_period": "yearly",
        "start_value": 0,
        "prefix": "DEMO",
        "is_effective": True,
        "type_labels": {"KP": "КП", "CT": "ДОГ", "INV": "СЧ", "ACT": "АКТ", "DOC": "ПИС", "X": "?"},
        **extra,
    }


async def test_numbering_get_maps_document_kinds(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.get(f"{API}/crm/numbering-scheme/").mock(
        return_value=httpx.Response(200, json=scheme_json())
    )

    response = await web.client.get("/api/v1/admin/company/numbering")

    assert response.status_code == 200
    check(response, "/admin/company/numbering", "get")
    assert response.json()["type_labels"] == {
        "quote": "КП",
        "contract": "ДОГ",
        "invoice": "СЧ",
        "act": "АКТ",
        "letter": "ПИС",
    }


async def test_numbering_patch_saves_prefix_first_then_the_scheme(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    order: list[str] = []

    def settings(request: httpx.Request) -> httpx.Response:
        order.append("settings")
        return httpx.Response(200, json={"doc_number_prefix": "NEW"})

    def scheme(request: httpx.Request) -> httpx.Response:
        order.append("scheme")
        return httpx.Response(200, json=scheme_json(prefix="NEW", padding=6))

    settings_route = erp.patch(f"{COMPANY}/settings/").mock(side_effect=settings)
    scheme_route = erp.patch(f"{API}/crm/numbering-scheme/").mock(side_effect=scheme)

    response = await web.send(
        "PATCH",
        "/api/v1/admin/company/numbering",
        json={"prefix": " NEW ".strip(), "padding": 6, "type_labels": {"contract": "ДОГ"}},
    )

    assert response.status_code == 200
    check(response, "/admin/company/numbering", "patch")
    assert order == ["settings", "scheme"]
    assert sent(settings_route) == {"doc_number_prefix": "NEW"}
    assert sent(scheme_route) == {"padding": 6, "type_labels": {"CT": "ДОГ"}}
    assert response.json()["prefix"] == "NEW"


async def test_numbering_prefix_only_does_not_touch_the_scheme_write(
    web: Web, erp: respx.MockRouter
) -> None:
    await web.login(["DIRECTOR"])
    erp.patch(f"{COMPANY}/settings/").mock(return_value=httpx.Response(200, json={}))
    scheme_patch = erp.patch(f"{API}/crm/numbering-scheme/").mock(return_value=httpx.Response(200))
    erp.get(f"{API}/crm/numbering-scheme/").mock(
        return_value=httpx.Response(200, json=scheme_json(prefix="ZZ"))
    )

    response = await web.send("PATCH", "/api/v1/admin/company/numbering", json={"prefix": "ZZ"})

    assert response.status_code == 200
    assert response.json()["prefix"] == "ZZ"
    assert scheme_patch.call_count == 0


async def test_numbering_errors_invalid_mask_and_taken_prefix(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.patch(f"{API}/crm/numbering-scheme/").mock(
        return_value=httpx.Response(400, json={"detail": "INVALID_NUMBERING_PATTERN"})
    )
    erp.patch(f"{COMPANY}/settings/").mock(
        return_value=httpx.Response(400, json={"detail": "DOC_PREFIX_TAKEN"})
    )

    bad_mask = await web.send(
        "PATCH", "/api/v1/admin/company/numbering", json={"pattern": "{type}"}
    )
    taken = await web.send("PATCH", "/api/v1/admin/company/numbering", json={"prefix": "ACME"})
    bad_prefix = await web.send("PATCH", "/api/v1/admin/company/numbering", json={"prefix": "A B"})

    assert bad_mask.status_code == 422
    check(bad_mask, "/admin/company/numbering", "patch")
    assert bad_mask.json()["details"]["reason"] == "invalid_numbering_pattern"
    assert bad_mask.json()["details"]["fields"] == ["pattern"]
    assert taken.status_code == 409
    check(taken, "/admin/company/numbering", "patch")
    assert taken.json()["code"] == "CONFLICT"
    assert taken.json()["details"] == {
        "backend_status": 400,
        "backend_code": "DOC_PREFIX_TAKEN",
        "reason": "doc_prefix_taken",
        "fields": ["prefix"],
    }
    assert bad_prefix.status_code == 422


async def test_numbering_preview_maps_kinds_both_ways(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    route = erp.post(f"{API}/crm/numbering-scheme/preview/").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"type_code": "KP", "label": "КП", "number": "DEMO-КП-2026-00001"},
                    {"type_code": "CT", "label": "ДОГ", "number": "DEMO-ДОГ-2026-00001"},
                    {"type_code": "ZZ", "label": "?", "number": "x"},
                ]
            },
        )
    )

    response = await web.send(
        "POST",
        "/api/v1/admin/company/numbering/preview",
        json={
            "pattern": "{prefix}{type}-{YYYY}-{seq}",
            "padding": 5,
            "reset_period": "yearly",
            "start_value": 0,
            "prefix": "DEMO",
            "type_labels": {"contract": "ДОГ"},
        },
    )

    assert response.status_code == 200
    check(response, "/admin/company/numbering/preview", "post")
    assert response.json()["items"] == [
        {"kind": "quote", "label": "КП", "number": "DEMO-КП-2026-00001"},
        {"kind": "contract", "label": "ДОГ", "number": "DEMO-ДОГ-2026-00001"},
    ]
    assert sent(route)["type_labels"] == {"CT": "ДОГ"}


# --- условия КП: маржа — группа cost_margin ----------------------------------------------------


def settings_json(**extra: Any) -> dict[str, Any]:
    return {
        "id": 1,
        "company": CID,
        "default_cost_currency_code": "USD",
        "default_delivery_basis_code": "FCA",
        "default_vat_rate": "12.00",
        "default_margin_percent": "18.00",
        "min_margin_percent": "5.00",
        "target_margin_percent": "20.00",
        "default_offer_validity_days": 14,
        "payment_terms_days": None,
        "default_payment_terms": "Предоплата 30%",
        "default_warranty_months": 12,
        "catalog_price_visibility": "cabinet",
        "catalog_publish_threshold": 70,
        "fx_rate_max_age_days": 7,
        "doc_number_prefix": "DEMO",
        "created_at": NOW,
        "updated_at": NOW,
        **extra,
    }


async def test_quote_defaults_director_sees_margins(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.get(f"{COMPANY}/settings/").mock(return_value=httpx.Response(200, json=settings_json()))

    response = await web.client.get("/api/v1/admin/company/quote-defaults")

    assert response.status_code == 200
    check(response, "/admin/company/quote-defaults", "get")
    body = response.json()
    assert body["default_cost_currency"] == "USD"
    assert body["default_delivery_basis"] == "FCA"
    assert body["default_margin_percent"] == "18.00"
    assert body["min_margin_percent"] == "5.00"
    assert "doc_number_prefix" not in body


async def test_quote_defaults_administrator_does_not_get_margin_fields(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    """Администратор не видит группу `cost_margin` (каталог): поля маржи вырезаются из ответа."""
    await web.login(["ADMIN"])
    erp.get(f"{COMPANY}/settings/").mock(return_value=httpx.Response(200, json=settings_json()))

    response = await web.client.get("/api/v1/admin/company/quote-defaults")

    check(response, "/admin/company/quote-defaults", "get")
    body = response.json()
    assert not {"default_margin_percent", "min_margin_percent", "target_margin_percent"} & set(body)
    assert body["default_vat_rate"] == "12.00"
    assert "18.00" not in response.text


async def test_quote_defaults_patch_margin_without_the_group_is_403_before_erp(
    web: Web, erp: respx.MockRouter
) -> None:
    await web.login(["ADMIN"])
    route = erp.patch(f"{COMPANY}/settings/").mock(return_value=httpx.Response(200, json={}))

    response = await web.send(
        "PATCH",
        "/api/v1/admin/company/quote-defaults",
        json={"default_vat_rate": "12", "min_margin_percent": "3"},
    )

    assert response.status_code == 403
    assert response.json()["details"] == {
        "resource": "company.settings",
        "restricted": "cost_margin",
        "fields": ["min_margin_percent"],
    }
    assert route.call_count == 0


async def test_quote_defaults_patch_sends_codes_and_returns_masked_result(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    route = erp.patch(f"{COMPANY}/settings/").mock(
        return_value=httpx.Response(
            200, json=settings_json(default_cost_currency_code="UZS", default_vat_rate="15.00")
        )
    )

    response = await web.send(
        "PATCH",
        "/api/v1/admin/company/quote-defaults",
        json={"default_cost_currency": "UZS", "default_vat_rate": "15", "payment_terms_days": None},
    )

    assert response.status_code == 200
    check(response, "/admin/company/quote-defaults", "patch")
    assert sent(route) == {
        "default_cost_currency": "UZS",
        "default_vat_rate": "15",
        "payment_terms_days": None,
    }
    assert response.json()["default_cost_currency"] == "UZS"
    assert "min_margin_percent" not in response.json()


async def test_quote_defaults_validation_codes_become_fields(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.patch(f"{COMPANY}/settings/").mock(
        return_value=httpx.Response(400, json={"detail": "BAD_CURRENCY"})
    )

    response = await web.send(
        "PATCH", "/api/v1/admin/company/quote-defaults", json={"default_cost_currency": "XXX"}
    )

    assert response.status_code == 422
    check(response, "/admin/company/quote-defaults", "patch")
    assert response.json()["details"]["fields"] == ["default_cost_currency"]
    too_big = await web.send(
        "PATCH", "/api/v1/admin/company/quote-defaults", json={"catalog_publish_threshold": 101}
    )
    assert too_big.status_code == 422


# --- статьи расхода ----------------------------------------------------------------------------


def charge_json(**extra: Any) -> dict[str, Any]:
    return {
        "id": 5,
        "delivery_basis": "FCA",
        "delivery_basis_name": "FCA — франко-перевозчик",
        "charge_type": "FREIGHT",
        "charge_type_name": "Фрахт",
        "default_amount": "150.00",
        "default_rate_percent": None,
        "is_deduction": False,
        "sort_order": 1,
        "is_active": True,
        **extra,
    }


async def test_charge_types_and_templates_crud(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.get(f"{API}/crm/charge-types/").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "code": "FREIGHT", "name": "Фрахт"}])
    )
    erp.get(f"{API}/crm/charge-templates/").mock(
        return_value=httpx.Response(200, json=[charge_json()])
    )
    create = erp.post(f"{API}/crm/charge-templates/").mock(
        return_value=httpx.Response(201, json=charge_json(id=6, charge_type="INSURANCE"))
    )
    patch = erp.patch(f"{API}/crm/charge-templates/5/").mock(
        return_value=httpx.Response(200, json=charge_json(default_amount="200.00"))
    )
    delete = erp.delete(f"{API}/crm/charge-templates/5/").mock(return_value=httpx.Response(204))

    types = await web.client.get("/api/v1/admin/company/charge-types")
    listed = await web.client.get("/api/v1/admin/company/charge-templates")
    created = await web.send(
        "POST",
        "/api/v1/admin/company/charge-templates",
        json={"delivery_basis": "FCA", "charge_type": "INSURANCE", "default_amount": "10"},
    )
    changed = await web.send(
        "PATCH", "/api/v1/admin/company/charge-templates/5", json={"default_amount": "200"}
    )
    removed = await web.send("DELETE", "/api/v1/admin/company/charge-templates/5")

    check(types, "/admin/company/charge-types", "get")
    check(listed, "/admin/company/charge-templates", "get")
    assert created.status_code == 201
    check(created, "/admin/company/charge-templates", "post")
    check(changed, "/admin/company/charge-templates/{id}", "patch")
    assert removed.status_code == 204
    assert listed.json()["items"][0]["id"] == "5"
    assert listed.json()["items"][0]["charge_type_name"] == "Фрахт"
    assert sent(create) == {
        "delivery_basis": "FCA",
        "charge_type": "INSURANCE",
        "default_amount": "10",
    }
    assert sent(patch) == {"default_amount": "200"}
    assert delete.call_count == 1


async def test_charge_template_unknown_id_is_404_and_bad_id_is_422(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.patch(f"{API}/crm/charge-templates/99/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )

    missing = await web.send(
        "PATCH", "/api/v1/admin/company/charge-templates/99", json={"sort_order": 2}
    )
    bad = await web.send(
        "PATCH", "/api/v1/admin/company/charge-templates/abc", json={"sort_order": 2}
    )

    assert missing.status_code == 404
    check(missing, "/admin/company/charge-templates/{id}", "patch")
    assert bad.status_code == 422


# --- шаблоны документов ------------------------------------------------------------------------


def doc_template_json(**extra: Any) -> dict[str, Any]:
    return {
        "id": 7,
        "name": "Договор поставки",
        "kind": "CONTRACT",
        "kind_code": "CONTRACT",
        "kind_name": "Договор",
        "body_html": "<p>{{buyer_name}}</p>",
        "placeholders_used": ["buyer_name"],
        "is_sample": False,
        "is_active": True,
        "is_owned": True,
        "created_at": NOW,
        "updated_at": NOW,
        **extra,
    }


async def test_document_templates_crud_copy_preview_and_placeholders(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.get(f"{API}/crm/document-templates/").mock(
        return_value=httpx.Response(
            200, json=[doc_template_json(), doc_template_json(id=8, is_sample=True, is_owned=False)]
        )
    )
    create = erp.post(f"{API}/crm/document-templates/").mock(
        return_value=httpx.Response(201, json=doc_template_json(id=9, name="Акт"))
    )
    erp.get(f"{API}/crm/document-templates/placeholders/").mock(
        return_value=httpx.Response(
            200,
            json={
                "groups": [
                    {
                        "key": "deal",
                        "label": "Данные заявки",
                        "items": [{"code": "buyer_name", "label": "Покупатель"}],
                    }
                ],
                "required_blocks": {},
            },
        )
    )
    preview = erp.post(f"{API}/crm/document-templates/preview/").mock(
        return_value=httpx.Response(
            200,
            json={
                "rendered_html": "<p>Покупатель</p>",
                "document_html": "<html><p>Покупатель</p></html>",
                "placeholders_used": ["buyer_name"],
                "warnings": ["Нет блока подписи"],
            },
        )
    )
    patch = erp.patch(f"{API}/crm/document-templates/7/").mock(
        return_value=httpx.Response(200, json=doc_template_json(is_active=False))
    )
    copy = erp.post(f"{API}/crm/document-templates/8/copy/").mock(
        return_value=httpx.Response(200, json=doc_template_json(id=10, name="Копия"))
    )

    listed = await web.client.get("/api/v1/admin/company/document-templates")
    created = await web.send(
        "POST",
        "/api/v1/admin/company/document-templates",
        json={"name": "Акт", "body_html": "<p/>"},
    )
    placeholders = await web.client.get("/api/v1/admin/company/document-templates/placeholders")
    rendered = await web.send(
        "POST",
        "/api/v1/admin/company/document-templates/preview",
        json={"body_html": "<p>{{x}}</p>"},
    )
    changed = await web.send(
        "PATCH", "/api/v1/admin/company/document-templates/7", json={"is_active": False}
    )
    copied = await web.send(
        "POST", "/api/v1/admin/company/document-templates/8/copy", json={"name": "Копия"}
    )

    check(listed, "/admin/company/document-templates", "get")
    assert [(t["id"], t["is_sample"]) for t in listed.json()["items"]] == [
        ("7", False),
        ("8", True),
    ]
    assert created.status_code == 201
    check(created, "/admin/company/document-templates", "post")
    check(placeholders, "/admin/company/document-templates/placeholders", "get")
    assert placeholders.json()["groups"][0]["items"][0]["code"] == "buyer_name"
    check(rendered, "/admin/company/document-templates/preview", "post")
    assert rendered.json() == {
        "html": "<html><p>Покупатель</p></html>",
        "warnings": ["Нет блока подписи"],
    }
    check(changed, "/admin/company/document-templates/{id}", "patch")
    check(copied, "/admin/company/document-templates/{id}/copy", "post")
    assert sent(create) == {"name": "Акт", "body_html": "<p/>"}
    assert sent(preview) == {"body_html": "<p>{{x}}</p>"}
    assert sent(patch) == {"is_active": False}
    assert sent(copy) == {"name": "Копия"}


async def test_document_template_kind_goes_to_erp_as_a_code_and_comes_back_as_a_word(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    """B-012 (W15-H8): вид выбирается при создании и предпросмотр идёт на каркасе своего вида."""
    await web.login(["DIRECTOR"])
    create = erp.post(f"{API}/crm/document-templates/").mock(
        return_value=httpx.Response(
            201, json=doc_template_json(id=9, kind="DELIVERY_NOTE", kind_code="DELIVERY_NOTE")
        )
    )
    preview = erp.post(f"{API}/crm/document-templates/preview/").mock(
        return_value=httpx.Response(
            200, json={"rendered_html": "<p>x</p>", "document_html": "<p>x</p>", "warnings": []}
        )
    )
    erp.get(f"{API}/crm/document-templates/").mock(
        return_value=httpx.Response(
            200,
            json=[
                doc_template_json(kind="WEIRD", kind_code="WEIRD"),
                doc_template_json(id=8, kind="ACT", kind_code="ACT"),
            ],
        )
    )

    created = await web.send(
        "POST",
        "/api/v1/admin/company/document-templates",
        json={"name": "Накладная", "kind": "delivery_note"},
    )
    rendered = await web.send(
        "POST",
        "/api/v1/admin/company/document-templates/preview",
        json={"body_html": "<p/>", "kind": "contract"},
    )
    listed = await web.client.get("/api/v1/admin/company/document-templates")
    bad = await web.send(
        "POST", "/api/v1/admin/company/document-templates", json={"name": "X", "kind": "poem"}
    )

    assert sent(create) == {"name": "Накладная", "kind": "DELIVERY_NOTE"}
    assert created.json()["kind"] == "delivery_note"
    check(created, "/admin/company/document-templates", "post")
    assert sent(preview) == {"body_html": "<p/>", "kind": "CONTRACT"}
    check(rendered, "/admin/company/document-templates/preview", "post")
    assert [t["kind"] for t in listed.json()["items"]] == ["custom", "act"]  # чужой код — «custom»
    check(listed, "/admin/company/document-templates", "get")
    assert bad.status_code == 422


async def test_document_template_in_use_is_409(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.delete(f"{API}/crm/document-templates/7/").mock(
        return_value=httpx.Response(400, json={"detail": "TEMPLATE_IN_USE"})
    )

    response = await web.send("DELETE", "/api/v1/admin/company/document-templates/7")

    assert response.status_code == 409
    check(response, "/admin/company/document-templates/{id}", "delete")
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["details"]["reason"] == "template_in_use"


async def test_document_template_without_required_blocks_names_them(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    """C2A-G-5: отказ ERP по составу блоков доезжает с названиями блоков, а не только кодом."""
    await web.login(["DIRECTOR"])
    blocks = [
        {"code": "doc.spec_table", "label": "Блок: спецификация (Приложение № 1)"},
        {"code": "doc.totals", "label": "Блок: итоги и НДС"},
    ]
    erp.patch(f"{API}/crm/document-templates/7/").mock(
        return_value=httpx.Response(
            400, json={"detail": "TEMPLATE_MISSING_REQUIRED_BLOCKS", "missing_blocks": blocks}
        )
    )

    response = await web.send(
        "PATCH", "/api/v1/admin/company/document-templates/7", json={"body_html": "{{buyer_name}}"}
    )

    assert response.status_code == 422
    check(response, "/admin/company/document-templates/{id}", "patch")
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["details"]["reason"] == "template_missing_required_blocks"
    assert body["details"]["missing_blocks"] == blocks
    assert "fields" not in body["details"]  # блоки — не поле формы


async def test_document_template_blocks_in_a_malformed_erp_body_are_dropped(
    web: Web, erp: respx.MockRouter
) -> None:
    await web.login(["DIRECTOR"])
    erp.post(f"{API}/crm/document-templates/").mock(
        return_value=httpx.Response(
            400,
            json={
                "detail": "TEMPLATE_MISSING_REQUIRED_BLOCKS",
                "missing_blocks": ["doc.totals", {"code": 5}],
            },
        )
    )

    response = await web.send(
        "POST",
        "/api/v1/admin/company/document-templates",
        json={"name": "Договор", "kind": "CONTRACT", "body_html": "x"},
    )

    assert response.status_code == 422
    assert "missing_blocks" not in response.json()["details"]


# --- шаблоны писем -----------------------------------------------------------------------------


def email_json(**extra: Any) -> dict[str, Any]:
    return {
        "id": 4,
        "key": "invoice_issued",
        "language": "ru",
        "subject": "Счёт {{number}}",
        "html_body": "<p>Счёт</p>",
        "text_body": "Счёт",
        "available_variables": "number, amount",
        "is_active": True,
        "updated_by": 7,
        "updated_by_email": "admin@demo.example",
        "updated_at": NOW,
        **extra,
    }


async def test_email_templates_follow_pages_and_support_crud_and_preview(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])

    def page(request: httpx.Request) -> httpx.Response:
        number = int(request.url.params["page"])
        if number == 1:
            return httpx.Response(
                200,
                json={
                    "count": 2,
                    "next": f"{API}/settings/email-templates/?page=2",
                    "results": [email_json()],
                },
            )
        return httpx.Response(
            200,
            json={
                "count": 2,
                "next": None,
                "results": [email_json(id=5, key="act_issued", updated_by_email="")],
            },
        )

    listing = erp.get(f"{API}/settings/email-templates/").mock(side_effect=page)
    create = erp.post(f"{API}/settings/email-templates/").mock(
        return_value=httpx.Response(201, json=email_json(id=6))
    )
    patch = erp.patch(f"{API}/settings/email-templates/4/").mock(
        return_value=httpx.Response(200, json=email_json(subject="Новый"))
    )
    delete = erp.delete(f"{API}/settings/email-templates/4/").mock(return_value=httpx.Response(204))
    preview = erp.post(f"{API}/settings/email-templates/4/preview/").mock(
        return_value=httpx.Response(
            200,
            json={
                "key": "invoice_issued",
                "subject": "Счёт 1",
                "text_body": "t",
                "html_body": "<p>h</p>",
                "context_used": {},
            },
        )
    )

    listed = await web.client.get("/api/v1/admin/company/email-templates")
    created = await web.send(
        "POST",
        "/api/v1/admin/company/email-templates",
        json={"key": "x", "subject": "S", "text_body": "T"},
    )
    changed = await web.send(
        "PATCH", "/api/v1/admin/company/email-templates/4", json={"subject": "Новый"}
    )
    removed = await web.send("DELETE", "/api/v1/admin/company/email-templates/4")
    rendered = await web.send("POST", "/api/v1/admin/company/email-templates/4/preview")

    assert listing.call_count == 2
    check(listed, "/admin/company/email-templates", "get")
    assert [t["key"] for t in listed.json()["items"]] == ["invoice_issued", "act_issued"]
    assert listed.json()["items"][0]["updated_by"] == "admin@demo.example"
    assert "updated_by" not in listed.json()["items"][1]
    assert created.status_code == 201
    check(created, "/admin/company/email-templates", "post")
    check(changed, "/admin/company/email-templates/{id}", "patch")
    assert removed.status_code == 204
    check(rendered, "/admin/company/email-templates/{id}/preview", "post")
    assert rendered.json() == {"subject": "Счёт 1", "text_body": "t", "html_body": "<p>h</p>"}
    assert sent(create) == {"key": "x", "subject": "S", "text_body": "T"}
    assert sent(patch) == {"subject": "Новый"}
    assert delete.call_count == preview.call_count == 1


# --- справочники ------------------------------------------------------------------------------


async def test_reference_lists_include_inactive_and_only_kind_fields(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    currencies = erp.get(f"{API}/master-data/currencies/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "code": "USD",
                    "name": "Доллар США",
                    "sort_order": 1,
                    "is_active": True,
                    "symbol": "$",
                }
            ],
        )
    )
    countries = erp.get(f"{API}/master-data/countries/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 2,
                    "code": "UZ",
                    "name": "Узбекистан",
                    "sort_order": 0,
                    "is_active": False,
                    "alpha2": "UZ",
                    "alpha3": "UZB",
                    "iso_numeric": "860",
                    "vat_rate": None,
                }
            ],
        )
    )
    basis = erp.get(f"{API}/master-data/delivery-basis/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 3,
                    "code": "FCA",
                    "name": "FCA",
                    "sort_order": 0,
                    "is_active": True,
                    "description": "d",
                    "seller_pays_freight": False,
                }
            ],
        )
    )

    cur = await web.client.get("/api/v1/admin/company/reference/currencies")
    cou = await web.client.get("/api/v1/admin/company/reference/countries")
    bas = await web.client.get("/api/v1/admin/company/reference/delivery-basis")
    bad = await web.client.get("/api/v1/admin/company/reference/manufacturers")

    for response in (cur, cou, bas):
        check(response, "/admin/company/reference/{kind}", "get")
    assert currencies.calls.last.request.url.params["include_inactive"] == "1"
    assert countries.call_count == basis.call_count == 1
    assert cur.json()["items"][0] == {
        "id": "1",
        "code": "USD",
        "name": "Доллар США",
        "sort_order": 1,
        "is_active": True,
        "symbol": "$",
    }
    assert cou.json()["items"][0]["vat_rate"] is None
    assert cou.json()["items"][0]["is_active"] is False
    assert "symbol" not in cou.json()["items"][0]
    assert bas.json()["items"][0]["seller_pays_freight"] is False
    assert bad.status_code == 422


async def test_reference_create_update_delete_and_foreign_fields(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    create = erp.post(f"{API}/master-data/units/").mock(
        return_value=httpx.Response(
            201, json={"id": 9, "code": "PCS", "name": "шт.", "sort_order": 0, "is_active": True}
        )
    )
    patch = erp.patch(f"{API}/master-data/units/9/").mock(
        return_value=httpx.Response(
            200, json={"id": 9, "code": "PCS", "name": "штука", "sort_order": 0, "is_active": False}
        )
    )
    delete = erp.delete(f"{API}/master-data/units/9/").mock(return_value=httpx.Response(204))

    created = await web.send(
        "POST", "/api/v1/admin/company/reference/units", json={"code": "PCS", "name": "шт."}
    )
    changed = await web.send(
        "PATCH",
        "/api/v1/admin/company/reference/units/9",
        json={"name": "штука", "is_active": False},
    )
    removed = await web.send("DELETE", "/api/v1/admin/company/reference/units/9")
    foreign = await web.send(
        "POST",
        "/api/v1/admin/company/reference/units",
        json={"code": "KG", "name": "кг", "symbol": "$"},
    )

    assert created.status_code == 201
    check(created, "/admin/company/reference/{kind}", "post")
    check(changed, "/admin/company/reference/{kind}/{id}", "patch")
    assert removed.status_code == 204
    assert sent(create) == {"code": "PCS", "name": "шт."}
    assert sent(patch) == {"name": "штука", "is_active": False}
    assert delete.call_count == 1
    assert foreign.status_code == 422
    assert foreign.json()["details"] == {"fields": ["symbol"], "reason": "field_not_in_reference"}
    assert create.call_count == 1


async def test_reference_in_use_and_duplicate_code(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.delete(f"{API}/master-data/currencies/1/").mock(
        return_value=httpx.Response(400, json={"detail": "LOOKUP_IN_USE:Quote,Deal"})
    )
    erp.post(f"{API}/master-data/currencies/").mock(
        return_value=httpx.Response(400, json={"code": ["Валюта с таким кодом уже существует."]})
    )

    used = await web.send("DELETE", "/api/v1/admin/company/reference/currencies/1")
    duplicate = await web.send(
        "POST", "/api/v1/admin/company/reference/currencies", json={"code": "USD", "name": "Доллар"}
    )

    assert used.status_code == 409
    check(used, "/admin/company/reference/{kind}/{id}", "delete")
    assert used.json()["details"]["reason"] == "lookup_in_use"
    assert duplicate.status_code == 422
    assert duplicate.json()["details"]["fields"] == ["code"]


# --- категории и запросы на них ---------------------------------------------------------------


async def test_categories_follow_pages_and_crud(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])

    def page(request: httpx.Request) -> httpx.Response:
        if request.url.params["page"] == "1":
            return httpx.Response(
                200,
                json={
                    "count": 2,
                    "next": f"{API}/catalog/categories/?page=2",
                    "results": [{"id": 1, "name": "Рельсы", "parent": None, "domain_type": 3}],
                },
            )
        return httpx.Response(
            200,
            json={"count": 2, "next": None, "results": [{"id": 2, "name": "Крепёж", "parent": 1}]},
        )

    listing = erp.get(f"{API}/catalog/categories/").mock(side_effect=page)
    create = erp.post(f"{API}/catalog/categories/").mock(
        return_value=httpx.Response(201, json={"id": 3, "name": "Шпалы", "parent": 1})
    )
    patch = erp.patch(f"{API}/catalog/categories/3/").mock(
        return_value=httpx.Response(200, json={"id": 3, "name": "Шпалы ЖБ", "parent": None})
    )
    delete = erp.delete(f"{API}/catalog/categories/1/").mock(
        return_value=httpx.Response(400, json={"detail": "CATEGORY_HAS_CHILDREN"})
    )

    listed = await web.client.get("/api/v1/admin/company/categories")
    created = await web.send(
        "POST", "/api/v1/admin/company/categories", json={"name": "Шпалы", "parent_id": "1"}
    )
    changed = await web.send(
        "PATCH", "/api/v1/admin/company/categories/3", json={"name": "Шпалы ЖБ", "parent_id": None}
    )
    blocked = await web.send("DELETE", "/api/v1/admin/company/categories/1")

    assert listing.call_count == 2
    check(listed, "/admin/company/categories", "get")
    assert listed.json()["items"] == [
        {"id": "1", "name": "Рельсы", "parent_id": None},
        {"id": "2", "name": "Крепёж", "parent_id": "1"},
    ]
    assert created.status_code == 201
    check(created, "/admin/company/categories", "post")
    check(changed, "/admin/company/categories/{id}", "patch")
    assert sent(create) == {"name": "Шпалы", "parent": 1}
    assert sent(patch) == {"name": "Шпалы ЖБ", "parent": None}
    assert blocked.status_code == 409
    check(blocked, "/admin/company/categories/{id}", "delete")
    assert blocked.json()["details"]["reason"] == "category_has_children"
    assert delete.call_count == 1


def request_json(**extra: Any) -> dict[str, Any]:
    return {
        "id": 11,
        "company": CID,
        "company_name": "ООО «Демо Рейл»",
        "requested_by_email": "manager@demo.example",
        "proposed_name": "Стрелочные переводы",
        "parent": 1,
        "parent_name": "Рельсы",
        "domain_type": None,
        "domain_type_code": "",
        "justification": "Нужна для нового каталога",
        "status": "PENDING",
        "resulting_category": None,
        "resulting_category_name": "",
        "review_notes": "",
        "reviewed_at": None,
        "created_at": NOW,
        **extra,
    }


async def test_category_requests_list_filter_and_decisions(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    listing = erp.get(f"{API}/catalog/category-requests/").mock(
        return_value=httpx.Response(
            200, json={"count": 1, "next": None, "results": [request_json()]}
        )
    )
    approve = erp.post(f"{API}/catalog/category-requests/11/approve/").mock(
        return_value=httpx.Response(
            200,
            json=request_json(
                status="APPROVED",
                resulting_category=3,
                resulting_category_name="Стрелки",
                reviewed_at=NOW,
            ),
        )
    )
    reject = erp.post(f"{API}/catalog/category-requests/12/reject/").mock(
        return_value=httpx.Response(
            200, json=request_json(id=12, status="REJECTED", review_notes="Дубль", reviewed_at=NOW)
        )
    )

    listed = await web.client.get("/api/v1/admin/company/category-requests?status=pending")
    approved = await web.send(
        "POST", "/api/v1/admin/company/category-requests/11/approve", json={"category_id": "3"}
    )
    rejected = await web.send(
        "POST", "/api/v1/admin/company/category-requests/12/reject", json={"reason": " Дубль "}
    )
    no_reason = await web.send(
        "POST", "/api/v1/admin/company/category-requests/12/reject", json={"reason": ""}
    )
    bad_status = await web.client.get("/api/v1/admin/company/category-requests?status=PENDING")

    assert listing.calls.last.request.url.params["status"] == "PENDING"
    check(listed, "/admin/company/category-requests", "get")
    first = listed.json()["items"][0]
    assert first["status"] == "pending"
    assert first["requested_by"] == "manager@demo.example"
    assert "resulting_category_id" not in first
    check(approved, "/admin/company/category-requests/{id}/approve", "post")
    assert approved.json()["status"] == "approved"
    assert approved.json()["resulting_category_id"] == "3"
    assert sent(approve) == {"category": 3}
    check(rejected, "/admin/company/category-requests/{id}/reject", "post")
    assert rejected.json()["review_notes"] == "Дубль"
    assert sent(reject) == {"reason": "Дубль"}
    assert no_reason.status_code == 422
    assert bad_status.status_code == 422


async def test_category_request_decision_errors(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    """Решает администратор платформы в ERP: другим — 403 `erp`; решённый запрос — 409."""
    await web.login(["DIRECTOR"])
    erp.post(f"{API}/catalog/category-requests/11/approve/").mock(
        return_value=httpx.Response(403, json={"detail": "You do not have permission."})
    )
    erp.post(f"{API}/catalog/category-requests/12/reject/").mock(
        return_value=httpx.Response(400, json={"detail": "CATEGORY_REQUEST_ALREADY_REVIEWED"})
    )

    forbidden = await web.send(
        "POST", "/api/v1/admin/company/category-requests/11/approve", json={"category_id": "3"}
    )
    reviewed = await web.send(
        "POST", "/api/v1/admin/company/category-requests/12/reject", json={"reason": "Дубль"}
    )

    assert forbidden.status_code == 403
    check(forbidden, "/admin/company/category-requests/{id}/approve", "post")
    assert forbidden.json()["source"] == "erp"
    assert reviewed.status_code == 409
    check(reviewed, "/admin/company/category-requests/{id}/reject", "post")
    assert reviewed.json()["details"]["reason"] == "already_reviewed"


# --- платформенные настройки -------------------------------------------------------------------


async def test_platform_settings_get_and_patch(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    erp.get(f"{API}/system-settings/").mock(
        return_value=httpx.Response(
            200,
            json={
                "vat_rate": "12.00",
                "exchange_rate_usd_uzs": "12650.5000",
                "platform_name": "RailTech",
                "maintenance_mode": False,
                "updated_at": NOW,
            },
        )
    )
    patch = erp.patch(f"{API}/system-settings/").mock(
        return_value=httpx.Response(
            200, json={"vat_rate": "15.00", "exchange_rate_usd_uzs": None, "updated_at": NOW}
        )
    )

    got = await web.client.get("/api/v1/admin/company/platform-settings")
    changed = await web.send(
        "PATCH", "/api/v1/admin/company/platform-settings", json={"vat_rate": "15"}
    )
    bad = await web.send(
        "PATCH", "/api/v1/admin/company/platform-settings", json={"maintenance_mode": True}
    )

    check(got, "/admin/company/platform-settings", "get")
    assert got.json() == {
        "vat_rate": "12.00",
        "exchange_rate_usd_uzs": "12650.5000",
        "updated_at": NOW,
    }
    check(changed, "/admin/company/platform-settings", "patch")
    assert changed.json()["exchange_rate_usd_uzs"] is None
    assert sent(patch) == {"vat_rate": "15"}
    assert bad.status_code == 422


async def test_platform_settings_erp_forbids_non_superuser(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.patch(f"{API}/system-settings/").mock(
        return_value=httpx.Response(403, json={"detail": "You do not have permission."})
    )

    response = await web.send(
        "PATCH", "/api/v1/admin/company/platform-settings", json={"vat_rate": "15"}
    )

    assert response.status_code == 403
    check(response, "/admin/company/platform-settings", "patch")
    assert response.json()["source"] == "erp"


# --- курс USD→UZS: ручной ввод и журнал (W13C-F6) ----------------------------------------------

FX_CURRENT = {
    "currency": "USD",
    "current": {
        "currency": "USD",
        "rate_to_uzs": "12650.5",
        "rate_date": "2026-10-27",
        "source": "CBU",
    },
    "max_age_days": 7,
}
FX_JOURNAL = [
    {
        "id": 41,
        "kind": "manual",
        "currency": "USD",
        "rate_date": "2026-10-27",
        "rate_to_uzs": "12650.5",
        "previous_rate_to_uzs": "12600",
        "previous_source": "CBU",
        "entered_by_id": 7,
        "entered_by_email": "anna@demo.example",
        "entered_by_name": "Анна Иванова",
        "entered_at": NOW,
    },
    {
        "id": 40,
        "kind": "auto_skipped",
        "currency": "USD",
        "rate_date": "2026-10-26",
        "rate_to_uzs": "12610",
        "previous_rate_to_uzs": "12600",
        "previous_source": "MANUAL",
        "entered_by_id": None,
        "entered_by_email": "",
        "entered_by_name": "",
        "entered_at": NOW,
    },
]


def fx_erp(erp: respx.MockRouter, current: dict[str, Any] | None = None) -> dict[str, respx.Route]:
    return {
        "current": erp.get(f"{API}/exchange-rates/current/").mock(
            return_value=httpx.Response(200, json=current or FX_CURRENT)
        ),
        "journal": erp.get(f"{API}/exchange-rates/journal/").mock(
            return_value=httpx.Response(200, json=FX_JOURNAL)
        ),
    }


async def test_fx_rate_get_shows_current_rate_source_and_journal(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    routes = fx_erp(erp)

    response = await web.client.get("/api/v1/admin/company/fx-rate")

    assert response.status_code == 200
    check(response, "/admin/company/fx-rate", "get")
    body = response.json()
    assert body["current"] == {
        "rate_to_uzs": "12650.5",
        "rate_date": "2026-10-27",
        "source": "auto",
    }
    assert body["max_age_days"] == 7
    manual, skipped = body["journal"]
    assert (manual["id"], manual["kind"], manual["entered_by"]) == ("41", "manual", "Анна Иванова")
    assert (manual["previous_rate_to_uzs"], manual["previous_source"]) == ("12600", "auto")
    assert (skipped["kind"], skipped["entered_by"], skipped["previous_source"]) == (
        "auto_skipped",
        None,
        "manual",
    )
    assert routes["journal"].calls.last.request.url.params["limit"] == "20"
    assert routes["current"].calls.last.request.url.params["currency"] == "USD"


async def test_fx_rate_journal_erp_403_is_not_shown_to_the_caller(
    web: Web, erp: respx.MockRouter
) -> None:
    """Журнал курсов — только `settings.edit` в ERP (W15-H8): отказ ERP доходит 403, без имён."""
    await web.login(["DIRECTOR"])
    erp.get(f"{API}/exchange-rates/current/").mock(
        return_value=httpx.Response(200, json=FX_CURRENT)
    )
    erp.get(f"{API}/exchange-rates/journal/").mock(
        return_value=httpx.Response(403, json={"detail": "SETTINGS_EDIT_REQUIRED"})
    )

    response = await web.client.get("/api/v1/admin/company/fx-rate")

    assert response.status_code == 403
    assert response.json()["source"] == "erp"
    assert "Иванова" not in response.text


async def test_fx_rate_without_a_rate_is_null_not_zero(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    fx_erp(erp, {"currency": "USD", "current": None, "max_age_days": 7})

    response = await web.client.get("/api/v1/admin/company/fx-rate")

    check(response, "/admin/company/fx-rate", "get")
    assert response.json()["current"] is None


async def test_fx_rate_reader_sees_but_cannot_enter(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login([custom(50, "Читатель настроек", {"company.settings": "read"})])
    fx_erp(erp)

    got = await web.client.get("/api/v1/admin/company/fx-rate")
    posted = await web.send(
        "POST",
        "/api/v1/admin/company/fx-rate",
        json={"rate_date": "2026-10-27", "rate_to_uzs": "12700"},
    )

    assert got.status_code == 200
    assert posted.status_code == 403
    assert posted.json()["details"] == {"resource": "company.settings", "need": "full"}
    assert not [
        c
        for c in erp.calls
        if c.request.method == "POST" and "exchange-rates" in c.request.url.path
    ]


async def test_fx_rate_post_sends_usd_to_erp_and_returns_fresh_overview(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    fx_erp(erp)
    route = erp.post(f"{API}/exchange-rates/manual/").mock(
        return_value=httpx.Response(
            201,
            json={
                "currency": "USD",
                "rate_to_uzs": "12700",
                "rate_date": "2026-10-27",
                "source": "MANUAL",
            },
        )
    )

    response = await web.send(
        "POST",
        "/api/v1/admin/company/fx-rate",
        json={"rate_date": "2026-10-27", "rate_to_uzs": "12700"},
    )

    assert response.status_code == 201
    check(response, "/admin/company/fx-rate", "post")
    assert sent(route) == {"currency": "USD", "rate_date": "2026-10-27", "rate_to_uzs": "12700"}
    assert route.calls.last.request.headers["authorization"].startswith("Bearer ")
    assert response.json()["journal"][0]["id"] == "41"


@pytest.mark.parametrize(
    ("erp_code", "field"),
    [
        ("FX_RATE_INVALID", "rate_to_uzs"),
        ("FX_RATE_DATE_INVALID", "rate_date"),
        ("FX_RATE_DATE_IN_FUTURE", "rate_date"),
        ("FX_RATE_DATE_TOO_OLD", "rate_date"),
    ],
)
async def test_fx_rate_erp_refusal_points_at_the_field(
    web: Web, erp: respx.MockRouter, check: ContractChecker, erp_code: str, field: str
) -> None:
    await web.login(["ADMIN"])
    erp.post(f"{API}/exchange-rates/manual/").mock(
        return_value=httpx.Response(400, json={"detail": erp_code})
    )

    response = await web.send(
        "POST",
        "/api/v1/admin/company/fx-rate",
        json={"rate_date": "2026-10-27", "rate_to_uzs": "0"},
    )

    assert response.status_code == 422
    check(response, "/admin/company/fx-rate", "post")
    details = response.json()["details"]
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert details["fields"] == [field]
    assert details["reason"] == erp_code.lower()


async def test_fx_rate_erp_forbids_member_without_settings_edit(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    erp.post(f"{API}/exchange-rates/manual/").mock(
        return_value=httpx.Response(403, json={"detail": "ROLE_NOT_PERMITTED"})
    )

    response = await web.send(
        "POST",
        "/api/v1/admin/company/fx-rate",
        json={"rate_date": "2026-10-27", "rate_to_uzs": "12700"},
    )

    assert response.status_code == 403
    check(response, "/admin/company/fx-rate", "post")
    assert response.json()["source"] == "erp"


@pytest.mark.parametrize(
    "body",
    [
        {"rate_date": "27.10.2026", "rate_to_uzs": "12700"},
        {"rate_date": "2026-10-27", "rate_to_uzs": "abc"},
        {"rate_date": "2026-10-27"},
        {"rate_to_uzs": "12700"},
        {"rate_date": "2026-10-27", "rate_to_uzs": "12700", "currency": "EUR"},
    ],
)
async def test_fx_rate_bad_body_is_422_and_erp_is_not_called(
    web: Web, erp: respx.MockRouter, body: dict[str, str]
) -> None:
    await web.login(["ADMIN"])
    route = erp.post(f"{API}/exchange-rates/manual/").mock(
        return_value=httpx.Response(201, json={})
    )

    response = await web.send("POST", "/api/v1/admin/company/fx-rate", json=body)

    assert response.status_code == 422
    assert route.call_count == 0
