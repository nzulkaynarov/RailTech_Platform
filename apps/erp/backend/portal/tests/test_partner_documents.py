"""FX-2: документы товаров партнёра — видимость, загрузка на проверку, удаление только своего, аудит выдачи.

Дефекты аудита 2026-11-08: партнёр с одной ценой на чужой карточке читал все её `TechDocument`; загрузка сразу
`client_visible=True`; чужие документы удалялись без следа; нечисловой `upload_id` давал 500; файл загрузки не копировался;
скачивание не писалось в журнал.
"""

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from portal.models import PortalUpload
from portal.tests.partner_world import PREFIX

from catalog.models import DocumentKind, TechDocument
from catalog.published import client_visible_documents
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def staff_doc(product, title, *, visible):
    doc = TechDocument(
        kind="certificate",
        title=title,
        original_name=f"{title}.pdf",
        content_type="application/pdf",
        product=product,
        client_visible=visible,
        size_bytes=len(PDF),
    )
    doc.file.save(f"{title}.pdf", ContentFile(PDF), save=True)
    return doc


@pytest.fixture
def docs(partner_world):
    DocumentKind.objects.get_or_create(code="certificate", defaults={"name": "Сертификат", "is_active": True})
    cards = partner_world["cards"]
    return {
        # чужая опубликованная карточка, на которую у А есть цена
        "shared_public": staff_doc(cards["shared"], "Сертификат общий", visible=True),
        "shared_internal": staff_doc(cards["shared"], "Внутренний протокол", visible=False),
        # чужая неопубликованная карточка с ценой А
        "matched_public": staff_doc(cards["b_draft_with_a_offer"], "Паспорт Б-2", visible=True),
        # своя карточка А
        "own_public": staff_doc(cards["published"], "Сертификат А-4", visible=True),
        "own_internal": staff_doc(cards["published"], "Внутренний А-4", visible=False),
    }


def url(product, *tail):
    return "/".join([f"{PREFIX}/products/{product.pk}/documents", *map(str, tail)])


def titles(response):
    assert response.status_code == 200, response.content
    return sorted(item["title"] for item in response.json())


class TestVisibility:
    def test_price_only_partner_sees_client_visible_docs_of_published_card(self, partner_world, docs):
        response = partner_world["client_a"].get(url(partner_world["cards"]["shared"]))
        assert titles(response) == ["Сертификат общий"]

    def test_unpublished_foreign_card_gives_no_documents(self, partner_world, docs):
        client = partner_world["client_a"]
        card = partner_world["cards"]["b_draft_with_a_offer"]
        assert client.get(url(card)).json() == []
        assert client.get(url(card, docs["matched_public"].pk, "file")).status_code == 404

    def test_internal_doc_is_not_given_to_the_partner_even_on_own_card(self, partner_world, docs):
        client, card = partner_world["client_a"], partner_world["cards"]["published"]
        assert titles(client.get(url(card))) == ["Сертификат А-4"]
        assert client.get(url(card, docs["own_internal"].pk, "file")).status_code == 404
        detail = client.get(f"{PREFIX}/products/{card.pk}").json()
        assert [d["title"] for d in detail["documents"]] == ["Сертификат А-4"]

    def test_internal_doc_of_foreign_card_file_is_404(self, partner_world, docs):
        client, card = partner_world["client_a"], partner_world["cards"]["shared"]
        assert client.get(url(card, docs["shared_internal"].pk, "file")).status_code == 404

    def test_foreign_card_without_offer_is_404(self, partner_world, docs):
        card = partner_world["cards"]["b_only"]
        staff_doc(card, "Секрет Б", visible=True)
        assert partner_world["client_a"].get(url(card)).status_code == 404


class TestDownloadAudit:
    def test_download_is_written_to_the_journal(self, partner_world, docs):
        doc, card = docs["shared_public"], partner_world["cards"]["shared"]
        response = partner_world["client_a"].get(url(card, doc.pk, "file"))
        assert response.status_code == 200
        entry = ActivityLog.objects.get(event_code="document.downloaded_by_client", entity_id=doc.pk)
        assert entry.contact_id == partner_world["a_contact"].pk
        assert entry.event_params["product_id"] == card.pk
        assert entry.event_params["source"] == "catalog"

    def test_refused_download_leaves_no_record(self, partner_world, docs):
        card = partner_world["cards"]["shared"]
        partner_world["client_a"].get(url(card, docs["shared_internal"].pk, "file"))
        assert not ActivityLog.objects.filter(event_code="document.downloaded_by_client").exists()


