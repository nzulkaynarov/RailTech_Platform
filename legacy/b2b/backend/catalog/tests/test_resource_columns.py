"""M9/M10 — MPN (the brand+MPN dedup key) and hs_code must round-trip through both
the django-import-export ProductResource and the XLSX import template, under the
same column names. Without them an export→import cycle drops the dedup key + the
customs code.
"""

import pytest
from rest_framework.test import APIClient

from catalog.resources import ProductResource


def test_product_resource_exports_mpn_and_hs_code():
    field_names = set(ProductResource().fields.keys())
    assert "manufacturer_part_number" in field_names
    assert "hs_code" in field_names


@pytest.mark.django_db
def test_export_template_has_mpn_and_hs_code_columns(user_factory):
    import openpyxl
    from io import BytesIO

    client = APIClient()
    client.force_authenticate(user=user_factory(email="tpl@example.com", username="tpl"))

    response = client.get("/api/v1/catalog/products/export-template/", SERVER_NAME="localhost")
    assert response.status_code == 200

    workbook = openpyxl.load_workbook(BytesIO(response.content))
    sheet = workbook.active
    header_row = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    assert "manufacturer_part_number" in header_row
    assert "hs_code" in header_row
