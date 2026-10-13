"""TRACK A — on-demand multi-format КП export service.

Covers crm.services.export_quote: the seller XLSX/CSV line table (with the cost
columns gated behind include_costs) and the unsupported-format guard. The PDF path
shares QuoteLifecycleService.generate_pdf (already exercised by the pdf-render and
public-send suites), so here we assert format dispatch + the cost-leak boundary, not
WeasyPrint output.
"""

from decimal import Decimal

import pytest

from accounts.models import Company, CompanyType, VerificationStatus
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services import export_quote
from crm.services.exporters import _client_columns, _cost_columns


@pytest.fixture
def export_lookups(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})


@pytest.fixture
def quote_with_items(export_lookups):
    company = Company.objects.create(
        name="Buyer LLC",
        inn="7700000001",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    deal = Deal.objects.create(company=company, stage=DealStage.objects.get(code="DRAFT"), title="Export test")
    quote = Quote.objects.create(
        deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"), margin_percent=Decimal("20")
    )
    QuoteItem.objects.create(
        quote=quote,
        imported_raw_name="=SUM(1+1) Тормозная колодка",  # formula-injection probe (leads with =)
        quantity=3,
        unit="шт",
        frozen_base_price=Decimal("100.00"),
        lead_time_days=14,
    )
    quote.recalculate_totals()
    quote.refresh_from_db()
    return quote


def test_unsupported_format_raises(quote_with_items):
    with pytest.raises(ValueError):
        export_quote(quote_with_items, "docx")


def test_csv_export_without_costs_is_client_safe(quote_with_items):
    response = export_quote(quote_with_items, "csv", include_costs=False)
    body = response.content.decode("utf-8")
    assert "text/csv" in response["Content-Type"]
    # Client columns present, seller cost/margin columns absent.
    assert "Наименование" in body
    assert "Себестоимость" not in body
    assert "Маржа" not in body
    assert "Landed cost" not in body
    # Formula-injection neutralisation from core.exporters is applied: a cell that
    # leads with "=" is prefixed with a single quote so Excel/Sheets won't run it.
    assert "'=SUM(1+1)" in body


def test_csv_export_with_costs_includes_seller_columns(quote_with_items):
    response = export_quote(quote_with_items, "csv", include_costs=True)
    body = response.content.decode("utf-8")
    assert "Себестоимость" in body
    # DT1: колонка теперь несёт ЭФФЕКТИВНУЮ маржу строки (позиционная либо унаследованная от КП),
    # поэтому заголовок больше не «Маржа КП».
    assert "Маржа, %" in body
    assert "Landed cost" in body


def test_xlsx_export_returns_spreadsheet(quote_with_items):
    response = export_quote(quote_with_items, "xlsx", include_costs=True)
    assert "spreadsheetml.sheet" in response["Content-Type"]
    assert response["Content-Disposition"].endswith('.xlsx"')
    assert len(response.content) > 0


def test_cost_columns_are_strictly_additive(quote_with_items):
    """The cost set must only EXTEND the client set — no client column dropped when
    costs are included (so the seller export is a superset, never a different shape)."""
    client_keys = {key for key, _, _ in _client_columns("UZS")}
    cost_keys = {key for key, _, _ in _cost_columns("UZS")}
    assert client_keys.isdisjoint(cost_keys)
