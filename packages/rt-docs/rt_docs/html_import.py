"""HTML-шаблоны ERP → тело JSON (миграция D-DOC3, исследование §3.7) с отчётом о потерях.

Вход — тело `DocumentTemplate.body_html` после санитайзера ERP (`crm/services/document_placeholders.py`: p, br, h1–h4,
strong, em, u, ul, ol, li, table, thead, tbody, tr, td, th, div, span, hr, img, a; style/class/id срезаны). Узлы
переносятся 1:1, плейсхолдеры `{{код}}` → переменные, `{{doc.*}}` → блоки с замком (абзац из одного токена — блок;
токен посреди текста делит абзац). Всё, что в схеме тела не выражается, — в отчёте `losses` (код и деталь), а не молча.
Детерминированно, без сети; парсер — stdlib `html.parser`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from .contracts import Catalog
from .model import Lang

Node = dict[str, Any]
PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")
_VAR_CODE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_BLOCK_CODE = re.compile(r"^doc\.[a-z][a-z0-9_]*$")
_SAFE_HREF = re.compile(r"^(https?://|mailto:|tel:)[^\s<>\"']+$")
LEGACY_CODES = {"today": "system.today"}

_VOID = {"br", "hr", "img", "meta", "link", "input", "col"}
_DROP = {"script", "style", "iframe", "object", "embed", "head", "title", "template"}
_BLOCK_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "table",
    "div",
    "hr",
    "blockquote",
    "section",
    "article",
    "header",
    "footer",
    "main",
}
_MARKS = {"strong": "bold", "b": "bold", "em": "italic", "i": "italic", "u": "underline"}


@dataclass(frozen=True)
class Loss:
    #: tag | attribute | image | hr | heading_level | placeholder_* | nested_table | cell_content | block_position
    code: str
    detail: str


@dataclass
class ImportResult:
    body: dict[str, Any]
    losses: list[Loss] = field(default_factory=list)


@dataclass
class _El:
    tag: str
    attrs: dict[str, str]
    children: list[_El | str] = field(default_factory=list)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _El("root", {})
        self.stack = [self.root]
        self.dropping = 0
        self.dropped: list[str] = []
        self.attrs_dropped: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.dropping:
            if tag not in _VOID:
                self.dropping += 1
            return
        if tag in _DROP:
            self.dropped.append(tag)
            self.dropping = 1
            return
        kept: dict[str, str] = {}
        for name, value in attrs:
            if name in ("href", "src", "alt", "colspan", "rowspan", "start"):
                kept[name] = value or ""
            else:
                self.attrs_dropped.add(name)
        element = _El(tag, kept)
        self.stack[-1].children.append(element)
        if tag not in _VOID:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID and not self.dropping and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if self.dropping:
            self.dropping -= 1
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not self.dropping:
            self.stack[-1].children.append(data)


class _Converter:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.losses: list[Loss] = []

    def lose(self, code: str, detail: str) -> None:
        loss = Loss(code, detail)
        if loss not in self.losses:
            self.losses.append(loss)

    # ─── inline ──────────────────────────────────────────────────────────────────────────────────

    def inline(self, items: Iterable[_El | str], marks: tuple[str, ...] = (), href: str | None = None) -> list[Node]:
        out: list[Node] = []
        for item in items:
            if isinstance(item, str):
                out += self.text(item, marks, href)
                continue
            tag = item.tag
            if tag == "br":
                out.append({"type": "hardBreak"})
            elif tag in _MARKS:
                out += self.inline(item.children, (*marks, _MARKS[tag]), href)
            elif tag == "a":
                link = item.attrs.get("href", "")
                if _SAFE_HREF.match(link):
                    out += self.inline(item.children, marks, link)
                else:
                    if link:
                        self.lose("attribute", f"ссылка {link[:60]!r} не по белому списку — оставлен текст")
                    out += self.inline(item.children, marks, href)
            elif tag == "img":
                self.lose("image", "картинка в тексте не переносится (логотип — в бланке, файлы — хранилище, D-DOC3)")
            elif tag == "span":
                out += self.inline(item.children, marks, href)
            else:
                if tag not in _BLOCK_TAGS:
                    self.lose("tag", f"<{tag}> развёрнут в текст")
                out += self.inline(item.children, marks, href)
        return out

    def text(self, raw: str, marks: tuple[str, ...], href: str | None) -> list[Node]:
        value = re.sub(r"\s+", " ", raw)
        if not value:
            return []
        out: list[Node] = []
        position = 0
        for match in PLACEHOLDER.finditer(value):
            if match.start() > position:
                out.append(self._text_node(value[position : match.start()], marks, href))
            out.append(self.placeholder(match.group(1), match.group(0), marks, href))
            position = match.end()
        if position < len(value):
            out.append(self._text_node(value[position:], marks, href))
        return out

    def _text_node(self, value: str, marks: tuple[str, ...], href: str | None) -> Node:
        node: Node = {"type": "text", "text": value}
        mark_list: list[dict[str, Any]] = [{"type": m} for m in dict.fromkeys(marks)]
        if href:
            mark_list.append({"type": "link", "attrs": {"href": href}})
        if mark_list:
            node["marks"] = mark_list
        return node

    def placeholder(self, code: str, raw: str, marks: tuple[str, ...], href: str | None) -> Node:
        code = LEGACY_CODES.get(code, code)
        if _BLOCK_CODE.match(code):
            if self.catalog.blocks and code not in self.catalog.blocks:
                self.lose("placeholder_unknown", f"блок {code} нет в каталоге")
            return {"type": "_block", "code": code}
        if not _VAR_CODE.match(code):
            self.lose("placeholder_invalid", f"{raw} не похож на код каталога — оставлен текстом")
            return self._text_node(raw, marks, href)
        if self.catalog.variables and code not in self.catalog.variables:
            self.lose(
                "placeholder_unknown", f"переменной {code} нет в каталоге — оставлена, подсветится в предпросмотре"
            )
        node: Node = {"type": "variable", "attrs": {"code": code}}
        if marks:
            node["marks"] = [{"type": m} for m in dict.fromkeys(marks)]
        return node

    def no_blocks(self, nodes: list[Node], where: str) -> list[Node]:
        kept = [n for n in nodes if n["type"] != "_block"]
        for n in nodes:
            if n["type"] == "_block":
                self.lose(
                    "block_position", f"блок {n['code']} в {where} не переносится — поставьте его отдельным абзацем"
                )
        return kept

    # ─── блоки ───────────────────────────────────────────────────────────────────────────────────

    def paragraphs(self, inline: list[Node], align: str | None = None) -> list[Node]:
        """Инлайн-узлы → абзацы; токен блока делит абзац, абзац из одного токена становится блоком."""
        out: list[Node] = []
        current: list[Node] = []

        def flush() -> None:
            trimmed = _trim(current)
            if trimmed:
                node: Node = {"type": "paragraph", "content": trimmed}
                if align:
                    node["attrs"] = {"textAlign": align}
                out.append(node)
            current.clear()

        for node in inline:
            if node["type"] == "_block":
                flush()
                out.append({"type": "block", "attrs": {"code": node["code"], "locked": True}})
            else:
                current.append(node)
        flush()
        return out

    def blocks(self, items: Iterable[_El | str]) -> list[Node]:
        out: list[Node] = []
        pending: list[_El | str] = []

        def flush_inline() -> None:
            if pending:
                out.extend(self.paragraphs(self.inline(pending)))
                pending.clear()

        for item in items:
            if isinstance(item, str) or item.tag not in _BLOCK_TAGS:
                pending.append(item)
                continue
            flush_inline()
            out += self.block(item)
        flush_inline()
        return out

    def block(self, el: _El) -> list[Node]:
        tag = el.tag
        if tag == "p":
            if any(isinstance(c, _El) and c.tag in _BLOCK_TAGS for c in el.children):
                return self.blocks(el.children)
            result = self.paragraphs(self.inline(el.children))
            return result or [{"type": "paragraph"}]
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            if level > 3:
                self.lose("heading_level", f"<{tag}> → заголовок 3-го уровня")
                level = 3
            content = self.no_blocks(_trim(self.inline(el.children)), "заголовке")
            return [{"type": "heading", "attrs": {"level": level}, "content": content}]
        if tag in ("ul", "ol"):
            return [self.list_(el)]
        if tag == "table":
            return [self.table(el)]
        if tag == "hr":
            self.lose("hr", "горизонтальная линия не переносится (оформление — бланк)")
            return []
        if tag != "div":
            self.lose("tag", f"<{tag}> → обычные абзацы")
        return self.blocks(el.children)

    def list_(self, el: _El) -> Node:
        items: list[Node] = []
        for child in el.children:
            if isinstance(child, str):
                if child.strip():
                    items.append(
                        {
                            "type": "listItem",
                            "content": [{"type": "paragraph", "content": self.text(child.strip(), (), None)}],
                        }
                    )
                continue
            if child.tag != "li":
                self.lose("tag", f"<{child.tag}> внутри списка → пункт")
            inline_part = [c for c in child.children if isinstance(c, str) or c.tag not in ("ul", "ol")]
            nested = [c for c in child.children if isinstance(c, _El) and c.tag in ("ul", "ol")]
            paragraph: Node = {
                "type": "paragraph",
                "content": self.no_blocks(_trim(self.inline(inline_part)), "списке"),
            }
            content: list[Node] = [paragraph] + [self.list_(n) for n in nested]
            items.append({"type": "listItem", "content": content})
        if not items:
            items.append({"type": "listItem", "content": [{"type": "paragraph"}]})
        node: Node = {"type": "bulletList" if el.tag == "ul" else "orderedList", "content": items}
        start = el.attrs.get("start", "")
        if el.tag == "ol" and start.isdigit() and int(start) > 1:
            node["attrs"] = {"start": int(start)}
        return node

    def table(self, el: _El) -> Node:
        rows: list[tuple[_El, bool]] = []

        def collect(parent: _El, in_head: bool) -> None:
            for child in parent.children:
                if isinstance(child, _El):
                    if child.tag == "tr":
                        rows.append((child, in_head))
                    elif child.tag in ("thead", "tbody", "tfoot"):
                        collect(child, child.tag == "thead")

        collect(el, False)
        out_rows: list[Node] = []
        for tr, in_head in rows:
            cells: list[Node] = []
            for td in tr.children:
                if not isinstance(td, _El) or td.tag not in ("td", "th"):
                    continue
                if any(isinstance(c, _El) and c.tag == "table" for c in td.children):
                    self.lose("nested_table", "вложенная таблица → текст ячейки")
                converted = self.blocks(td.children)
                if any(b["type"] != "paragraph" for b in converted):
                    self.lose(
                        "cell_content",
                        "в ячейке таблицы остаются только абзацы (блоки, списки и таблицы — текстом не переносятся)",
                    )
                content = [b for b in converted if b["type"] == "paragraph"] or [{"type": "paragraph"}]
                cell: Node = {"type": "tableHeader" if (td.tag == "th" or in_head) else "tableCell", "content": content}
                attrs: dict[str, int] = {}
                for name in ("colspan", "rowspan"):
                    raw = td.attrs.get(name, "")
                    if raw.isdigit() and int(raw) > 1:
                        attrs[name] = min(int(raw), 20 if name == "colspan" else 1000)
                if attrs:
                    cell["attrs"] = attrs
                cells.append(cell)
            if cells:
                out_rows.append({"type": "tableRow", "content": cells})
        if not out_rows:
            out_rows = [{"type": "tableRow", "content": [{"type": "tableCell", "content": [{"type": "paragraph"}]}]}]
        return {"type": "table", "content": out_rows}


def _trim(nodes: list[Node]) -> list[Node]:
    """Пробелы по краям абзаца (как в HTML) и пустые текстовые узлы."""
    out = [dict(n) for n in nodes]
    while out and out[0]["type"] == "hardBreak":
        out.pop(0)
    while out and out[-1]["type"] == "hardBreak":
        out.pop()
    if out and out[0]["type"] == "text":
        out[0]["text"] = out[0]["text"].lstrip()
    if out and out[-1]["type"] == "text":
        out[-1]["text"] = out[-1]["text"].rstrip()
    return [n for n in out if n["type"] != "text" or n["text"]]


def html_to_body(html: str, *, lang: Lang = "ru", catalog: Catalog | None = None) -> ImportResult:
    """HTML (санитизированный шаблон ERP) → тело по контракту `documents/body.schema.json` и отчёт о потерях."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    converter = _Converter(catalog or Catalog.empty())
    for tag in dict.fromkeys(builder.dropped):
        converter.lose("tag", f"<{tag}> удалён вместе с содержимым")
    for name in sorted(builder.attrs_dropped):
        converter.lose("attribute", f"атрибут {name} не переносится (оформление задаёт бланк)")
    content = converter.blocks(builder.root.children) or [{"type": "paragraph"}]
    body = {"version": 1, "lang": lang, "doc": {"type": "doc", "content": content}}
    return ImportResult(body=body, losses=converter.losses)
