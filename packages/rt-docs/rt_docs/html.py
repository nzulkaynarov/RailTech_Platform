"""Тело JSON → HTML документа (для WeasyPrint и предпросмотра).

Безопасность по построению (ADR-0020 п. 2): рендерятся только известные узлы контракта, весь текст экранируется
(`html.escape`), сырого HTML из тела нет; атрибуты — только классы из фиксированного набора, числа и ссылки по белому
списку схем. Ресурсы (шрифты, логотип) — адреса `rtdocs:` для безопасного fetcher'а (rt_docs.fetcher).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Any

from .contracts import clean_text
from .css import PageSetup, stylesheet
from .formatters import format_date
from .labels import EXECUTOR, MISSING_BLOCK, REPLY_TO, SIGN, STAMP, number_line
from .model import DocumentMeta, Lang, Layout, Letterhead
from .resolve import Node

LOGO_URL = "rtdocs:logo"
_SAFE_HREF = re.compile(r"^(https?://|mailto:|tel:)[^\s<>\"']+$")
_BLANK = "_______________"
_LAYOUT_CLASS = {
    Layout.LETTER: "rt-layout-letter",
    Layout.INTERNAL: "rt-layout-internal",
    Layout.COMMERCIAL: "rt-layout-commercial",
}
_LANG_ATTR = {"ru": "ru", "uz": "uz", "en": "en"}


def e(text: str) -> str:
    """Экранирование всего, что попадает в HTML из данных; управляющие символы вычищаются."""
    return escape(clean_text(str(text)), quote=True)


@dataclass(frozen=True)
class HtmlOptions:
    page_numbers: bool
    highlight_missing: bool = True


class _Writer:
    def __init__(self, lang: Lang, options: HtmlOptions) -> None:
        self.lang = lang
        self.options = options
        self.out: list[str] = []

    def w(self, *parts: str) -> None:
        self.out.extend(parts)

    # ─── inline ──────────────────────────────────────────────────────────────────────────────────

    def inline(self, nodes: Sequence[Mapping[str, Any]]) -> None:
        for node in nodes:
            kind = node["type"]
            if kind == "hardBreak":
                self.w("<br>")
            elif kind == "text":
                self.text(node)

    def text(self, node: Mapping[str, Any]) -> None:
        if node.get("_missing"):
            body = f"[{e(node['text'])}]" if self.options.highlight_missing else _BLANK
            cls = "rt-var rt-var-missing" if self.options.highlight_missing else "rt-var"
            content = f'<span class="{cls}">{body}</span>'
        elif node.get("_var"):
            content = f'<span class="rt-var">{e(node["text"])}</span>'
        else:
            content = e(node["text"])
        for mark in reversed(node.get("marks") or ()):
            content = self.mark(mark, content)
        self.w(content)

    def mark(self, mark: Mapping[str, Any], content: str) -> str:
        kind = mark["type"]
        if kind == "bold":
            return f"<strong>{content}</strong>"
        if kind == "italic":
            return f"<em>{content}</em>"
        if kind == "underline":
            return f"<u>{content}</u>"
        if kind == "link":
            href = str(mark.get("attrs", {}).get("href", ""))
            return f'<a href="{e(href)}">{content}</a>' if _SAFE_HREF.match(href) else content
        return content

    # ─── блоки ───────────────────────────────────────────────────────────────────────────────────

    def blocks(self, nodes: Sequence[Mapping[str, Any]]) -> None:
        for node in nodes:
            self.block(node)

    def block(self, node: Mapping[str, Any]) -> None:
        kind = node["type"]
        attrs = node.get("attrs") or {}
        if kind == "paragraph":
            self.w(f"<p{_align(attrs)}>")
            self.inline(node.get("content", ()))
            self.w("</p>")
        elif kind == "heading":
            level = int(attrs["level"])
            self.w(f"<h{level}{_align(attrs)}>")
            self.inline(node.get("content", ()))
            self.w(f"</h{level}>")
        elif kind in ("bulletList", "orderedList"):
            tag = "ul" if kind == "bulletList" else "ol"
            start = int(attrs.get("start", 1))
            self.w(f'<{tag} start="{start}">' if tag == "ol" and start != 1 else f"<{tag}>")
            for item in node["content"]:
                self.w("<li>")
                self.blocks(item["content"])
                self.w("</li>")
            self.w(f"</{tag}>")
        elif kind == "table":
            self.table(node)
        elif kind == "pageBreak":
            self.w('<div class="rt-pb"></div>')
        elif kind == "signature":
            self.signature(node)
        elif kind == "_block":
            self.locked_block(node)

    def table(self, node: Mapping[str, Any]) -> None:
        attrs = node.get("attrs") or {}
        variant = attrs.get("variant", "grid")
        if variant not in ("grid", "plain", "totals"):
            variant = "grid"
        rows: list[Mapping[str, Any]] = list(node["content"])
        head = 0
        for row in rows:
            if all(cell["type"] == "tableHeader" for cell in row["content"]):
                head += 1
            else:
                break
        if head == len(rows):
            head = 0  # таблица из одних заголовков — без повторяемой шапки
        self.w(f'<table class="rt-table rt-{variant}">')
        widths = attrs.get("columnWidths")
        if widths:
            total = sum(float(x) for x in widths) or 1.0
            self.w("<colgroup>")
            for width in widths:
                self.w(f'<col style="width: {float(width) * 100 / total:.3f}%">')
            self.w("</colgroup>")
        if head:
            self.w("<thead>")
            for row in rows[:head]:
                self.row(row)
            self.w("</thead>")
        self.w("<tbody>")
        for row in rows[head:]:
            self.row(row)
        self.w("</tbody></table>")

    def row(self, row: Mapping[str, Any]) -> None:
        emphasis = bool((row.get("attrs") or {}).get("emphasis"))
        self.w('<tr class="rt-em">' if emphasis else "<tr>")
        for cell in row["content"]:
            tag = "th" if cell["type"] == "tableHeader" else "td"
            attrs = cell.get("attrs") or {}
            classes = []
            if attrs.get("numeric"):
                classes.append("rt-num")
            if attrs.get("align") in ("center", "right"):
                classes.append(f"rt-al-{attrs['align']}")
            span = ""
            if int(attrs.get("colspan", 1)) > 1:
                span += f' colspan="{int(attrs["colspan"])}"'
            if int(attrs.get("rowspan", 1)) > 1:
                span += f' rowspan="{int(attrs["rowspan"])}"'
            cls = f' class="{" ".join(classes)}"' if classes else ""
            self.w(f"<{tag}{cls}{span}>")
            self.blocks(cell["content"])
            self.w(f"</{tag}>")
        self.w("</tr>")

    def signature(self, node: Mapping[str, Any]) -> None:
        parties: list[Mapping[str, Any]] = list(node["parties"])
        self.w('<table class="rt-signature"><tr>')
        for party in [*parties, *([{}] if len(parties) == 1 else [])]:
            self.w("<td>")
            if party:
                if party.get("role"):
                    self.w(f'<div class="rt-sign-role">{self.field(party["role"])}</div>')
                if party.get("position"):
                    self.w(f"<div>{self.field(party['position'])}</div>")
                self.w('<div class="rt-sign-line"></div>')
                name = self.field(party["name"]) if party.get("name") else ""
                self.w(f'<div class="rt-sign-caption">{e(SIGN[self.lang])}{" · " + name if name else ""}</div>')
                if node.get("stamp"):
                    self.w(f'<div class="rt-stamp">{e(STAMP[self.lang])}</div>')
            self.w("</td>")
        self.w("</tr></table>")

    def field(self, value: tuple[str, bool]) -> str:
        text, missing = value
        if missing:
            return f'<span class="rt-var-missing">[{e(text)}]</span>' if self.options.highlight_missing else _BLANK
        return e(text)

    def locked_block(self, node: Mapping[str, Any]) -> None:
        # Класс — только из фиксированного набора: код блока в разметку не попадает.
        classes = ["rt-block"]
        if node.get("keep"):
            classes.append("rt-keep")
        if node.get("missing"):
            classes.append("rt-block-missing")
            self.w(f'<div class="{" ".join(classes)}">{e(MISSING_BLOCK[self.lang].format(label=node["label"]))}</div>')
            return
        self.w(f'<div class="{" ".join(classes)}">')
        self.blocks(node["content"])
        self.w("</div>")


def _align(attrs: Mapping[str, Any]) -> str:
    align = attrs.get("textAlign")
    return f' class="rt-al-{align}"' if align in ("left", "center", "right", "justify") else ""


def _letterhead(w: _Writer, letterhead: Letterhead, meta: DocumentMeta, layout: Layout) -> None:
    lang = w.lang
    if layout is Layout.INTERNAL:
        w.w('<div class="rt-int-head">')
        w.w(f'<div class="rt-company">{e(letterhead.company_name)}</div>')
        w.w("</div>")
        return
    w.w('<header><table class="rt-brand"><tr>')
    if letterhead.logo is not None:
        w.w(f'<td class="rt-logo"><img src="{LOGO_URL}" alt=""></td>')
    w.w(f'<td><div class="rt-company">{e(letterhead.company_name)}</div>')
    if letterhead.requisites:
        w.w(f'<div class="rt-req">{"<br>".join(e(line) for line in letterhead.requisites)}</div>')
    w.w("</td>")
    if layout is Layout.COMMERCIAL and (meta.number or meta.date):
        w.w('<td class="rt-docid">')
        if meta.number:
            w.w(f'<div class="rt-docno">{e(meta.number)}</div>')
        if meta.date:
            w.w(f"<div>{e(format_date(meta.date, lang))}</div>")
        w.w("</td>")
    w.w('</tr></table><div class="rt-rule"></div></header>')


def _letter_meta(w: _Writer, meta: DocumentMeta, layout: Layout) -> None:
    if layout is Layout.COMMERCIAL:
        return
    lang = w.lang
    left = number_line(lang, meta.number, format_date(meta.date, lang, long=False) if meta.date else None)
    if not (left or meta.reply_to or meta.addressee):
        return
    w.w('<table class="rt-letter-meta"><tr><td>')
    if left:
        number_html = e(left)
        if meta.number:
            # Номер документа — бегущий колонтитул со 2-й страницы (string-set на .rt-docno)
            number_html = number_html.replace(
                e(meta.number), f'<span class="rt-docno-inline">{e(meta.number)}</span>', 1
            )
        w.w(f"<div>{number_html}</div>")
    if meta.reply_to:
        w.w(f"<div>{e(REPLY_TO[lang] + meta.reply_to)}</div>")
    w.w('</td><td class="rt-addressee">')
    w.w("<br>".join(e(line) for line in meta.addressee))
    w.w("</td></tr></table>")


def build_html(
    content: Sequence[Node],
    *,
    lang: Lang,
    letterhead: Letterhead,
    meta: DocumentMeta,
    setup: PageSetup,
    options: HtmlOptions,
) -> str:
    """HTML всего документа: бланк, реквизиты, тело, подписи, колонтитулы."""
    w = _Writer(lang, options)
    layout = setup.layout
    title = meta.title or letterhead.company_name
    w.w(f'<!DOCTYPE html><html lang="{_LANG_ATTR[lang]}"><head><meta charset="utf-8"><title>{e(title)}</title>')
    w.w(f"<style>{stylesheet(setup, letterhead, lang, page_numbers=options.page_numbers)}")
    w.w(".rt-docno-inline { string-set: rtdocref content(); }</style></head>")
    w.w(f'<body class="{_LAYOUT_CLASS[layout]}">')
    if layout is Layout.COMMERCIAL and letterhead.footer:
        # Бегущий подвал — в начале потока: значение действует с первой страницы до последней.
        w.w(f'<div class="rt-footer">{"<br>".join(e(line) for line in letterhead.footer)}</div>')
    _letterhead(w, letterhead, meta, layout)
    _letter_meta(w, meta, layout)
    if meta.title:
        w.w(f'<h1 class="rt-title">{e(meta.title)}</h1>')
    w.w('<main class="rt-body">')
    w.blocks(content)
    w.w("</main>")
    if meta.executor and layout is not Layout.COMMERCIAL:
        # Бегущий элемент в конце потока: появляется только на последней странице (внизу слева).
        w.w(f'<div class="rt-executor">{e(EXECUTOR[lang] + meta.executor)}</div>')
    w.w("</body></html>")
    return "".join(w.out)