class TestUpload:
    def _post(self, client, card, **fields):
        file = SimpleUploadedFile("cert.pdf", PDF, content_type="application/pdf")
        return client.post(url(card), {"file": file, "title": "Сертификат партнёра", **fields}, format="multipart")

    def test_partner_upload_waits_for_staff_and_is_hidden_from_clients(self, partner_world, docs):
        card = partner_world["cards"]["published"]
        # партнёр пытается объявить документ видимым клиенту — поле игнорируется
        response = self._post(partner_world["client_a"], card, client_visible="true")
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["status"] == "pending"
        doc = TechDocument.objects.get(pk=body["id"])
        assert doc.client_visible is False
        assert not client_visible_documents().filter(pk=doc.pk).exists()
        # самому партнёру свой документ виден, с пометкой «на проверке»
        listed = partner_world["client_a"].get(url(card)).json()
        assert {(d["title"], d["status"], d["can_delete"]) for d in listed} == {
            ("Сертификат А-4", "approved", False),
            ("Сертификат партнёра", "pending", True),
        }

    def test_upload_to_foreign_card_is_404(self, partner_world, docs):
        response = self._post(partner_world["client_a"], partner_world["cards"]["shared"])
        assert response.status_code == 404
        assert TechDocument.objects.filter(title="Сертификат партнёра").count() == 0

    @pytest.mark.parametrize("bad", ["abc", "1", "not-a-uuid", "0" * 40])
    def test_non_uuid_upload_id_is_422_not_500(self, partner_world, docs, bad):
        card = partner_world["cards"]["published"]
        response = partner_world["client_a"].post(url(card), {"upload_id": bad, "title": "X"}, format="json")
        assert response.status_code == 422, response.content
        assert response.json()["detail"] == "UPLOAD_NOT_FOUND"

    def test_foreign_upload_is_not_found(self, partner_world, docs):
        other = PortalUpload(company=partner_world["b"], name="b.pdf", size_bytes=len(PDF))
        other.file.save("b.pdf", ContentFile(PDF), save=True)
        card = partner_world["cards"]["published"]
        response = partner_world["client_a"].post(
            url(card), {"upload_id": str(other.upload_id), "title": "X"}, format="json"
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "UPLOAD_NOT_FOUND"

    def test_upload_file_is_copied_not_shared(self, partner_world, docs):
        up = PortalUpload(company=partner_world["a"], name="a.pdf", size_bytes=len(PDF))
        up.file.save("a.pdf", ContentFile(PDF), save=True)
        card = partner_world["cards"]["published"]
        response = partner_world["client_a"].post(
            url(card), {"upload_id": str(up.upload_id), "title": "Копия"}, format="json"
        )
        assert response.status_code == 201, response.content
        doc = TechDocument.objects.get(pk=response.json()["id"])
        assert doc.file.name != up.file.name
        storage = up.file.storage
        assert storage.exists(up.file.name) and storage.exists(doc.file.name)
        assert doc.source_supplier_id == partner_world["a"].pk
        # удаление документа не уносит файл загрузки
        assert partner_world["client_a"].delete(url(card, doc.pk)).status_code == 204
        assert storage.exists(up.file.name)


class TestDelete:
    def test_cannot_delete_staff_document_on_own_card(self, partner_world, docs):
        client, card = partner_world["client_a"], partner_world["cards"]["published"]
        for key in ("own_public", "own_internal"):
            assert client.delete(url(card, docs[key].pk)).status_code == 404
            assert TechDocument.objects.filter(pk=docs[key].pk).exists()
        assert not ActivityLog.objects.filter(event_code="catalog.partner_document_deleted").exists()

    def test_cannot_delete_other_partner_document(self, partner_world, docs):
        card = partner_world["cards"]["published"]
        file = SimpleUploadedFile("cert.pdf", PDF, content_type="application/pdf")
        created = partner_world["client_a"].post(url(card), {"file": file, "title": "Док А"}, format="multipart")
        doc_id = created.json()["id"]
        # Б не владеет карточкой и не может удалить
        assert partner_world["client_b"].delete(url(card, doc_id)).status_code == 404
        assert TechDocument.objects.filter(pk=doc_id).exists()

    def test_delete_own_upload_is_journaled(self, partner_world, docs):
        client, card = partner_world["client_a"], partner_world["cards"]["published"]
        file = SimpleUploadedFile("cert.pdf", PDF, content_type="application/pdf")
        doc_id = client.post(url(card), {"file": file, "title": "Док А"}, format="multipart").json()["id"]
        assert client.delete(url(card, doc_id)).status_code == 204
        assert not TechDocument.objects.filter(pk=doc_id).exists()
        entry = ActivityLog.objects.get(event_code="catalog.partner_document_deleted")
        assert entry.entity_id == doc_id
        assert entry.contact_id == partner_world["a_contact"].pk
        assert entry.event_params["product_id"] == card.pk
