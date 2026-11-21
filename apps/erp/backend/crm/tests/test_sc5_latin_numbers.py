"""СЦ-5 — Latin numbers in ERP: label validation, samples from the scheme, sequential articles with `previous_sku`,
the `renumber_latin` command (dry-run, --apply, idempotency) and the PDF without a pseudo number."""

import importlib
import io
import json

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.template.loader import render_to_string
from documents.models import DocumentSequence
from sales.models import CalcTask

from accounts.models import Company
from catalog.models import DomainType, Product, ProductStatus
from crm.models import Deal, DocumentNumberingScheme
from crm.services import latin_renumber
from crm.services.numbering import sample_numbers, set_company_scheme
from crm.tests.test_numbering_scheme_view import URL, _client, _owner, _seller_company

pytestmark = pytest.mark.django_db

CYRILLIC = {chr(code) for code in range(0x0400, 0x0530)}


def _has_cyrillic(text: str) -> bool:
    return any(char in CYRILLIC for char in text)


# ── label validation ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("label", ["КП", "qt", "Q T", "QT-1", "", "A" * 17, "ÄÖ"])
def test_set_company_scheme_rejects_non_latin_label(label):
    company = _seller_company("Lbl", "6300000001")
    with pytest.raises(ValidationError) as caught:
        set_company_scheme(company, type_labels={"KP": label})
    assert "type_labels" in caught.value.message_dict


def test_set_company_scheme_accepts_latin_label():
    company = _seller_company("Lbl2", "6300000002")
    set_company_scheme(company, type_labels={"KP": "RFQ2"})
    assert DocumentNumberingScheme.objects.get(company__isnull=True).type_labels["KP"] == "RFQ2"


def test_patch_with_cyrillic_label_is_400_with_field_error_and_preview_too():
    company = _seller_company("Lbl3", "6300000003")
    client = _client(_owner(company, "owner@lbl3.test"))
    resp = client.patch(URL, {"type_labels": {"KP": "КП"}}, format="json")
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"] == "INVALID_NUMBERING_LABEL" and body["type_labels"]
    assert not DocumentNumberingScheme.objects.exists()
    draft = {"pattern": "{type}-{YYYY}/{seq}", "padding": 3, "reset_period": "yearly", "start_value": 0}
    preview = client.post(URL + "preview/", {**draft, "type_labels": {"KP": "КП"}}, format="json")
    assert preview.status_code == 400 and preview.json()["detail"] == "INVALID_NUMBERING_LABEL"


# ── samples come from the scheme ────────────────────────────────────────────────────


def test_sample_numbers_follow_the_scheme_and_are_latin():
    default = sample_numbers(None)
    assert default["KP"].startswith("QT-") and default["CT"].startswith("CT-")
    assert not any(_has_cyrillic(value) for value in default.values())
    company = _seller_company("Smp", "6300000004")
    set_company_scheme(company, type_labels={"CT": "AGR", "KP": "RFQ"})
    custom = sample_numbers(company)
    assert custom["CT"].startswith("AGR-") and custom["KP"].startswith("RFQ-")


def test_document_previews_use_scheme_numbers_not_literals():
    from crm.services.documents.preview import render_document_profile_preview_html

    company = _seller_company("Prv", "6300000005")
    set_company_scheme(company, type_labels={"CT": "AGR", "INV": "BILL", "ACT": "ACC", "DOC": "PAPER"})
    for doc_type, expected in (("CT", "AGR-"), ("INV", "BILL-"), ("ACT", "ACC-"), ("DOC", "PAPER-")):
        html = render_document_profile_preview_html(company, doc_type)
        assert expected in html, doc_type
        for literal in ("ДОГ-2026", "СЧ-2026", "АКТ-2026", "ДОК-2026", "КП-2026"):
            assert literal not in html, (doc_type, literal)


def test_quote_pdf_without_number_has_no_pseudo_number():
    from types import SimpleNamespace

    html = render_to_string(
        "crm/quote_pdf.html",
        {
            "quote": SimpleNamespace(number="", deal_id=77, version=3),
            "document_draft": False,
            "items": [],
            "company": None,
        },
    )
    assert "77-3" not in html


# ── sequential articles ─────────────────────────────────────────────────────────────


@pytest.fixture
def goods():
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    return DomainType.objects.update_or_create(code="GENERAL_GOODS", defaults={"name": "Goods", "sku_prefix": "GD"})[0]


