"""FX-2: решение сотрудника по документу, присланному партнёром — очередь, одобрение, отказ, права, журнал."""

import pytest
from django.core.files.base import ContentFile
from parties.models import Company

from catalog.models import DocumentKind, TechDocument
from catalog.published import client_visible_documents
from catalog.tests.desk_world import build_world
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
BASE = "/api/v1/catalog/tech-docs/"


@pytest.fixture
def world():
    return build_world()


@pytest.fixture
def pending(world):
    DocumentKind.objects.get_or_create(
        code="certificate", defaults={"name": "Сертификат", "is_active": True, "client_visible_default": True}
    )
    partner = Company.objects.create(name="Завод Север", inn="300000111")
    doc = TechDocument(
        kind="certificate",
        title="Сертификат партнёра",
        original_name="c.pdf",
        content_type="application/pdf",
        product=world["relay"],
        client_visible=False,
        review_state="pending",
        source_supplier=partner,
    )
    doc.file.save("c.pdf", ContentFile(PDF), save=True)
    return doc


def post(world, who, doc, body):
    return world["clients"][who].post(f"{BASE}{doc.pk}/review/", body, format="json")


def test_queue_lists_pending_with_partner_name(world, pending):
    response = world["clients"]["manager"].get(BASE, {"review_state": "pending"})
    assert response.status_code == 200
    rows = response.json()["results"]
    assert [(r["id"], r["review_state"], r["partner"]) for r in rows] == [(pending.pk, "pending", "Завод Север")]


def test_pending_document_is_hidden_from_clients_even_if_staff_flips_visibility(world, pending):
    # правка «видно клиенту» у документа на проверке не открывает его клиенту
    response = world["clients"]["engineer"].patch(f"{BASE}{pending.pk}/", {"client_visible": True}, format="json")
    assert response.status_code == 200
    pending.refresh_from_db()
    assert pending.client_visible is False
    assert not client_visible_documents().filter(pk=pending.pk).exists()
    # и даже принудительно выставленный флаг не обходит проверку
    TechDocument.objects.filter(pk=pending.pk).update(client_visible=True)
    assert not client_visible_documents().filter(pk=pending.pk).exists()


def test_approve_publishes_to_clients_and_is_journaled(world, pending):
    response = post(world, "engineer", pending, {"decision": "approve"})
    assert response.status_code == 200, response.content
    assert response.json()["review_state"] == "approved" and response.json()["client_visible"] is True
    assert client_visible_documents().filter(pk=pending.pk).exists()
    assert ActivityLog.objects.filter(event_code="admin.tech_doc.reviewed", entity_id=pending.pk).exists()


def test_approve_may_keep_the_document_internal(world, pending):
    response = post(world, "engineer", pending, {"decision": "approve", "client_visible": False})
    assert response.status_code == 200
    assert response.json()["review_state"] == "approved" and response.json()["client_visible"] is False
    assert not client_visible_documents().filter(pk=pending.pk).exists()


def test_reject_keeps_it_hidden(world, pending):
    response = post(world, "engineer", pending, {"decision": "reject"})
    assert response.status_code == 200 and response.json()["review_state"] == "rejected"
    assert not client_visible_documents().filter(pk=pending.pk).exists()


def test_second_decision_is_conflict(world, pending):
    assert post(world, "engineer", pending, {"decision": "reject"}).status_code == 200
    again = post(world, "engineer", pending, {"decision": "approve"})
    assert again.status_code == 409 and again.json() == {"detail": "TECH_DOC_NOT_PENDING"}
    pending.refresh_from_db()
    assert pending.review_state == "rejected"


def test_staff_without_manage_cannot_decide(world, pending):
    assert post(world, "manager", pending, {"decision": "approve"}).status_code == 403
    pending.refresh_from_db()
    assert pending.review_state == "pending"


def test_bad_decision_is_400(world, pending):
    assert post(world, "engineer", pending, {"decision": "maybe"}).status_code == 400
