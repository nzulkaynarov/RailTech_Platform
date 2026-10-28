"""Версия движка PDF: rt_docs.pdf опирается на внутренности WeasyPrint 69 (FontConfiguration, боксы страниц)."""

from __future__ import annotations

from .errors import RtDocsError

SUPPORTED_MAJOR = 69


def check_weasyprint_version(version: str) -> None:
    """Другая мажорная версия WeasyPrint — понятная ошибка при импорте, а не тихо неверная вёрстка."""
    major = version.split(".", 1)[0]
    if major != str(SUPPORTED_MAJOR):
        raise RtDocsError(
            f"rt_docs.pdf supports WeasyPrint {SUPPORTED_MAJOR}.x, found {version}: font isolation and page statistics "
            "use its internals — pin weasyprint>=69,<70 or update rt_docs (docs/architecture/rt-docs.md §4)"
        )
