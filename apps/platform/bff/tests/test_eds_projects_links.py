"""EDS · Проекты: «Ссылка клиента в Кабинете» у договора, счёта и акта (ДК-3б).

ERP — на respx. Проверяется то, что делает BFF: документ берётся только из карточки этого
проекта (чужой id — 404 и в ERP не уходит), отзыв уходит на ЭТОТ документ, отказ ERP в праве
(403) на чтении — пустой список (блок скрыт), на отзыве — 403; адрес получателя приходит из ERP
уже замаскированным и в ответ идёт как есть.
"""

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_projects_support import (
    ACT_ID,
    CONTRACT_ID,
    DEAL,
    INVOICE_ID,
    ProjectsFake,
    act_card,
    card,
    contract_card,
    erp_error,
    invoice_card,
)

BASE = "/api/v1/eds/projects"
NUMBER = "ПР-2026-104"
DOCS = [
    ("contract", CONTRACT_ID, "contracts"),
    ("invoice", INVOICE_ID, "invoices"),
    ("act", ACT_ID, "acts"),
]
LINK = {
    "id": 5,
    "recipient_hint": "a***@client.example",
    "sent_at": "2026-11-24T09:00:00+05:00",
    "first_opened_at": None,
    "last_opened_at": None,
    "expires_at": "2026-12-30T23:59:59+05:00",
    "state": "active",
}


@pytest.fixture
def erp(be: Backends) -> ProjectsFake:
    fake = ProjectsFake(be)
    fake.cards[DEAL] = card(contract=contract_card(), act=act_card(), invoices=[invoice_card()])
    return fake


async def _as(web: Web, role: str = "ACCOUNTANT") -> None:
    assert (await web.login([role])).status_code == 200


@pytest.mark.parametrize(("kind", "doc_id", "slug"), DOCS)
async def test_the_list_comes_from_the_documents_own_erp_endpoint(
    web: Web, erp: ProjectsFake, check: ContractChecker, kind: str, doc_id: int, slug: str
) -> None:
    await _as(web)
    erp.answer(
        "GET",
        rf"{slug}/{doc_id}/client-links/",
        httpx.Response(200, json={"links": [LINK], "can_revoke": True}),
    )
    response = await web.client.get(f"{BASE}/{NUMBER}/documents/{kind}/{doc_id}/client-links")
    check(response, "/eds/projects/{ref}/documents/{kind}/{doc_id}/client-links", "get")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_revoke"] is True
    assert body["links"][0]["recipient_hint"] == "a***@client.example"
    assert "id" not in body["links"][0]


@pytest.mark.parametrize(("kind", "doc_id", "slug"), DOCS)
async def test_revoke_goes_to_this_document_only(
    web: Web, erp: ProjectsFake, check: ContractChecker, kind: str, doc_id: int, slug: str
) -> None:
    await _as(web)
    erp.answer(
        "POST",
        rf"{slug}/{doc_id}/revoke-client-links/",
        httpx.Response(200, json={"links": [{**LINK, "state": "revoked"}], "can_revoke": False}),
    )
    response = await web.send("POST", f"{BASE}/{NUMBER}/documents/{kind}/{doc_id}/revoke-links")
    check(response, "/eds/projects/{ref}/documents/{kind}/{doc_id}/revoke-links", "post")
    assert response.status_code == 200, response.text
    assert response.json()["links"][0]["state"] == "revoked"
    assert [c.url.path for c in erp.posts()] == [
        f"/api/v1/crm/{slug}/{doc_id}/revoke-client-links/"
    ]


@pytest.mark.parametrize("kind", ["contract", "invoice", "act"])
async def test_a_document_of_another_project_is_404_and_never_reaches_erp(
    web: Web, erp: ProjectsFake, kind: str
) -> None:
    await _as(web)
    before = len(erp.calls)
    got = await web.client.get(f"{BASE}/{NUMBER}/documents/{kind}/987654/client-links")
    sent = await web.send("POST", f"{BASE}/{NUMBER}/documents/{kind}/987654/revoke-links")
    assert (got.status_code, sent.status_code) == (404, 404)
    assert all("client-links" not in c.url.path for c in erp.calls[before:])


async def test_no_right_to_send_hides_the_list_and_refuses_the_revoke(
    web: Web, erp: ProjectsFake
) -> None:
    await _as(web, "MANAGER")
    erp.answer("GET", r"contracts/\d+/client-links/", erp_error(403, "ROLE_NOT_PERMITTED"))
    erp.answer("POST", r"contracts/\d+/revoke-client-links/", erp_error(403, "ROLE_NOT_PERMITTED"))
    listed = await web.client.get(f"{BASE}/{NUMBER}/documents/contract/{CONTRACT_ID}/client-links")
    assert listed.status_code == 200
    assert listed.json() == {"links": [], "can_revoke": False}
    revoked = await web.send(
        "POST", f"{BASE}/{NUMBER}/documents/contract/{CONTRACT_ID}/revoke-links"
    )
    assert revoked.status_code == 403


async def test_a_role_without_the_projects_section_is_refused_before_erp(
    web: Web, erp: ProjectsFake
) -> None:
    await _as(web, "ADMIN")
    response = await web.client.get(
        f"{BASE}/{NUMBER}/documents/contract/{CONTRACT_ID}/client-links"
    )
    assert response.status_code == 403
    assert erp.calls == []


@pytest.mark.parametrize("erp_status", [500, 502])
async def test_an_erp_failure_on_read_is_503_not_an_empty_list(
    web: Web, erp: ProjectsFake, erp_status: int
) -> None:
    await _as(web)
    erp.answer("GET", r"contracts/\d+/client-links/", erp_error(erp_status, "BOOM"))
    response = await web.client.get(
        f"{BASE}/{NUMBER}/documents/contract/{CONTRACT_ID}/client-links"
    )
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("kind", "other_id"),
    [("contract", INVOICE_ID), ("invoice", ACT_ID), ("act", CONTRACT_ID)],
)
async def test_an_id_of_another_kind_in_the_same_project_is_404_without_erp(
    web: Web, erp: ProjectsFake, kind: str, other_id: int
) -> None:
    await _as(web)
    before = len(erp.calls)
    got = await web.client.get(f"{BASE}/{NUMBER}/documents/{kind}/{other_id}/client-links")
    sent = await web.send("POST", f"{BASE}/{NUMBER}/documents/{kind}/{other_id}/revoke-links")
    assert (got.status_code, sent.status_code) == (404, 404)
    assert all("client-links" not in c.url.path for c in erp.calls[before:])


async def test_only_a_403_hides_the_list_other_erp_refusals_pass_through(
    web: Web, erp: ProjectsFake
) -> None:
    await _as(web)
    erp.answer("GET", r"contracts/\d+/client-links/", erp_error(404, "NOT_FOUND"))
    response = await web.client.get(
        f"{BASE}/{NUMBER}/documents/contract/{CONTRACT_ID}/client-links"
    )
    assert response.status_code == 404
