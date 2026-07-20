"""КП (Quote) export service — render ONE quote to PDF / XLSX / CSV on demand.

World rule (owner directive): export is a USER-CHOSEN format, generated ON DEMAND —
there is no forced/auto single PDF. The view stays thin (Rule 8) and dispatches here.

Two projections, gated by the requester:
  - PDF → the CLIENT projection (crm/quote_pdf.html). NEVER exposes seller cost /
    margin / landed cost / charges — same rule the public link and email use.
  - XLSX / CSV → the SELLER line table. Includes the cost/margin columns ONLY when
    the requester passes `include_costs` (the caller gates this on
    can_view_quote_costs_for). Without it the spreadsheet collapses to the same
    client-safe columns as the PDF, so a buyer self-exporting can't derive markup.

Spreadsheet rendering reuses core.exporters (export_queryset_xlsx / _csv) so the
formula-injection neutralisation (_normalize_value) is applied to every user-controlled
cell — a КП line name like `=HYPERLINK(...)` can't run when opened in Excel/Sheets.
"""

from __future__ import annotations

from decimal import Decimal

from django.http import HttpResponse

from core.exporters import export_queryset_csv, export_queryset_xlsx

from ..models import Quote

# Formats this service can render. Anything else → ValueError("UNSUPPORTED_FORMAT").
EXPORT_FORMATS = ("pdf", "xlsx", "csv")


def _money(value) -> str:
    """Two-decimal plain string for a money cell (Decimal discipline, no float)."""
    if value is None:
        return ""
    return str(Decimal(value).quantize(Decimal("0.01")))


def _pres_currency(quote: Quote) -> str:
    """Presentation currency code of the КП (what the client sees). UZS by default."""
    return quote.quote_currency.code if quote.quote_currency_id else "UZS"


def _line_name(item) -> str:
    return item.product.name if item.product_id and item.product else (item.imported_raw_name or "")


def _is_priced(item) -> bool:
    """A row that actually carries a price (an ITEM — whether billable or optional). SECTION/NOTE
    are presentation rows and their (zeroed) price/cost cells must render blank, never «0.00»."""
    from ..models import QuoteItem

    return item.display_type == QuoteItem.DisplayType.ITEM


def _priced_money(row, attr) -> str:
    """Money cell for a line-level amount — blank on SECTION/NOTE (they have no price)."""
    return _money(getattr(row["item"], attr)) if _is_priced(row["item"]) else ""


def _client_columns(pres_ccy: str):
    """The buyer-safe column set — mirrors the PDF table. No cost / margin / landed."""
    return [
        # № numbers ONLY billable ITEM rows; SECTION/NOTE render as separators (no №) and optional
        # ITEMs are marked «опц.» — never a plain payable position number (see _spreadsheet_rows).
        ("pos", "№", lambda row: row["pos"]),
        ("row_type", "Тип", lambda row: row["type_label"]),
        ("name", "Наименование", lambda row: _line_name(row["item"])),
        ("mpn", "Артикул", lambda row: row["item"].mpn or ""),
        ("quantity", "Кол-во", lambda row: row["item"].quantity if _is_priced(row["item"]) else ""),
        ("unit", "Ед. изм.", lambda row: row["item"].unit or ""),
        (
            "lead_time",
            "Срок, дн.",
            lambda row: (row["item"].lead_time_days or "") if _is_priced(row["item"]) else "",
        ),
        (
            "unit_price",
            f"Цена за ед., без НДС ({pres_ccy})",
            lambda row: _priced_money(row, "final_price_excl_vat"),
        ),
        (
            "line_total",
            f"Сумма, без НДС ({pres_ccy})",
            lambda row: _priced_money(row, "line_total"),
        ),
    ]


def _cost_columns(pres_ccy: str):
    """The seller cost/margin columns — APPENDED to the client set when include_costs.

    base_price is shown in the line's OWN cost currency (frozen_currency); the
    derived landed/final/total are in the КП presentation currency (UZS).
    """
    return [
        (
            "base_price",
            "Себестоимость (база)",
            lambda row: _priced_money(row, "frozen_base_price"),
        ),
        (
            "base_ccy",
            "Валюта себест.",
            lambda row: (
                (row["item"].frozen_currency.code if row["item"].frozen_currency_id else "UZS")
                if _is_priced(row["item"])
                else ""
            ),
        ),
        ("customs_duty", "Пошлина", lambda row: _priced_money(row, "customs_duty")),
        (
            "landed_cost",
            f"Landed cost ({pres_ccy})",
            lambda row: _priced_money(row, "landed_cost"),
        ),
        # Margin is a КП-level %, meaningful only against a priced line — blank on section/note.
        (
            "margin_percent",
            "Маржа КП, %",
            lambda row: _money(row["quote"].margin_percent) if _is_priced(row["item"]) else "",
        ),
        ("discount_percent", "Скидка, %", lambda row: _priced_money(row, "discount_percent")),
    ]


