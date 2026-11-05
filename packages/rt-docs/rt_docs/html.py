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

import qrcode  # type: ignore[import-untyped]
import qrcode.image.svg  # type: ignore[import-untyped]

from .contracts import clean_text
from .css import PageSetup, stylesheet
from .formatters import format_date
from .labels import (
    DRAFT_MARK,
    EXECUTOR,
    MISSING_BLOCK,
    NO_NUMBER,
    REPLY_TO,
    SIGN,
    STAMP,
    VERIFY_CODE,
    VERIFY_QR_NOTE,
    number_line,
)
from .model import DocumentMeta, Lang, Layout, Letterhead
from .resolve import Node

LOGO_URL = "rtdocs:logo"
_SAFE_HREF = re.compile(r"^(https?://|mailto:|tel:)[^\s<>\"']+$")
_BLANK = "_______________"


def generate_qr_svg(url: str) -> str:
    """Генерация чистого векторного SVG QR-кода для встраивания в HTML печатной формы."""
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=6)
    res: Any = img.to_string()
    if isinstance(res, bytes):
        return res.decode("utf-8")
    return str(res)


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
    draft: bool = False  # проект (ADR-0024 п. 4): знак, «без номера», подпись без печати


class _Writer:
    def __init__(self, lang: Lang, options: HtmlOptions, meta: DocumentMeta | None = None) -> None:
        self.lang = lang
        self.options = options
        self.meta = meta or DocumentMeta()
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
        for i, party in enumerate([*parties, *([{}] if len(parties) == 1 else [])]):
            self.w("<td>")
            if party:
                if party.get("role"):
                    self.w(f'<div class="rt-sign-role">{self.field(party["role"])}</div>')
                if party.get("position"):
                    self.w(f"<div>{self.field(party['position'])}</div>")
                # Основание полномочия подписи (SIGN-3, ADR-0024 п. 5): устав — без отметки
                basis = party.get("basis") or (self.meta.basis_text if i == 0 else None)
                if basis:
                    basis_html = self.field(basis) if isinstance(basis, tuple) else e(basis)
                    self.w(f'<div class="rt-sign-basis">{basis_html}</div>')
                self.w('<div class="rt-sign-line"></div>')
                name = self.field(party["name"]) if party.get("name") else ""
                self.w(f'<div class="rt-sign-caption">{e(SIGN[self.lang])}{" · " + name if name else ""}</div>')
                if node.get("stamp") and not self.options.draft:
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
    if layout is Layout.COMMERCIAL and w.options.draft:
        w.w(f'<td class="rt-docid"><div class="rt-docno-draft">{e(NO_NUMBER[lang])}</div></td>')
    elif layout is Layout.COMMERCIAL and (meta.number or meta.date):
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
    draft = w.options.draft
    left = (
        NO_NUMBER[lang]
        if draft
        else number_line(lang, meta.number, format_date(meta.date, lang, long=False) if meta.date else None)
    )
    if not (left or meta.reply_to or meta.addressee):
        return
    w.w('<table class="rt-letter-meta"><tr><td>')
    if left:
        number_html = e(left)
        if draft:
            number_html = f'<span class="rt-docno-draft">{number_html}</span>'
        elif meta.number:
            # Номер документа — бегущий колонтитул со 2-й страницы (string-set на .rt-docno)
            ref_label = meta.number
            if meta.verification_code:
                ref_label = f"{meta.number} · {VERIFY_CODE[lang]}{meta.verification_code}"
            number_html = number_html.replace(
                e(meta.number), f'<span class="rt-docno-inline">{e(meta.number)}</span>', 1
            )
            number_html += f'<span class="rt-running-docref">{e(ref_label)}</span>'
        w.w(f"<div>{number_html}</div>")
    if not draft and meta.verification_code:
        code_html = f"<strong>{e(meta.verification_code)}</strong>"
        w.w(f'<div class="rt-verify-code-inline">{e(VERIFY_CODE[lang])}{code_html}</div>')
    if meta.reply_to:
        w.w(f"<div>{e(REPLY_TO[lang] + meta.reply_to)}</div>")
    w.w('</td><td class="rt-addressee">')
    w.w("<br>".join(e(line) for line in meta.addressee))
    w.w("</td></tr></table>")


def _render_verification_block(w: _Writer, meta: DocumentMeta) -> None:
    """Блок проверки подлинности с QR-кодом на последней странице (ADR-0024 п. 5)."""
    lang = w.lang
    url = meta.verification_url or (
        f"https://cabinet.railtech.uz/v/{meta.verification_code}" if meta.verification_code else ""
    )
    if not url:
        return
    qr_svg = generate_qr_svg(url)
    w.w('<div class="rt-verify-block">')
    w.w(f'<div class="rt-verify-qr">{qr_svg}</div>')
    w.w('<div class="rt-verify-info">')
    w.w(f'<div class="rt-verify-title">{e(VERIFY_QR_NOTE[lang])}</div>')
    if meta.verification_code:
        w.w(f'<div class="rt-verify-code">{e(VERIFY_CODE[lang])}<strong>{e(meta.verification_code)}</strong></div>')
    w.w(f'<div class="rt-verify-url">{e(url)}</div>')
    w.w("</div></div>")


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
    w = _Writer(lang, options, meta=meta)
    layout = setup.layout
    title = meta.title or letterhead.company_name
    w.w(f'<!DOCTYPE html><html lang="{_LANG_ATTR[lang]}"><head><meta charset="utf-8"><title>{e(title)}</title>')
    w.w(f"<style>{stylesheet(setup, letterhead, lang, page_numbers=options.page_numbers, draft=options.draft)}")
    w.w(".rt-docno-inline { string-set: rtdocref content(); }</style></head>")
    w.w(f'<body class="{_LAYOUT_CLASS[layout]}">')
    if options.draft:
        # position: fixed — WeasyPrint повторяет знак на каждой странице.
        w.w(f'<div class="rt-draft-mark">{e(DRAFT_MARK[lang])}</div>')
    if layout is Layout.COMMERCIAL and letterhead.footer:
        # Бегущий подвал — в начале потока: значение действует с первой страницы до последней.
        w.w(f'<div class="rt-footer">{"<br>".join(e(line) for line in letterhead.footer)}</div>')
    _letterhead(w, letterhead, meta, layout)
    _letter_meta(w, meta, layout)
    if meta.title:
        w.w(f'<h1 class="rt-title">{e(meta.title)}</h1>')
    w.w('<main class="rt-body">')
    w.blocks(content)
    if not options.draft and (meta.verification_code or meta.verification_url):
        _render_verification_block(w, meta)
    w.w("</main>")
    if meta.executor and layout is not Layout.COMMERCIAL:
        # Бегущий элемент в конце потока: появляется только на последней странице (внизу слева).
        w.w(f'<div class="rt-executor">{e(EXECUTOR[lang] + meta.executor)}</div>')
    w.w("</body></html>")
    return "".join(w.out)
