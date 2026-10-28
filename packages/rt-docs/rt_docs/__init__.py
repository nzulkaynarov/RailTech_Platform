"""rt_docs — документы RailTech Platform: тело JSON → HTML → PDF (WeasyPrint), DOCX, «Подогнать», форматтеры ru/uz.

Описание и подключение — docs/architecture/rt-docs.md; решение — docs/adr/0020-documents-letterhead-body-rendering.md.
Рендер PDF — `rt_docs.pdf.render_pdf` и `rt_docs.fit.fit` (импорт требует pango и harfbuzz); остальное — без них.
"""

from .contracts import Catalog, contracts_dir, load_catalog, validate_body
from .docx_export import DocxResult, to_docx
from .errors import BodyError, ContractsNotFoundError, LetterheadError, RtDocsError
from .formatters import amount_in_words, currency_label, format_date, format_money, format_number, format_value
from .html_import import ImportResult, Loss, html_to_body
from .model import (
    Density,
    DocumentMeta,
    Layout,
    Letterhead,
    Logo,
    Money,
    Orientation,
    PageStats,
    RenderResult,
    Tuning,
)

__all__ = [
    "BodyError",
    "Catalog",
    "ContractsNotFoundError",
    "Density",
    "DocumentMeta",
    "DocxResult",
    "ImportResult",
    "Layout",
    "Letterhead",
    "LetterheadError",
    "Logo",
    "Loss",
    "Money",
    "Orientation",
    "PageStats",
    "RenderResult",
    "RtDocsError",
    "Tuning",
    "amount_in_words",
    "contracts_dir",
    "currency_label",
    "format_date",
    "format_money",
    "format_number",
    "format_value",
    "html_to_body",
    "load_catalog",
    "to_docx",
    "validate_body",
]
