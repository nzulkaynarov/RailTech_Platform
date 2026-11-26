"""ДП-1: «Есть замечания» в Кабинете — `POST /contracts/{id}/remarks`, DOCX для правок и защита «принять» при замечаниях.

Факт, из которого выводится ответ: строки `ContractRemark` и статус договора. Без защиты тесты краснеют: клиент не принимает
редакцию, пока замечания на согласовании; чужая компания и контакт без `can_act` — не подают замечаний.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from portal.tests.contract_support import check_response, response_schema

from crm.models import ContractRemark
from crm.services import contract_compare

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"


def uploaded(client, paragraphs, name="our.docx"):
    data = contract_compare.paragraphs_to_docx(paragraphs)
    response = client.post(
        f"{API}/uploads",
        {"file": SimpleUploadedFile(name, data, content_type="application/octet-stream")},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    return response.json()["upload_id"]


def post(client, contract, body):
    return client.post(f"{API}/contracts/{contract.pk}/remarks", body, format="json")


def test_remark_is_accepted_and_the_contract_shows_it_on_review(contract_world, portal_client):
    contract = contract_world["contracts"]["sent"]
    upload_id = uploaded(portal_client, ["1.1. Один.", "2.2. Предоплата 30 %."])
    response = post(portal_client, contract, {"comment": "Предоплата 30 %", "upload_id": upload_id})
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == "sent" and body["remark"]["state"] == "review"
    assert body["remark"]["file_name"] == "our.docx" and body["can_download_docx"] is True
    assert not check_response(body, response_schema("/contracts/{id}/remarks", "post", "201"))
    remark = ContractRemark.objects.get(contract=contract)
    assert remark.comment == "Предоплата 30 %" and remark.resolution == ""


def test_remark_without_a_file_is_fine_but_not_without_words(contract_world, portal_client):
    contract = contract_world["contracts"]["sent"]
    assert post(portal_client, contract, {"comment": ""}).status_code == 422
    assert post(portal_client, contract, {"comment": "Склад переехал"}).status_code == 201
    again = post(portal_client, contract, {"comment": "Ещё"})
    assert again.status_code == 409 and again.json() == {"detail": "REMARK_OPEN"}


def test_client_cannot_accept_the_edition_while_remarks_are_on_review(contract_world, portal_client):
    contract = contract_world["contracts"]["sent"]
    post(portal_client, contract, {"comment": "Правки"})
    response = portal_client.post(f"{API}/contracts/{contract.pk}/sign", {}, format="json")
    assert response.status_code == 409
    contract.refresh_from_db()
    assert contract.status.code == "PENDING_CLIENT"


def test_signed_contract_takes_no_remarks_and_docx_is_only_for_review(contract_world, portal_client):
    signed = contract_world["contracts"]["signed"]
    assert post(portal_client, signed, {"comment": "Поздно"}).status_code == 409
    assert portal_client.get(f"{API}/contracts/{signed.pk}/docx").status_code == 404


def test_docx_download_returns_our_edition_as_word(contract_world, portal_client):
    contract = contract_world["contracts"]["sent"]
    contract.frozen_template_body = "<p>1.1. Один.</p><p>2.2. Два.</p>"
    contract.save(update_fields=["frozen_template_body"])
    response = portal_client.get(f"{API}/contracts/{contract.pk}/docx")
    assert response.status_code == 200
    assert response["Content-Type"].endswith("wordprocessingml.document")
    assert contract_compare.docx_paragraphs(io.BytesIO(response.content)) == ["1.1. Один.", "2.2. Два."]


def test_other_company_and_read_only_contact_cannot_remark(contract_world, other_portal_client, readonly_portal_client):
    contract = contract_world["contracts"]["sent"]
    assert post(other_portal_client, contract, {"comment": "x"}).status_code == 404
    assert post(readonly_portal_client, contract, {"comment": "x"}).status_code == 403
    assert not ContractRemark.objects.exists()
