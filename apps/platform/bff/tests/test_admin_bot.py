"""Admin · Настройки бота (W13-A5, контракт BFF 0.11.0): прокси к CRM, `/admin/bot/*`.

CRM — на respx (`kb_support`), ответы BFF проверяются по схемам platform-bff.yaml. Проверяется то,
что делает BFF: раздел каталога (чтение настроек — `admin: read`, правка, шаблоны и выгрузки —
`admin: full`, выгрузка ещё и чтение данных; 403 до CRM), токен сотрудника, значения настроек без
изменений, пути невалидных полей из CRM, выгрузка CSV потоком. Решения (значения, формат) — за CRM.
"""

import asyncio
import gzip
from collections.abc import MutableMapping
from typing import Any

import httpx
import pytest

from app.api.admin_bot import CsvStream
from app.clients.base import PROBE_TIMEOUT_SECONDS
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.kb_support import CSV_LEADS, Chunks, CrmBotFake, text3
from tests.roles import custom

BASE = "/api/v1/admin/bot"
READS: tuple[tuple[str, str], ...] = (
    (f"{BASE}/settings", "/admin/bot/settings"),
    (f"{BASE}/reply-templates", "/admin/bot/reply-templates"),
)
TEMPLATE = {"title": "Пришлю КП сегодня", "text": text3("{name}, пришлю КП", "Yuboraman", "Soon")}
WRITES: tuple[tuple[str, str, str, dict[str, Any] | None], ...] = (
    ("PUT", f"{BASE}/settings/company", "/admin/bot/settings/{key}", {"name": "RailTech (демо)"}),
    (
        "POST",
        f"{BASE}/settings/escalation/dry-run",
        "/admin/bot/settings/escalation/dry-run",
        {"sla_minutes": 10},
    ),
    ("POST", f"{BASE}/reply-templates", "/admin/bot/reply-templates", TEMPLATE),
    ("PUT", f"{BASE}/reply-templates/4", "/admin/bot/reply-templates/{id}", TEMPLATE),
    ("DELETE", f"{BASE}/reply-templates/4", "/admin/bot/reply-templates/{id}", None),
)
ENTITIES = ("leads", "clients", "deals")


@pytest.fixture
def crm(be: Backends) -> CrmBotFake:
    return CrmBotFake(be)


# --- права: раздел каталога, до CRM -------------------------------------------------------------


@pytest.mark.parametrize("role", ["MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"])
async def test_role_without_admin_gets_403_on_every_endpoint(
    web: Web, crm: CrmBotFake, role: str
) -> None:
    """Нет раздела `admin` — 403 в BFF на каждом эндпоинте, CRM не вызывается.

    Исключение — шаблоны ответов для менеджера (`crm.leads` полный): они нужны ему в карточке лида.
    """
    await web.login([role])
    before = crm.count

    for url, _ in READS:
        if role == "MANAGER" and url.endswith("reply-templates"):
            continue
        assert (await web.client.get(url)).status_code == 403, url
    for method, url, _, body in WRITES:
        response = await web.send(method, url, json=body)  # type: ignore[arg-type]
        assert response.status_code == 403, (method, url)
        assert response.json()["details"] == {"resource": "admin", "need": "full"}
    for entity in ENTITIES:
        assert (await web.client.get(f"{BASE}/exports/{entity}")).status_code == 403
    assert crm.count == before


async def test_manager_reads_reply_templates_only(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])

    templates = await web.client.get(f"{BASE}/reply-templates")
    settings = await web.client.get(f"{BASE}/settings")

    assert templates.status_code == 200
    check(templates, "/admin/bot/reply-templates", "get")
    assert settings.status_code == 403
    assert settings.json()["details"] == {"resource": "admin", "need": "read"}


