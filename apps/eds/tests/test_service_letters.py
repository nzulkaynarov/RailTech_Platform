"""Сервисная выдача PDF отправленного исходящего письма для кабинета через ERP (ADR-0026, pg).

Только по сервисному токену ERP (оба токена ротации), только `letter_out` с номером ИСХ и итоговым PDF; черновик,
проект PDF, служебная записка и чужой токен — 401 или 404 без подробностей.
"""

import httpx
import pytest

from app.container import Container
from tests.conftest import ACCESS_SECRET, ERP_SERVICE_TOKEN, ERP_SERVICE_TOKEN_PREVIOUS
from tests.domain import Person
from tests.signing import sign_out
from tests.test_api_auth import assert_error
from tests.test_letterhead_letters import PDF, StubRenderer, deliver_letterhead, letter_json, run

pytestmark = pytest.mark.pg


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_erp_reads_only_the_final_pdf_of_a_sent_letter(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    registrar = staff["registrar"]
    await deliver_letterhead(client, container)
    doc = (await client.post("/api/v1/documents", json=letter_json(), headers=registrar.headers)).json()
    path = f"/api/v1/service/letters/{doc['id']}/pdf"

    # Черновик: даже с готовым проектом PDF — не отдаётся.
    await client.post(f"/api/v1/documents/{doc['id']}/pdf", headers=registrar.headers)
    assert await run(container, StubRenderer(), deferred[-1]) == "ready"
    assert_error(await client.get(path, headers=bearer(ERP_SERVICE_TOKEN)), 404, "NOT_FOUND")

    sent = await sign_out(client, staff, doc["id"])
    assert sent.status_code == 200 and sent.json()["status"] == "sent", sent.text
    # Номер выдан, итоговый PDF ещё готовится — 404.
    assert_error(await client.get(path, headers=bearer(ERP_SERVICE_TOKEN)), 404, "NOT_FOUND")
    assert await run(container, StubRenderer(), deferred[-1]) == "ready"

    for token in (ERP_SERVICE_TOKEN, ERP_SERVICE_TOKEN_PREVIOUS):
        pdf = await client.get(path, headers=bearer(token))
        assert pdf.status_code == 200 and pdf.content == PDF
        assert pdf.headers["content-type"] == "application/pdf"
        assert sent.json()["number"].replace("/", "-") in pdf.headers["content-disposition"]


async def test_service_path_rejects_staff_tokens_and_foreign_documents(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    registrar = staff["registrar"]
    memo = (
        await client.post(
            "/api/v1/documents", json={"kind": "memo", "subject": "СЗ", "text": "—"}, headers=registrar.headers
        )
    ).json()
    path = f"/api/v1/service/letters/{memo['id']}/pdf"
    assert_error(await client.get(path), 401, "UNAUTHORIZED", reason="missing")
    assert_error(await client.get(path, headers=bearer(ACCESS_SECRET)), 401, "UNAUTHORIZED", reason="invalid")
    # Токен сотрудника (доступ EDS) — не сервисный токен.
    assert_error(await client.get(path, headers=registrar.headers), 401, "UNAUTHORIZED", reason="invalid")
    assert_error(await client.get(path, headers=bearer(ERP_SERVICE_TOKEN)), 404, "NOT_FOUND")
    missing = "/api/v1/service/letters/00000000-0000-0000-0000-000000000000/pdf"
    assert_error(await client.get(missing, headers=bearer(ERP_SERVICE_TOKEN)), 404, "NOT_FOUND")
