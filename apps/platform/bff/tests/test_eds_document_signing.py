"""Тесты BFF для шага подписи исходящего документа (SIGN-3, ADR-0024)."""

import pytest

from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_documents_support import DOC_ID, EdsFake, document

BASE = "/api/v1/eds"


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    return EdsFake(be)


async def test_sign_eds_document_proxies_to_eds_and_matches_contract(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    signed_doc = document(
        kind="letter_out",
        status="sent",
        number="ИСХ-042/26",
    )
    signed_doc["signed_at"] = "2026-11-05T14:30:00Z"
    signed_doc["signed_by"] = {"crm_user_id": 3, "full_name": "Рустам Директоров"}
    signed_doc["signatory_basis"] = "charter"
    signed_doc["signatory_basis_text"] = None
    signed_doc["verification_code"] = "V7K9Q2P4M1"
    signed_doc["verification_url"] = "https://cabinet.railtech.uz/v/V7K9Q2P4M1"
    signed_doc["dispatch_method"] = "paper"

    eds.answer("POST", f"documents/{DOC_ID}/sign", 200, signed_doc)

    response = await web.client.post(
        f"{BASE}/documents/{DOC_ID}/sign",
        json={"dispatch_method": "paper", "send": False},
        headers={CSRF_HEADER: web.csrf},
    )

    assert response.status_code == 200, response.text
    check(response, "/eds/documents/{id}/sign", "post")
    data = response.json()
    assert data["number"] == "ИСХ-042/26"
    assert data["status"] == "sent"
    assert data["verification_code"] == "V7K9Q2P4M1"
    assert data["verification_url"] == "https://cabinet.railtech.uz/v/V7K9Q2P4M1"
    assert data["dispatch_method"] == "paper"
