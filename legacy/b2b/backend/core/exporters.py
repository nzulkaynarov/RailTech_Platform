"""
Generic CSV / XLSX export helpers used by admin list views.

Usage in a ViewSet:

    @action(detail=False, methods=['get'], url_path='export')
    def export(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return export_queryset(
            qs,
            request=request,
            filename='companies',
            columns=[
                ('id', 'ID', lambda c: c.id),
                ('name', 'Name', lambda c: c.name),
                ...
            ],
        )
"""

from __future__ import annotations

import csv
import io
from typing import Callable, Iterable, Sequence

from django.http import HttpResponse

ColumnSpec = tuple[str, str, Callable[[object], object]]
# (key, header_label, getter) — getter receives the row object, returns the cell value


def _normalize_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    text = str(value)
    # CSV/formula injection (audit H5): a cell starting with = + - @ (or tab/CR) runs as a
    # formula when the admin opens the export in Excel/Sheets (HYPERLINK exfil, DDE exec).
    # Prefix a single quote to neutralize — user-controlled fields flow through here.
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        text = "'" + text
    return text


def export_queryset_csv(
    queryset: Iterable,
    *,
    filename: str,
    columns: Sequence[ColumnSpec],
) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    response.write("﻿")  # BOM — Excel opens UTF-8 correctly
    writer = csv.writer(response, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([label for _, label, _ in columns])
    for row in queryset:
        writer.writerow([_normalize_value(getter(row)) for _, _, getter in columns])
    return response


def export_queryset_xlsx(
    queryset: Iterable,
    *,
    filename: str,
    columns: Sequence[ColumnSpec],
) -> HttpResponse:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        return export_queryset_csv(queryset, filename=filename, columns=columns)

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Export")
    header_font = Font(bold=True)
    header_row = []
    from openpyxl.cell import WriteOnlyCell

    for _, label, _ in columns:
        cell = WriteOnlyCell(ws, value=label)
        cell.font = header_font
        header_row.append(cell)
    ws.append(header_row)

    for row in queryset:
        ws.append([_normalize_value(getter(row)) for _, _, getter in columns])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response


def export_queryset(
    queryset: Iterable,
    *,
    request,
    filename: str,
    columns: Sequence[ColumnSpec],
) -> HttpResponse:
    """Dispatch on ?fmt=csv|xlsx (default: xlsx).

    Uses `fmt` instead of `format` because DRF reserves `format` for content
    negotiation (format suffixes/renderers).
    """
    fmt = (request.query_params.get("fmt") or "xlsx").lower()
    if fmt == "csv":
        return export_queryset_csv(queryset, filename=filename, columns=columns)
    return export_queryset_xlsx(queryset, filename=filename, columns=columns)
