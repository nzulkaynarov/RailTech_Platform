"""Подготовка документа к рендеру: нормализация входа, проверка по контракту, подстановка данных, HTML.

Без системных библиотек WeasyPrint: тот же путь, что у PDF, — для HTML-предпросмотра и тестов на машине.
Порядок: вычистка управляющих символов (тело, данные блоков) → лимиты и схема тела → схема данных блоков
(`#/$defs/block`) → подстановка переменных и блоков (rt_docs.resolve) → HTML только из узлов контракта (rt_docs.html).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .contracts import Catalog, load_catalog, normalize_blocks, normalize_body, validate_blocks, validate_body
from .css import PageSetup, page_setup
from .errors import ContractsNotFoundError
from .fonts import missing_glyphs
from .html import HtmlOptions, build_html
from .model import Density, DocumentMeta, Lang, Layout, Letterhead, Orientation, Tuning, Value
from .resolve import Node, plain_text, resolve


@dataclass(frozen=True)
class Prepared:
    """Тело после нормализации, проверки и подстановки — общее для нескольких проходов «Подогнать»."""

    content: Sequence[Node]
    lang: Lang
    letterhead: Letterhead
    meta: DocumentMeta
    layout: Layout
    orientation: Orientation
    density: Density | None
    tuning: Tuning
    warnings: tuple[str, ...]
    highlight_missing: bool

    def setup(self, tuning: Tuning | None = None) -> PageSetup:
        return page_setup(self.layout, self.orientation, self.density, tuning if tuning is not None else self.tuning)


def body_tuning(page: Mapping[str, Any]) -> Tuning:
    raw: Mapping[str, Any] = page.get("tuning") or {}
    return Tuning(
        line_height=raw.get("lineHeight"),
        margin_delta_mm=int(raw.get("marginDeltaMm", 0)),
        lead_mm=int(raw.get("leadMm", 0)),
    )


def checked_input(
    body: Any,
    blocks: Any,
    catalog: Catalog | None,
    contracts_dir: str | None,
) -> tuple[dict[str, Any], dict[str, list[Any]], Catalog]:
    """Нормализованные и проверенные тело и данные блоков + каталог (общий вход PDF, HTML и DOCX)."""
    clean_body = normalize_body(body)
    validate_body(clean_body, contracts_dir)
    clean_blocks = normalize_blocks(blocks if blocks is not None else {})
    validate_blocks(clean_blocks, contracts_dir)
    if catalog is None:
        try:
            catalog = load_catalog(contracts_dir)
        except ContractsNotFoundError:
            catalog = Catalog.empty()
    return clean_body, clean_blocks, catalog


def prepare(
    body: Any,
    *,
    letterhead: Letterhead,
    layout: Layout,
    meta: DocumentMeta | None = None,
    values: Mapping[str, Value] | None = None,
    blocks: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    catalog: Catalog | None = None,
    highlight_missing: bool = True,
    contracts_dir: str | None = None,
) -> Prepared:
    clean_body, clean_blocks, catalog = checked_input(body, blocks, catalog, contracts_dir)
    resolved = resolve(clean_body, values=values or {}, blocks=clean_blocks, catalog=catalog)
    page: Mapping[str, Any] = clean_body.get("page") or {}
    meta = meta or DocumentMeta()
    text = "\n".join(
        [
            plain_text(resolved.content),
            letterhead.company_name,
            *letterhead.requisites,
            *letterhead.footer,
            meta.title or "",
            meta.number or "",
            *meta.addressee,
            meta.reply_to or "",
            meta.executor or "",
        ]
    )
    warnings = resolved.warnings()
    absent = missing_glyphs(text, letterhead.font)
    if absent:
        warnings.append("characters missing from the document font: " + " ".join(f"U+{ord(c):04X}" for c in absent))
    return Prepared(
        content=resolved.content,
        lang=clean_body["lang"],
        letterhead=letterhead,
        meta=meta,
        layout=layout,
        orientation=Orientation(page.get("orientation", "portrait")),
        density=Density(page["density"]) if page.get("density") else None,
        tuning=body_tuning(page),
        warnings=tuple(warnings),
        highlight_missing=highlight_missing,
    )


def document_html(prepared: Prepared, tuning: Tuning | None = None, *, page_numbers: bool) -> str:
    """HTML документа для WeasyPrint (и для проверки на машине без pango)."""
    return build_html(
        prepared.content,
        lang=prepared.lang,
        letterhead=prepared.letterhead,
        meta=prepared.meta,
        setup=prepared.setup(tuning),
        options=HtmlOptions(page_numbers=page_numbers, highlight_missing=prepared.highlight_missing),
    )