def test_new_sku_is_sequential_without_random_part(goods):
    first = Product.objects.create(name="Alpha", domain_type=goods)
    second = Product.objects.create(name="Beta", domain_type=goods)
    assert (first.sku, second.sku) == ("GD-00001", "GD-00002")


def test_sku_counter_skips_taken_articles(goods):
    Product.objects.create(name="Imported", domain_type=goods, sku="GD-00001")
    assert Product.objects.create(name="Next", domain_type=goods).sku == "GD-00002"


def test_catalog_search_finds_a_card_by_previous_sku(goods):
    from catalog.desk.items import list_queryset

    product = Product.objects.create(name="Gamma", domain_type=goods)
    Product.objects.filter(pk=product.pk).update(previous_sku="ТВ-1A2B3C4D")
    assert [p.pk for p in list_queryset({"q": "ТВ-1A2B3C4D"})] == [product.pk]
    assert list_queryset({"q": "ТВ-FFFFFFFF"}).count() == 0


def test_domain_type_prefix_migration_changes_only_untouched_seed_prefixes():
    migration = importlib.import_module("catalog.migrations.0019_product_previous_sku")
    from django.apps import apps

    DomainType.objects.update_or_create(code="GENERAL_GOODS", defaults={"name": "Goods", "sku_prefix": "ТВ"})
    DomainType.objects.update_or_create(code="SERVICES", defaults={"name": "Services", "sku_prefix": "MYSV"})
    migration.latin_prefixes(apps, None)
    assert DomainType.objects.get(code="GENERAL_GOODS").sku_prefix == "GD"
    assert DomainType.objects.get(code="SERVICES").sku_prefix == "MYSV"  # edited by the owner: kept
    migration.cyrillic_prefixes(apps, None)
    assert DomainType.objects.get(code="GENERAL_GOODS").sku_prefix == "ТВ"


# ── renumber_latin ──────────────────────────────────────────────────────────────────


def _deal_with_old_number(title: str, old: str, *, project: bool = False) -> Deal:
    deal = Deal.objects.create(title=title)
    Deal.objects.filter(pk=deal.pk).update(number=old, is_project=project)
    deal.refresh_from_db()
    return deal