async def test_director_reads_but_every_change_is_403(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    """Директор (`admin: read`) читает настройки и шаблоны; правка, прогон и выгрузка — 403."""
    await web.login(["DIRECTOR"])

    for url, template in READS:
        response = await web.client.get(url)
        assert response.status_code == 200, url
        check(response, template, "get")
    reads = crm.count
    for method, url, _, body in WRITES:
        response = await web.send(method, url, json=body)  # type: ignore[arg-type]
        assert response.status_code == 403, (method, url)
        assert response.json()["details"] == {"resource": "admin", "need": "full"}
    for entity in ENTITIES:
        assert (await web.client.get(f"{BASE}/exports/{entity}")).status_code == 403
    assert crm.count == reads


async def test_session_and_csrf_are_required(web: Web, crm: CrmBotFake) -> None:
    anonymous = await web.client.get(f"{BASE}/settings")
    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "SESSION_EXPIRED"

    await web.login(["ADMIN"])
    no_csrf = await web.send("PUT", f"{BASE}/settings/company", json={"name": "x"}, csrf="x")
    assert no_csrf.status_code == 403
    assert no_csrf.json()["code"] == "CSRF_FAILED"
    assert crm.requests("PUT", "settings/company") == []


# --- каждый эндпоинт: админ, токен сотрудника, ответ по контракту --------------------------------


@pytest.mark.parametrize(("url", "template"), READS)
async def test_admin_reads_every_endpoint_with_staff_token(
    web: Web, crm: CrmBotFake, check: ContractChecker, url: str, template: str
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get(url)

    assert response.status_code == 200
    check(response, template, "get")
    for call in crm.calls:
        assert call.headers["authorization"].startswith("Bearer crm-access-")


@pytest.mark.parametrize(("method", "url", "template", "body"), WRITES)
async def test_admin_runs_every_action(
    web: Web,
    crm: CrmBotFake,
    check: ContractChecker,
    method: str,
    url: str,
    template: str,
    body: dict[str, Any] | None,
) -> None:
    await web.login(["ADMIN"])

    response = await web.send(method, url, json=body)  # type: ignore[arg-type]

    expected = 201 if method == "POST" and url.endswith("reply-templates") else 200
    assert response.status_code == expected, response.text
    check(response, template, method.lower())
    sent = crm.calls[-1]
    assert sent.method == method
    assert sent.headers["authorization"].startswith("Bearer crm-access-")


# --- настройки ----------------------------------------------------------------------------------


async def test_settings_pass_values_and_schemas_as_they_are(web: Web, crm: CrmBotFake) -> None:
    await web.login(["ADMIN"])

    body = (await web.client.get(f"{BASE}/settings")).json()

    assert body["values"]["company"]["name"] == "RailTech (демо)"
    assert body["schemas"]["texts"]["properties"]["greeting"] == {"$ref": "#/$defs/L"}
    assert set(body) == {"values", "schemas"}


async def test_saving_a_section_sends_the_body_unchanged(web: Web, crm: CrmBotFake) -> None:
    await web.login(["ADMIN"])
    texts = {"greeting": text3("Здравствуйте!", "Salom!", "Hello!"), "note": {"nested": [1, 2]}}

    response = await web.send("PUT", f"{BASE}/settings/texts", json=texts)

    assert response.status_code == 200
    assert crm.body("PUT", "settings/texts") == texts


async def test_invalid_value_comes_back_with_field_paths(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    crm.error(
        "PUT",
        "settings/texts",
        422,
        "validation_failed",
        field="texts",
        paths=["greeting.uz", "help.en"],
    )
    await web.login(["ADMIN"])

    response = await web.send("PUT", f"{BASE}/settings/texts", json={"greeting": {}})

    assert response.status_code == 422
    check(response, "/admin/bot/settings/{key}", "put")
    error = response.json()
    assert error["code"] == "VALIDATION_FAILED"
    assert error["details"]["fields"] == ["texts"]
    assert error["details"]["paths"] == ["greeting.uz", "help.en"]


async def test_unknown_section_is_404_and_odd_key_never_reaches_crm(
    web: Web, crm: CrmBotFake
) -> None:
    crm.error("PUT", "settings/nope", 404, "not_found")
    await web.login(["ADMIN"])

    missing = await web.send("PUT", f"{BASE}/settings/nope", json={})
    odd = await web.send("PUT", f"{BASE}/settings/Co..mpany", json={})

    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
    assert odd.status_code == 422
    assert len(crm.requests("PUT", "settings/nope")) == 1
    assert crm.count == 1


async def test_dry_run_sends_only_the_given_rules_and_waits_like_a_probe(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send(
        "POST",
        f"{BASE}/settings/escalation/dry-run",
        json={
            "sla_minutes": 10,
            "disabled_triggers": ["complaint"],
            "price_always_to_manager": False,
        },
    )

    assert response.status_code == 200
    check(response, "/admin/bot/settings/escalation/dry-run", "post")
    assert crm.body("POST", "settings/escalation/dry-run") == {
        "sla_minutes": 10,
        "disabled_triggers": ["complaint"],
        "price_always_to_manager": False,
    }
    timeout = crm.last("POST", "settings/escalation/dry-run").extensions["timeout"]["read"]
    assert timeout == PROBE_TIMEOUT_SECONDS
    result = response.json()
    assert (result["escalated_current"], result["escalated_candidate"]) == (12, 9)
    assert result["changed"][0]["candidate"] == []


async def test_dry_run_rejects_values_outside_crm_limits_before_crm(
    web: Web, crm: CrmBotFake
) -> None:
    await web.login(["ADMIN"])

    for body in (
        {"high_score_threshold": 101},
        {"sla_minutes": 0},
        {"qualifier_min_confidence": 1.5},
        {"unknown_rule": 1},
    ):
        response = await web.send("POST", f"{BASE}/settings/escalation/dry-run", json=body)
        assert response.status_code == 422, body
    assert crm.count == 0


# --- шаблоны ответов ----------------------------------------------------------------------------


async def test_template_goes_to_crm_with_all_three_languages(web: Web, crm: CrmBotFake) -> None:
    await web.login(["ADMIN"])

    created = await web.send("POST", f"{BASE}/reply-templates", json=TEMPLATE)
    updated = await web.send("PUT", f"{BASE}/reply-templates/4", json=TEMPLATE)

    assert created.json() == {"id": 9}
    assert updated.json() == {"id": None, "ok": True}
    assert crm.body("POST", "reply-templates") == TEMPLATE
    assert crm.body("PUT", "reply-templates/4") == TEMPLATE


async def test_template_without_ru_text_is_refused_by_crm_and_shown_as_validation(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    crm.error("POST", "reply-templates", 422, "validation_failed", field="text")
    await web.login(["ADMIN"])

    response = await web.send(
        "POST", f"{BASE}/reply-templates", json={"title": "Пусто", "text": text3("", "", "")}
    )

    assert response.status_code == 422
    check(response, "/admin/bot/reply-templates", "post")
    assert response.json()["details"]["fields"] == ["text"]


@pytest.mark.parametrize(
    "body",
    [
        {"title": "", "text": text3("а")},
        {"title": "я" * 121, "text": text3("а")},
        {"title": "ок", "text": {"ru": "а"}},
        {"title": "ок", "text": text3("а"), "extra": 1},
    ],
)
async def test_template_shape_is_checked_in_bff(
    web: Web, crm: CrmBotFake, body: dict[str, Any]
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/reply-templates", json=body)

    assert response.status_code == 422
    assert crm.count == 0


async def test_deleting_a_missing_template_is_404(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    crm.error("DELETE", "reply-templates/8", 404, "not_found")
    await web.login(["ADMIN"])

    response = await web.send("DELETE", f"{BASE}/reply-templates/8")

    assert response.status_code == 404
    check(response, "/admin/bot/reply-templates/{id}", "delete")


# --- выгрузки CSV -------------------------------------------------------------------------------


@pytest.fixture
def exporter(crm: CrmBotFake) -> CrmBotFake:
    return crm


async def test_admin_alone_cannot_export_business_data(web: Web, crm: CrmBotFake) -> None:
    """Системная «Администратор» без второй роли бизнес-данные не выгружает (R3-D-2): 403 до CRM."""
    await web.login(["ADMIN"])

    leads = await web.client.get(f"{BASE}/exports/leads")
    clients = await web.client.get(f"{BASE}/exports/clients")
    deals = await web.client.get(f"{BASE}/exports/deals")

    assert leads.status_code == 403
    assert leads.json()["details"] == {"resource": "crm.leads", "need": "read"}
    assert clients.json()["details"] == {"resource": "crm.clients", "need": "read"}
    assert deals.json()["details"] == {"resource": "crm.clients", "need": "read"}
    assert crm.count == 0


@pytest.mark.parametrize("entity", ENTITIES)
async def test_admin_with_data_role_downloads_csv_as_a_stream(
    web: Web, crm: CrmBotFake, check: ContractChecker, entity: str
) -> None:
    await web.login(["ADMIN", "MANAGER"])

    response = await web.client.get(f"{BASE}/exports/{entity}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{entity}-20261026-1430.csv"'
    )
    assert response.content.decode("utf-8") == CSV_LEADS
    # поток: BFF не знает длины файла заранее; ответ CRM прочитан кусками и закрыт
    assert "content-length" not in response.headers
    (stream,) = crm.streams
    assert stream.sent == 2
    assert stream.closed is True
    sent = crm.last("GET", f"export/{entity}.csv")
    assert sent.headers["authorization"].startswith("Bearer crm-access-")
    assert sent.extensions["timeout"]["read"] == PROBE_TIMEOUT_SECONDS


async def test_each_export_forwards_only_its_own_filters(web: Web, crm: CrmBotFake) -> None:
    await web.login(["ADMIN", "MANAGER"])
    query = (
        "q=Анна&stage=won&language=uz&created_from=2026-10-01T00:00:00Z"
        "&created_to=2026-10-26T00:00:00Z&closed_from=2026-09-01&closed_to=2026-09-30"
    )

    await web.client.get(f"{BASE}/exports/leads?{query}")
    await web.client.get(f"{BASE}/exports/clients?{query}")
    await web.client.get(f"{BASE}/exports/deals?{query}")

    leads = dict(crm.last("GET", "export/leads.csv").url.params)
    assert set(leads) == {"q", "stage", "language", "created_from", "created_to"}
    assert leads["q"] == "Анна"
    assert dict(crm.last("GET", "export/clients.csv").url.params) == {"q": "Анна"}
    assert dict(crm.last("GET", "export/deals.csv").url.params) == {
        "stage": "won",
        "closed_from": "2026-09-01",
        "closed_to": "2026-09-30",
    }


async def test_export_filters_are_validated_before_crm(web: Web, crm: CrmBotFake) -> None:
    await web.login(["ADMIN", "MANAGER"])

    for query in ("language=de", "created_from=вчера", "closed_to=30.09.2026", "q=" + "я" * 101):
        response = await web.client.get(f"{BASE}/exports/leads?{query}")
        assert response.status_code == 422, query
    assert (await web.client.get(f"{BASE}/exports/orders")).status_code == 422
    assert crm.count == 0


async def test_export_filename_gets_a_date_when_crm_gives_none_or_something_odd(
    web: Web, crm: CrmBotFake
) -> None:
    await web.login(["ADMIN", "MANAGER"])
    crm.answer(
        "GET",
        "export/leads.csv",
        200,
        None,
        content=b"ID\r\n1\r\n",
        headers={"content-type": "text/csv", "content-disposition": 'attachment; filename="../x"'},
    )

    response = await web.client.get(f"{BASE}/exports/leads")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="leads-')
    assert disposition.endswith('.csv"')
    assert ".." not in disposition
    assert response.content == b"ID\r\n1\r\n"


async def test_export_refused_by_crm_is_an_error_and_the_stream_is_closed(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    crm.error("GET", "export/leads.csv", 403, "forbidden")
    await web.login(["ADMIN", "MANAGER"])

    response = await web.client.get(f"{BASE}/exports/leads")

    assert response.status_code == 403
    check(response, "/admin/bot/exports/{entity}", "get")
    assert response.json()["code"] == "FORBIDDEN"
    assert response.json()["source"] == "crm"


async def test_export_when_crm_is_down_is_503(web: Web, crm: CrmBotFake) -> None:
    crm.error("GET", "export/clients.csv", 500, "internal")
    await web.login(["ADMIN", "MANAGER"])

    response = await web.client.get(f"{BASE}/exports/clients")

    assert response.status_code == 503
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"


async def test_role_with_admin_and_clients_exports_clients_but_not_leads(
    web: Web, crm: CrmBotFake
) -> None:
    role = custom(21, "Администратор и клиенты", {"admin": "full", "crm.clients": "read"})
    await web.login([role])

    clients = await web.client.get(f"{BASE}/exports/clients")
    deals = await web.client.get(f"{BASE}/exports/deals")
    leads = await web.client.get(f"{BASE}/exports/leads")

    assert (clients.status_code, deals.status_code, leads.status_code) == (200, 200, 403)


# --- выгрузка: обрыв клиента и сжатие ответа CRM -------------------------------------------------


async def test_export_stream_closes_crm_response_when_client_disconnects() -> None:
    """Клиент оборвал загрузку после первого куска: ответ CRM закрывается, остаток не читается."""
    stream = Chunks([b"ID\r\n", b"1\r\n", b"2\r\n"])
    upstream = httpx.Response(200, stream=stream)
    sent: list[str] = []
    first_chunk_sent = asyncio.Event()

    async def receive() -> dict[str, str]:
        await first_chunk_sent.wait()
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message["type"])
        if message["type"] == "http.response.body":
            first_chunk_sent.set()
            await asyncio.sleep(0)  # отдать управление: слушатель обрыва успевает сработать

    response = CsvStream(upstream, headers={"Content-Disposition": 'attachment; filename="a.csv"'})
    await response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send)

    assert stream.closed is True
    assert stream.sent < 3  # весь файл не читался


async def test_export_stream_closes_crm_response_after_the_whole_file() -> None:
    stream = Chunks([b"ID\r\n", b"1\r\n"])
    upstream = httpx.Response(200, stream=stream)
    bodies: list[bytes] = []

    async def receive() -> dict[str, str]:
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.body":
            bodies.append(message["body"])

    await CsvStream(upstream, headers={})(
        {"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send
    )

    assert b"".join(bodies) == b"ID\r\n1\r\n"
    assert stream.closed is True


async def test_export_of_a_compressed_crm_answer_reaches_the_browser_as_plain_text(
    web: Web, crm: CrmBotFake
) -> None:
    """CRM ответила gzip: BFF отдаёт распакованный CSV и не передаёт `Content-Encoding`."""
    csv = CSV_LEADS.encode("utf-8")
    crm.answer(
        "GET",
        "export/leads.csv",
        200,
        None,
        content=gzip.compress(csv),
        headers={
            "content-type": "text/csv",
            "content-encoding": "gzip",
            "content-disposition": 'attachment; filename="leads-20261026-1430.csv"',
        },
    )
    await web.login(["ADMIN", "MANAGER"])

    response = await web.client.get(f"{BASE}/exports/leads")

    assert response.status_code == 200
    assert response.content == csv
    assert "content-encoding" not in response.headers
