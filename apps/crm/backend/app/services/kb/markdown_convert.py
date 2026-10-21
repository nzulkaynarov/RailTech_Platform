"""Встроенный конвертер Markdown → DoclingDocument (M5-CRM-02, ADR-0011).

Единственный конвертер базы знаний: в неё принимается только `.md` по docs/kb/FORMAT.md.
Работает в процессе CRM, без docling-serve и без новых зависимостей: только `docling-core`.
Front matter YAML отбрасывается (метаданные — в `kb_documents`), в чанки идёт тело.
Понимает заголовки (`#`…`######`) → разделы, абзацы, маркированные и нумерованные списки,
блоки кода и markdown-таблицы (→ `TableItem`, чанкер печатает их markdown-таблицей).
Вложенность списков не сохраняется (плоский список), встроенная разметка (`**`, ссылки) остаётся
в тексте как есть, HTML-теги и картинки не разбираются. Полученный документ идёт в тот же
`HybridChunker`, что и результат docling-serve.
"""

import re
from typing import Final

from docling_core.types.doc import DoclingDocument, TableCell, TableData
from docling_core.types.doc.labels import DocItemLabel, GroupLabel

from app.services.kb.format import split_front_matter

MARKDOWN_SUFFIX: Final = ".md"

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(```|~~~)")
_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$")
_RULE = re.compile(r"^ {0,3}([-*_])([ \t]*\1){2,}[ \t]*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


def is_markdown_file(filename: str) -> bool:
    return filename.lower().endswith(MARKDOWN_SUFFIX)


class MarkdownConverter:
    """Реализует протокол `Converter` ингеста (`async convert`)."""

    async def convert(self, filename: str, content: bytes, mime: str) -> DoclingDocument:
        if not is_markdown_file(filename):
            raise ValueError(f"knowledge base accepts only Markdown, got {filename!r}")
        text = content.decode("utf-8-sig", errors="replace")
        return markdown_to_document(filename, split_front_matter(text).body)


def markdown_to_document(name: str, text: str) -> DoclingDocument:
    doc = DoclingDocument(name=name)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paragraph: list[str] = []
    items: list[str] = []  # текущий список: пункты (хвосты строк дописываются к последнему)
    enumerated = False
    i = 0

    def flush_paragraph() -> None:
        if paragraph:
            doc.add_text(DocItemLabel.TEXT, " ".join(paragraph))
            paragraph.clear()

    def flush_list() -> None:
        if items:
            group = doc.add_group(label=GroupLabel.ORDERED_LIST if enumerated else GroupLabel.LIST)
            for k, item in enumerate(items, 1):
                doc.add_list_item(
                    item, enumerated=enumerated, marker=f"{k}." if enumerated else "-", parent=group
                )
            items.clear()

    def flush_all() -> None:
        flush_paragraph()
        flush_list()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if _FENCE.match(line):
            flush_all()
            fence = _FENCE.match(line).group(1)  # type: ignore[union-attr]
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                code.append(lines[i])
                i += 1
            if "".join(code).strip():
                doc.add_code("\n".join(code))
            i += 1
            continue
        if not stripped:
            flush_all()
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_all()
            title = (heading.group(2) or "").strip()
            if title:
                doc.add_heading(title, level=len(heading.group(1)))
            i += 1
            continue
        if _RULE.match(line):
            flush_all()
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and _is_separator(lines[i + 1]):
            flush_all()
            rows: list[list[str]] = [_split_row(line)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            doc.add_table(_table_data(rows))
            continue
        item = _LIST_ITEM.match(line)
        if item and not _RULE.match(line):
            flush_paragraph()
            ordered = item.group(2)[0].isdigit()
            if items and ordered != enumerated:
                flush_list()
            enumerated = ordered
            items.append(item.group(3).strip())
            i += 1
            continue
        text_line = stripped.lstrip(">").strip()
        if items and line[:1] in {" ", "\t"}:
            items[-1] = f"{items[-1]} {text_line}"  # продолжение пункта списка
        else:
            flush_list()
            if text_line:
                paragraph.append(text_line)
        i += 1
    flush_all()
    return doc


def _is_separator(line: str) -> bool:
    return "-" in line and bool(_TABLE_SEPARATOR.match(line))


def _split_row(line: str) -> list[str]:
    body = line.strip()
    body = body.removeprefix("|").removesuffix("|")
    # экранированный `\|` остаётся частью ячейки
    cells = re.split(r"(?<!\\)\|", body)
    return [c.strip().replace("\\|", "|") for c in cells]


def _table_data(rows: list[list[str]]) -> TableData:
    cols = max(len(r) for r in rows)
    cells = [
        TableCell(
            text=row[c] if c < len(row) else "",
            start_row_offset_idx=r,
            end_row_offset_idx=r + 1,
            start_col_offset_idx=c,
            end_col_offset_idx=c + 1,
            column_header=r == 0,
        )
        for r, row in enumerate(rows)
        for c in range(cols)
    ]
    return TableData(table_cells=cells, num_rows=len(rows), num_cols=cols)
