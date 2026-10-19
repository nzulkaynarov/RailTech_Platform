"""Лимиты контракта 0.2.0 в коде и на границах (FIX-21): summary ≤ 5000, Reason ≤ 2000, загрузка ≤ 10 МБ."""

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from portal.serializers import REASON_MAX_LENGTH, SUMMARY_MAX_LENGTH
from portal.tests.contract_support import component
from rest_framework import status

from crm.models import Act, Deal, Quote

pytestmark = pytest.mark.django_db

REQUESTS = "/api/portal/v1/requests"
UPLOADS = "/api/portal/v1/uploads"
MB = 1024 * 1024


def test_limits_equal_the_contract():
    schemas = {
        "summary": component("ClientRequestCreate")["properties"]["summary"]["maxLength"],
        "reason": component("Reason")["properties"]["reason"]["maxLength"],
    }
    assert (SUMMARY_MAX_LENGTH, REASON_MAX_LENGTH) == (schemas["summary"], schemas["reason"]) == (5000, 2000)
    assert settings.PORTAL_UPLOAD_MAX_BYTES == 10 * MB


class TestSummaryLimit:
    def test_5000_characters_are_accepted(self, portal_client):
        resp = portal_client.post(REQUESTS, {"summary": "я" * 5000, "lines": []}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert len(resp.json()["summary"]) == 5000
        # текст не обрезан ни в карточке, ни в списке; название сделки для сотрудников — одна короткая строка
        request_id = resp.json()["id"]
        assert portal_client.get(f"{REQUESTS}/{request_id}").json()["summary"] == "я" * 5000
        assert [r["summary"] for r in portal_client.get(REQUESTS).json() if r["id"] == request_id] == ["я" * 5000]
        assert len(Deal.objects.get(pk=request_id).title) <= 255

    def test_multiline_summary_is_kept_as_written(self, portal_client):
        text = "Нужны трубы\n\nГОСТ 8732,   150 м"
        resp = portal_client.post(REQUESTS, {"summary": text, "lines": []}, format="json")
        assert resp.json()["summary"] == text
        assert Deal.objects.get(pk=resp.json()["id"]).title == "Нужны трубы ГОСТ 8732, 150 м"

    def test_5001_characters_are_rejected(self, portal_client):
        resp = portal_client.post(REQUESTS, {"summary": "я" * 5001, "lines": []}, format="json")
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert resp.json() == {"detail": "VALIDATION_ERROR"}

    def test_read_only_contact_cannot_create_a_request(self, readonly_portal_client):
        resp = readonly_portal_client.post(REQUESTS, {"summary": "x", "lines": []}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.json() == {"detail": "FORBIDDEN"}


class TestReasonLimit:
    @pytest.fixture
    def targets(self, contract_world):
        return {
            "quote": f"/api/portal/v1/quotes/{contract_world['quotes']['sent'].pk}/reject",
            "act": f"/api/portal/v1/acts/{contract_world['acts']['issued'].pk}/return",
        }

    @pytest.mark.parametrize("target", ["quote", "act"])
    def test_2000_characters_are_accepted(self, portal_client, targets, target):
        resp = portal_client.post(targets[target], {"reason": "я" * 2000}, format="json")
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.parametrize("target", ["quote", "act"])
    def test_2001_characters_are_rejected(self, portal_client, targets, target):
        resp = portal_client.post(targets[target], {"reason": "я" * 2001}, format="json")
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert resp.json() == {"detail": "VALIDATION_ERROR"}

    @pytest.mark.parametrize("target", ["quote", "act"])
    @pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "   "}])
    def test_empty_reason_is_reason_required(self, portal_client, targets, target, body):
        resp = portal_client.post(targets[target], body, format="json")
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert resp.json() == {"detail": "REASON_REQUIRED"}

    @pytest.mark.parametrize("target", ["quote", "act"])
    def test_read_only_contact_gets_403_and_nothing_changes(
        self, readonly_portal_client, contract_world, targets, target
    ):
        resp = readonly_portal_client.post(targets[target], {"reason": "x"}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.json() == {"detail": "FORBIDDEN"}
        assert Quote.objects.get(pk=contract_world["quotes"]["sent"].pk).status.code == "SENT"
        assert Act.objects.get(pk=contract_world["acts"]["issued"].pk).rejection_reason == ""

    @pytest.mark.parametrize("target", ["quote", "act"])
    def test_other_company_is_404(self, other_portal_client, targets, target):
        resp = other_portal_client.post(targets[target], {"reason": "x"}, format="json")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.json() == {"detail": "NOT_FOUND"}


class TestUploadLimit:
    def upload(self, client, size):
        return client.post(
            UPLOADS, {"file": SimpleUploadedFile("scan.pdf", b"0" * size, "application/pdf")}, format="multipart"
        )

    def test_exactly_10_mb_is_accepted(self, portal_client):
        resp = self.upload(portal_client, 10 * MB)
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["size_bytes"] == 10 * MB

    def test_one_byte_over_is_rejected(self, portal_client):
        resp = self.upload(portal_client, 10 * MB + 1)
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert resp.json() == {"detail": "FILE_TOO_LARGE"}

    def test_limit_is_a_setting(self, portal_client, settings):
        settings.PORTAL_UPLOAD_MAX_BYTES = 100
        assert self.upload(portal_client, 100).status_code == status.HTTP_201_CREATED
        assert self.upload(portal_client, 101).json() == {"detail": "FILE_TOO_LARGE"}

    def test_missing_file_is_file_required_400(self, portal_client):
        resp = portal_client.post(UPLOADS, {}, format="multipart")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json() == {"detail": "FILE_REQUIRED"}

    def test_read_only_contact_cannot_upload(self, readonly_portal_client):
        assert self.upload(readonly_portal_client, 10).status_code == status.HTTP_403_FORBIDDEN
