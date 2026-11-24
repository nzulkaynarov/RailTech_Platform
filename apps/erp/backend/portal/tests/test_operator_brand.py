"""ДВ-3: логотип оператора до входа — публичный адрес логотипа своей компании в `GET /operator`."""

from __future__ import annotations

import pytest
from django.core.files.base import ContentFile
from parties.models import Company
from rest_framework.test import APIClient

OPERATOR = "/api/portal/v1/operator"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.django_db
def test_operator_without_own_company_has_no_logo(settings):
    settings.OWN_COMPANY_ID = None
    body = APIClient().get(OPERATOR).json()
    assert body["logo_url"] is None


@pytest.mark.django_db
def test_operator_logo_is_a_versioned_api_path_not_a_media_path(settings):
    company = Company.objects.create(name="ООО Оператор", inn="301000111")
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (30, 30), (1, 2, 3)).save(out, format="PNG")
    company.logo.save("logo.png", ContentFile(out.getvalue()), save=True)
    settings.OWN_COMPANY_ID = company.pk

    body = APIClient().get(OPERATOR).json()

    assert body["logo_url"].startswith("/api/portal/v1/operator/logo?v=")
    assert "/media/" not in body["logo_url"]
    assert APIClient().get("/api/portal/v1/operator/logo").status_code == 200