def _run(mapping: dict, tmp_path, *args) -> str:
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    out = io.StringIO()
    call_command("renumber_latin", str(path), *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def old_data(goods):
    request = _deal_with_old_number("Req", "ЗВ-2026-001")
    project = _deal_with_old_number("Prj", "ЗВ-2026-002", project=True)
    product = Product.objects.create(name="Legacy", domain_type=goods)
    Product.objects.filter(pk=product.pk).update(sku="ТВ-1A2B3C4D")
    DocumentSequence.objects.filter(doc_type="SKU-GD").delete()  # prod has no counter yet: the old article was random
    company = Company.objects.create(name="Buyer", inn="6300000099")
    CalcTask.objects.create(
        deal=request,
        eds_letter_id="11111111-1111-1111-1111-111111111111",
        letter_number="ВХ-001/26",
        resolution_text="r",
        due="2026-12-01",
        decided_at="2026-11-01T10:00:00Z",
    )
    from parties.models import Contact
    from portal.models import PortalNotice

    contact = Contact.objects.create(company=company, name="C")
    notice = PortalNotice.objects.create(
        company=company,
        contact=contact,
        kind="k",
        group="g",
        object_type="deal",
        object_id=request.pk,
        object_number="ЗВ-2026-001",
        action="a",
        text_key="t",
        params={"number": "ЗВ-2026-001", "deal": "ЗВ-2026-001", "keep": "other", "nested": ["ЗВ-2026-001"]},
        link="/x",
        dedup_key="d1",
    )
    return {"request": request, "project": project, "product": product, "notice": notice}


def test_emit_mapping_lists_own_numbers_only(old_data):
    mapping = latin_renumber.emit_mapping()
    assert mapping == {
        "ЗВ-2026-001": "RQ-2026-001",
        "ПР-2026-001": "RQ-2026-001",
        "ЗВ-2026-002": "PRJ-2026-002",
        "ПР-2026-002": "PRJ-2026-002",
        "ТВ-1A2B3C4D": "GD-00001",
    }


def test_emit_mapping_covers_copies_of_an_already_renumbered_or_promoted_deal(old_data, tmp_path):
    """Prod: the project is PRJ-2026-002 already, EDS and portal copies still say ЗВ-2026-002."""
    from parties.models import Contact
    from portal.models import PortalNotice
    from supply.models import SupplierOrder, SupplierOrderLine

    Deal.objects.filter(pk=old_data["project"].pk).update(number="PRJ-2026-002")
    Deal.objects.filter(pk=old_data["request"].pk).update(number="RQ-2026-001")  # Latin: never renamed itself
    company = old_data["notice"].company
    notice = PortalNotice.objects.create(
        company=company,
        contact=Contact.objects.create(company=company, name="C2"),
        kind="k",
        group="g",
        object_type="deal",
        object_id=old_data["project"].pk,
        object_number="ЗВ-2026-002",
        action="a",
        text_key="t",
        params={"number": "ЗВ-2026-002"},
        link="/x",
        dedup_key="d2",
    )
    mapping = latin_renumber.emit_mapping()
    assert mapping["ЗВ-2026-002"] == "PRJ-2026-002" and mapping["ПР-2026-002"] == "PRJ-2026-002"
    assert "RQ-2026-001" not in mapping
    order = SupplierOrder.objects.create(number="PO-2026-001", number_year=2026, number_seq=1, supplier=company)
    line = SupplierOrderLine.objects.create(order=order, name="L", article="ТВ-1A2B3C4D", quantity=1)
    _run(mapping, tmp_path, "--apply")
    notice.refresh_from_db()
    assert notice.object_number == "PRJ-2026-002" and notice.params == {"number": "PRJ-2026-002"}
    line.refresh_from_db()
    assert line.article == "GD-00001"


def test_dry_run_prints_changes_and_writes_nothing(old_data, tmp_path):
    mapping = {**latin_renumber.emit_mapping(), "ВХ-001/26": "IN-001/26"}
    out = _run(mapping, tmp_path)
    assert "sales_deal.number" in out and "ЗВ-2026-001 → RQ-2026-001" in out
    assert "catalog_product.sku" in out and "sales_calctask.letter_number" in out
    assert "portal_portalnotice.object_number" in out and "portal_portalnotice.params" in out
    assert Deal.objects.get(pk=old_data["request"].pk).number == "ЗВ-2026-001"
    assert Product.objects.get(pk=old_data["product"].pk).sku == "ТВ-1A2B3C4D"


def test_apply_renumbers_everything_and_is_idempotent(old_data, tmp_path):
    mapping = {**latin_renumber.emit_mapping(), "ВХ-001/26": "IN-001/26"}
    _run(mapping, tmp_path, "--apply")
    assert Deal.objects.get(pk=old_data["request"].pk).number == "RQ-2026-001"
    assert Deal.objects.get(pk=old_data["project"].pk).number == "PRJ-2026-002"
    product = Product.objects.get(pk=old_data["product"].pk)
    assert (product.sku, product.previous_sku) == ("GD-00001", "ТВ-1A2B3C4D")
    assert CalcTask.objects.get().letter_number == "IN-001/26"
    notice = type(old_data["notice"]).objects.get()
    assert notice.object_number == "RQ-2026-001"
    assert notice.params == {"number": "RQ-2026-001", "deal": "RQ-2026-001", "keep": "other", "nested": ["RQ-2026-001"]}
    # the counter continues after the renumbered article
    assert DocumentSequence.objects.get(doc_type="SKU-GD").last_value == 1
    assert Product.objects.create(name="Fresh", domain_type=product.domain_type).sku == "GD-00002"
    again = _run(mapping, tmp_path, "--apply")
    assert "0 field(s) changed" in again
    assert Product.objects.get(pk=product.pk).previous_sku == "ТВ-1A2B3C4D"


def test_apply_is_one_transaction(old_data, tmp_path):
    """A taken target article aborts the whole run: the deal number is rolled back too."""
    Product.objects.create(name="Squatter", sku="GD-00005")
    mapping = {"ЗВ-2026-001": "RQ-2026-001", "ТВ-1A2B3C4D": "GD-00005"}
    with pytest.raises(Exception):
        _run(mapping, tmp_path, "--apply")
    assert Deal.objects.get(pk=old_data["request"].pk).number == "ЗВ-2026-001"


def test_stage_follows_is_project_not_the_number_prefix(old_data):
    from sales.services.deal_numbers import stage_of

    assert stage_of(old_data["request"]) == "request" and stage_of(old_data["project"]) == "project"
    Deal.objects.filter(pk=old_data["project"].pk).update(number="XX-2026-002")
    assert stage_of(Deal.objects.get(pk=old_data["project"].pk)) == "project"


def test_old_deal_number_is_still_found_by_year_and_seq(old_data):
    from sales.services.deal_numbers import parse_query

    assert parse_query("ЗВ-2026-001") == parse_query("RQ-2026-001") == (2026, 1)