def _spreadsheet_rows(quote: Quote):
    """Pre-fetched line rows in `position` order, wrapped with a back-reference to the КП (for the
    margin getter) plus a display-type-aware № and «Тип» label so the seller sheet never presents a
    SECTION/NOTE or an optional line as a plain numbered payable position (review MAJOR):

      • billable ITEM (non-optional) → sequential № (1,2,3…), type «Позиция»
      • optional ITEM               → no № («опц.» marker), type «Опционально» — priced but off-total
      • SECTION                     → no №, type «Раздел» (a grouping separator)
      • NOTE                        → no №, type «Заметка»
    """
    from ..models import QuoteItem

    items = quote.items.select_related("product", "frozen_currency").all()
    rows = []
    pos = 0
    for item in items:
        if item.display_type == QuoteItem.DisplayType.SECTION:
            pos_label, type_label = "", "Раздел"
        elif item.display_type == QuoteItem.DisplayType.NOTE:
            pos_label, type_label = "", "Заметка"
        elif item.is_optional:
            pos_label, type_label = "опц.", "Опционально"
        else:
            pos += 1
            pos_label, type_label = pos, "Позиция"
        rows.append({"pos": pos_label, "type_label": type_label, "item": item, "quote": quote})
    return rows


def _export_spreadsheet(quote: Quote, fmt: str, *, include_costs: bool) -> HttpResponse:
    """Render the seller line table to XLSX or CSV via the shared core helpers."""
    pres_ccy = _pres_currency(quote)
    columns = _client_columns(pres_ccy)
    if include_costs:
        columns = columns + _cost_columns(pres_ccy)
    rows = _spreadsheet_rows(quote)
    filename = f"KP_{quote.deal_id}_v{quote.version}"
    if fmt == "csv":
        return export_queryset_csv(rows, filename=filename, columns=columns)
    return export_queryset_xlsx(rows, filename=filename, columns=columns)


def _export_pdf(quote: Quote) -> HttpResponse:
    """Render the CLIENT projection PDF (no cost/margin leak) and stream it inline.

    Reuses QuoteLifecycleService.generate_pdf — the single rendering path that writes
    quote_pdf.html through WeasyPrint and persists pdf_file — so the on-demand export
    and the emailed/public КП are byte-for-byte the same document.
    """
    from django.http import FileResponse

    from .quotes import QuoteLifecycleService

    quote = QuoteLifecycleService.generate_pdf(quote.pk)
    return FileResponse(
        quote.pdf_file.open("rb"),
        content_type="application/pdf",
        as_attachment=True,
        filename=quote.pdf_file.name.split("/")[-1],
    )


def export_quote(quote: Quote, fmt: str, *, include_costs: bool = False) -> HttpResponse:
    """Render `quote` to `fmt` (pdf | xlsx | csv) and return a download HttpResponse.

    `include_costs` ONLY affects the spreadsheet projections and MUST already be
    authorised by the caller (can_view_quote_costs_for). The PDF is always the
    client projection regardless. Raises ValueError("UNSUPPORTED_FORMAT") on a bad
    format so the view can map it to 400.
    """
    fmt = (fmt or "pdf").lower()
    if fmt not in EXPORT_FORMATS:
        raise ValueError("UNSUPPORTED_FORMAT")
    if fmt == "pdf":
        # The PDF is the CLIENT document → _export_pdf/generate_pdf hard-gate fx_missing +
        # below_cost + not_claimed (HOLE 2). XLSX/CSV is the seller's INTERNAL cost/margin sheet
        # (it carries cost columns) — never a client КП — so it must export even on a fx-missing /
        # below-cost DRAFT the seller is still working (the prior unconditional fx_missing block
        # here wrongly froze the internal sheet too).
        return _export_pdf(quote)
    return _export_spreadsheet(quote, fmt, include_costs=include_costs)
