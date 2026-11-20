"""СЦ-10: файлы заявки клиента видны в карточке сделки и в листе расчёта и скачиваются под своим именем.

Прогон сценариев: клиент приложил spec.pdf к заявке в кабинете, а ни директор, ни снабженец его не видели. Файл заявки —
исходник на сделке (`Attachment.kind=SOURCE`); подтверждения доставки и прочее (`SUPPORTING`) сюда не попадают.
"""

import pytest
from django.core.files.base import ContentFile

from accounts.models import Company, CompanyType
from crm.models import Deal, DealStage
from crm.services.draft_quote import deal_request_files
from crm.tests.test_calc import _api, _sheet, _staff, world  # noqa: F401 — фикстура мира расчёта
from sourcing.models import Attachment, AttachmentKind

pytestmark = pytest.mark.django_db


def attach(deal, name, content=b"%PDF-1.4 spec", kind=AttachmentKind.SOURCE):
    attachment = Attachment(deal=deal, kind=kind, original_filename=name)
    attachment.file.save(name, ContentFile(content), save=True)
    return attachment


def deal_url(deal, suffix=""):
    return f"/api/v1/crm/deals/{deal.pk}/{suffix}"


def test_request_files_are_the_sources_of_the_request_only(world):
    deal = world["deal"]
    spec = attach(deal, "spec.pdf")
    attach(deal, "delivery.pdf", kind=AttachmentKind.SUPPORTING)

    assert [f["name"] for f in deal_request_files(deal)] == ["spec.pdf"]
    card = _api(world["supply"]).get(deal_url(deal))
    assert card.status_code == 200, card.content
    assert [(f["id"], f["name"]) for f in card.json()["request_files"]] == [(spec.pk, "spec.pdf")]


def test_calc_sheet_lists_the_request_files(world):
    spec = attach(world["deal"], "spec.pdf")

    sheet = _sheet(world, world["supply"])

    assert [(f["id"], f["name"]) for f in sheet["request"]["files"]] == [(spec.pk, "spec.pdf")]


def test_calc_sheet_without_files_has_an_empty_list(world):
    assert _sheet(world, world["supply"])["request"]["files"] == []


@pytest.mark.parametrize(("name", "expected"), [("spec.pdf", "spec.pdf"), ("заявка.pdf", "utf-8''%D0%B7%D0%B0")])
def test_download_by_the_original_name(world, name, expected):
    spec = attach(world["deal"], name)

    response = _api(world["supply"]).get(deal_url(world["deal"], f"request-files/{spec.pk}/"))

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"%PDF-1.4 spec"
    assert response["Content-Type"] == "application/octet-stream"
    assert response["Content-Disposition"].startswith("attachment") and expected in response["Content-Disposition"]


def test_other_files_of_the_deal_and_other_deals_are_not_served(world):
    deal = world["deal"]
    supporting = attach(deal, "delivery.pdf", kind=AttachmentKind.SUPPORTING)
    other_company = Company.objects.create(name="ООО Другой Клиент", inn="6600000299")
    other_company.types.add(CompanyType.objects.get(code="CLIENT"))
    other = Deal.objects.create(title="Другая", company=other_company, stage=DealStage.objects.get(code="RFQ_OPEN"))
    foreign = attach(other, "foreign.pdf")
    api = _api(world["supply"])

    assert api.get(deal_url(deal, f"request-files/{supporting.pk}/")).status_code == 404
    assert api.get(deal_url(deal, f"request-files/{foreign.pk}/")).status_code == 404


def test_file_missing_in_the_storage_is_404(world):
    spec = attach(world["deal"], "spec.pdf")
    spec.file.storage.delete(spec.file.name)

    assert _api(world["supply"]).get(deal_url(world["deal"], f"request-files/{spec.pk}/")).status_code == 404


def test_member_of_another_company_and_anonymous_get_nothing(world):
    from rest_framework.test import APIClient

    spec = attach(world["deal"], "spec.pdf")
    stranger_company = Company.objects.create(name="ООО Посторонний", inn="6600000300")
    stranger = _staff(stranger_company, "stranger@other.test", [])
    url = deal_url(world["deal"], f"request-files/{spec.pk}/")

    assert _api(stranger).get(url).status_code in (403, 404)
    assert APIClient().get(url).status_code == 401
