"""Facade module for sourcing views.

The concrete view classes live in focused submodules (kept under the 500-line
file limit); this module re-exports them so existing importers
(`from sourcing.views import ...`) and the URLconf keep working unchanged.

- views_imports.py   — Excel/catalog imports, import status, catalog template
- views_attachments.py — AttachmentViewSet
- views_ai.py        — AI match / preflight / document-extract endpoints
"""

from .views_ai import (  # noqa: F401
    MAX_DOC_FILE_SIZE,
    DocumentExtractView,
    MatchCatalogView,
    PreflightCheckView,
    QuoteImportFileView,
    _resolve_expected,
)
from .views_attachments import AttachmentViewSet  # noqa: F401
from .views_imports import (  # noqa: F401
    CATALOG_TEMPLATE_EXAMPLE,
    CATALOG_TEMPLATE_HEADERS,
    MAX_EXCEL_FILE_SIZE,
    XLSX_MAGIC,
    CatalogImportView,
    CatalogTemplateView,
    ExcelImportView,
    ImportCatalogAiView,
    ImportStatusView,
    _check_deal_access,
    _validate_xlsx_signature,
)

__all__ = [
    "AttachmentViewSet",
    "CatalogImportView",
    "ImportCatalogAiView",
    "CatalogTemplateView",
    "DocumentExtractView",
    "QuoteImportFileView",
    "ExcelImportView",
    "ImportStatusView",
    "MatchCatalogView",
    "PreflightCheckView",
    "MAX_DOC_FILE_SIZE",
    "MAX_EXCEL_FILE_SIZE",
    "XLSX_MAGIC",
    "CATALOG_TEMPLATE_HEADERS",
    "CATALOG_TEMPLATE_EXAMPLE",
    "_resolve_expected",
    "_check_deal_access",
    "_validate_xlsx_signature",
]
