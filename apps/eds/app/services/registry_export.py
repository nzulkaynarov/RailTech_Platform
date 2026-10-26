"""Экспорт реестра в CSV и XLSX без внешних библиотек (eds.yaml `GET /registry/export`, до 10 000 строк).

CSV — UTF-8 с BOM (Excel открывает кириллицу), разделитель запятая. XLSX — минимальная книга OOXML с одним листом и
строками-значениями (`inlineStr`). Ячейки, начинающиеся с `=`, `+`, `-`, `@`, получают префикс `'` (защита от формул).
"""

import csv
import io
import zipfile
from xml.sax.saxutils import escape

from app.schemas.registry import RegistryItem

HEADERS = ("Тип", "Номер", "Тема", "Статус", "Зарегистрирован", "Ответственный", "Клиент", "Сделка ERP")
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_TYPE = "text/csv; charset=utf-8"
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe(value: str) -> str:
    return f"'{value}" if value.startswith(_FORMULA_START) else value


def _row(item: RegistryItem) -> list[str]:
    return [
        item.kind.value,
        item.number or "",
        item.title,
        item.status,
        item.registered_at.isoformat(timespec="seconds"),
        item.responsible.full_name if item.responsible else "",
        (item.client.name or "") if item.client else "",
        item.links.deal_number or "",
    ]


def to_csv(items: list[RegistryItem]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(HEADERS)
    for item in items:
        writer.writerow([_safe(cell) for cell in _row(item)])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")


def _xml_text(value: str) -> str:
    """Текст ячейки без символов, недопустимых в XML 1.0."""
    return escape("".join(ch for ch in value if ch in "\t\n\r" or ord(ch) >= 0x20))


def _cell(column: int, row: int, value: str) -> str:
    ref = f"{chr(ord('A') + column)}{row}"
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_xml_text(value)}</t></is></c>'


def to_xlsx(items: list[RegistryItem]) -> bytes:
    rows = [list(HEADERS), *([_safe(cell) for cell in _row(item)] for item in items)]
    sheet_rows = "".join(
        f'<row r="{n}">{"".join(_cell(c, n, v) for c, v in enumerate(values))}</row>'
        for n, values in enumerate(rows, 1)
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Реестр" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>'
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{sheet_rows}</sheetData></worksheet>'
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    return buffer.getvalue()
