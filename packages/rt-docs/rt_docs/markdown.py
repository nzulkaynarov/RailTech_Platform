"""Мост Markdown ↔ тело документа (план 1.3): черновик помощника становится телом документа и обратно.

* `markdown_to_body` — Markdown (CommonMark и таблицы GFM) → HTML готовым парсером `markdown-it-py` (сырой HTML
  выключен, ссылки только безопасные) → тело через `html_to_body`: те же правила и тот же отчёт о потерях, что у импорта
  шаблонов. Плейсхолдеры `{{код}}` становятся переменными и блоками с замком.
* `body_to_markdown` — тело → Markdown для помощника: абзацы, заголовки, списки, таблицы, жирный и курсив, ссылки,
  переменные `{{код}}` и блоки `{{doc.код}}`. Подчёркивание, ширины колонок, выравнивание и разрыв страницы в Markdown
  не выражаются — они теряются (оформление задают шаблон и бланк).

Детерминированно, без сети.
"""

from __future__ import annotations

from typing import Any

from markdown_it import MarkdownIt

from .contracts import Catalog
from .html_import import ImportResult, html_to_body
from .model import Lang

Node = dict[str, Any]

#: Специальные символы Markdown в тексте: экранируются, чтобы текст вернулся тем же текстом.
_ESCAPE = str.maketrans({ch: f"\\{ch}" for ch in "\\`*_[]<>#|"})


def _parser() -> MarkdownIt:
    # «commonmark» + таблицы GFM; сырой HTML выключен — помощник не протащит разметку мимо санитайзера тела.
    return MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")


def markdown_to_body(markdown: str, *, lang: Lang = "ru", catalog: Catalog | None = None) -> ImportResult:
    """Markdown → тело по контракту `documents/body.schema.json` и отчёт о потерях (как `html_to_body`)."""
    return html_to_body(_parser().render(markdown or ""), lang=lang, catalog=catalog)


def _text(node: Node) -> str:
    if node["type"] == "hardBreak":
        return "  \n"
    if node["type"] == "variable":
        value = "{{" + str(node["attrs"]["code"]) + "}}"
    else:
        value = str(node.get("text", "")).translate(_ESCAPE)
    kinds = [mark["type"] for mark in node.get("marks", [])]
    if "italic" in kinds:
        value = f"*{value}*"
    if "bold" in kinds:
        value = f"**{value}**"
    link = next((mark for mark in node.get("marks", []) if mark["type"] == "link"), None)
    if link is not None:
        value = f"[{value}]({link['attrs']['href']})"
    return value


def _inline(nodes: list[Node]) -> str:
    return "".join(_text(node) for node in nodes)


def _cell(cell: Node) -> str:
    # Ячейка таблицы Markdown — одна строка: абзацы ячейки через пробел, `|` уже экранирован в тексте.
    return " ".join(_inline(p.get("content", [])) for p in cell.get("content", [])).replace("\n", " ").strip()


def _table(node: Node) -> list[str]:
    rows = node.get("content", [])
    if not rows:
        return []
    width = max(len(row.get("content", [])) for row in rows)
    lines = []
    for index, row in enumerate(rows):
        cells = [_cell(cell) for cell in row.get("content", [])]
        cells += [""] * (width - len(cells))
        lines.append("| " + " | ".join(cells) + " |")
        if index == 0:
            lines.append("|" + "|".join(" --- " for _ in range(width)) + "|")
    return lines


def _list(node: Node, depth: int) -> list[str]:
    ordered = node["type"] == "orderedList"
    start = int((node.get("attrs") or {}).get("start", 1)) if ordered else 1
    indent = "   " * depth
    lines: list[str] = []
    for number, item in enumerate(node.get("content", []), start=start):
        marker = f"{number}. " if ordered else "- "
        first = True
        for child in item.get("content", []):
            if child["type"] in ("bulletList", "orderedList"):
                lines += _list(child, depth + 1)
            elif first:
                lines.append(f"{indent}{marker}{_inline(child.get('content', []))}")
                first = False
            else:
                lines.append(f"{indent}   {_inline(child.get('content', []))}")
    return lines


def _block(node: Node) -> list[str]:
    kind = node["type"]
    if kind == "paragraph":
        return [_inline(node.get("content", []))]
    if kind == "heading":
        level = int((node.get("attrs") or {}).get("level", 1))
        return ["#" * level + " " + _inline(node.get("content", []))]
    if kind in ("bulletList", "orderedList"):
        return _list(node, 0)
    if kind == "table":
        return _table(node)
    if kind == "block":
        return ["{{" + str(node["attrs"]["code"]) + "}}"]
    return []  # pageBreak, signature — оформление шаблона, в черновике не нужны


def body_to_markdown(body: Node) -> str:
    """Тело документа → Markdown для помощника; блоки разделены пустой строкой."""
    blocks = (body.get("doc") or {}).get("content", [])
    parts = ["\n".join(lines) for lines in (_block(node) for node in blocks) if lines and any(lines)]
    return "\n\n".join(parts).strip() + "\n" if parts else ""
