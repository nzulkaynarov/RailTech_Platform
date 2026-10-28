"""Рендер PDF через WeasyPrint: изолированные шрифты, безопасный fetcher, статистика страниц,
«Стр. N из M» только при M > 1.

Импорт этого модуля требует системных библиотек WeasyPrint (pango, harfbuzz): в сервисе — образ потребителя,
в тестах — docker/test.Dockerfile. Остальной пакет (схема, HTML, DOCX, форматтеры) работает без них.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from weasyprint import HTML
from weasyprint.formatting_structure import boxes
from weasyprint.text.ffi import ffi, fontconfig, gobject, pangoft2
from weasyprint.text.fonts import FontConfiguration
from weasyprint.urls import URLFetcher, URLFetcherResponse

from .contracts import Catalog, load_catalog, validate_body
from .css import PageSetup, page_setup
from .errors import ContractsNotFoundError
from .fetcher import ResourcePolicy
from .fonts import missing_glyphs
from .html import HtmlOptions, build_html
from .model import (
    Density,
    DocumentMeta,
    Lang,
    Layout,
    Letterhead,
    Orientation,
    PageStats,
    RenderResult,
    Tuning,
    Value,
)
from .resolve import Node, plain_text, resolve

_FC_DECLARED = False


def _declare_fontconfig() -> None:
    """FcConfigCreate нет в объявлениях cffi WeasyPrint — добавляем один раз (ABI-режим разрешает это после dlopen)."""
    global _FC_DECLARED
    if not _FC_DECLARED:
        ffi.cdef("FcConfig * FcConfigCreate (void);")
        _FC_DECLARED = True


class IsolatedFontConfiguration(FontConfiguration):  # type: ignore[misc]
    """Конфигурация fontconfig без системных шрифтов: документ видит только @font-face пакета.

    WeasyPrint строит конфигурацию из системной (FcInitLoadConfigAndFonts) — DejaVu, PT Sans и всё, что стоит в образе,
    участвовало бы в подборе запасного шрифта, и число страниц зависело бы от образа. Здесь карта шрифтов Pango получает
    пустую конфигурацию (FcConfigCreate); @font-face WeasyPrint добавляет в неё вшитые файлы (add_font_face). Тело
    __init__ повторяет WeasyPrint 69 (внутренние имена _config, font_map, _folder проверяют тесты при смене версии).
    """

    def __init__(self) -> None:
        _declare_fontconfig()
        self._config = ffi.gc(fontconfig.FcConfigCreate(), fontconfig.FcConfigDestroy)
        self.font_map = ffi.gc(pangoft2.pango_ft2_font_map_new(), gobject.g_object_unref)
        pangoft2.pango_fc_font_map_set_config(ffi.cast("PangoFcFontMap *", self.font_map), self._config)
        # Тот же учёт ссылок, что в WeasyPrint: ссылку держит карта шрифтов.
        fontconfig.FcConfigDestroy(self._config)
        self._folder = None
        self.strut_layouts: dict[Any, Any] = {}
        self.font_features: dict[Any, Any] = {}


class SafeURLFetcher(URLFetcher):  # type: ignore[misc]
    """URL fetcher WeasyPrint по белому списку `ResourcePolicy`: без сети и без файловой системы."""

    def __init__(self, policy: ResourcePolicy) -> None:
        super().__init__(allowed_protocols=())
        self.policy = policy

    def fetch(self, url: str, headers: Mapping[str, str] | None = None) -> Any:
        resource = self.policy.resolve(url)
        if resource is None:
            raise ValueError(f"rt_docs: resource is not allowed: {url[:80]}")
        return URLFetcherResponse(url, resource.data, {"Content-Type": resource.mime})


def page_stats(document: Any) -> PageStats:
    """Число страниц и заполненность последней: низ самого нижнего бокса потока / высота области текста."""
    pages = document.pages
    page_box = pages[-1]._page_box
    top = page_box.content_box_y()
    height = page_box.height
    root = page_box.children[0]
    bottom = top
    for box in root.descendants():
        if box is root or getattr(box, "element_tag", None) in ("html", "body", "main"):
            continue
        if isinstance(box, boxes.MarginBox) or box.style["position"] not in ("static", "relative"):
            continue
        if isinstance(box, boxes.BlockBox | boxes.TableBox) and box.children:
            continue  # контейнер: считаем по содержимому (его нижнее поле не текст)
        bottom = max(bottom, box.position_y + box.margin_top + box.border_height())
    fill = max(0.0, min(1.0, (bottom - top) / height)) if height else 0.0
    return PageStats(pages=len(pages), last_page_fill=round(fill, 4))


@dataclass(frozen=True)
class Prepared:
    """Тело после проверки и подстановки — общее для нескольких рендеров «Подогнать»."""

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


def prepare(
    body: Mapping[str, Any],
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
    validate_body(body, contracts_dir)
    if catalog is None:
        try:
            catalog = load_catalog(contracts_dir)
        except ContractsNotFoundError:
            catalog = Catalog.empty()
    resolved = resolve(body, values=values or {}, blocks=blocks or {}, catalog=catalog)
    page: Mapping[str, Any] = body.get("page") or {}
    tuning_raw: Mapping[str, Any] = page.get("tuning") or {}
    tuning = Tuning(
        line_height=tuning_raw.get("lineHeight"),
        margin_delta_mm=int(tuning_raw.get("marginDeltaMm", 0)),
        lead_mm=int(tuning_raw.get("leadMm", 0)),
    )
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
        lang=body["lang"],
        letterhead=letterhead,
        meta=meta,
        layout=layout,
        orientation=Orientation(page.get("orientation", "portrait")),
        density=Density(page["density"]) if page.get("density") else None,
        tuning=tuning,
        warnings=tuple(warnings),
        highlight_missing=highlight_missing,
    )


def _render(prepared: Prepared, setup: PageSetup, *, page_numbers: bool) -> tuple[Any, ResourcePolicy]:
    policy = ResourcePolicy(logo=prepared.letterhead.logo)
    html = build_html(
        prepared.content,
        lang=prepared.lang,
        letterhead=prepared.letterhead,
        meta=prepared.meta,
        setup=setup,
        options=HtmlOptions(page_numbers=page_numbers, highlight_missing=prepared.highlight_missing),
    )
    document = HTML(string=html, base_url=None, url_fetcher=SafeURLFetcher(policy)).render(
        font_config=IsolatedFontConfiguration()
    )
    return document, policy


def render_prepared(prepared: Prepared, tuning: Tuning | None = None) -> RenderResult:
    """Рендер подготовленного тела с подстройкой `tuning` (по умолчанию — из `page.tuning` тела)."""
    effective = tuning if tuning is not None else prepared.tuning
    setup = page_setup(prepared.layout, prepared.orientation, prepared.density, effective)
    document, policy = _render(prepared, setup, page_numbers=False)
    stats = page_stats(document)
    if stats.pages > 1:
        # Колонтитулы не влияют на поток: второй проход с «Стр. N из M» даёт ту же разбивку.
        document, policy = _render(prepared, setup, page_numbers=True)
        stats = page_stats(document)
    pdf = document.write_pdf()
    used = replace(effective, density=setup.density, line_height=setup.line_height)
    return RenderResult(
        pdf=pdf,
        stats=stats,
        tuning=used,
        warnings=prepared.warnings,
        blocked_urls=tuple(dict.fromkeys(policy.blocked)),
    )


def render_pdf(
    body: Mapping[str, Any],
    *,
    letterhead: Letterhead,
    layout: Layout,
    meta: DocumentMeta | None = None,
    values: Mapping[str, Value] | None = None,
    blocks: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    tuning: Tuning | None = None,
    catalog: Catalog | None = None,
    highlight_missing: bool = True,
    contracts_dir: str | None = None,
) -> RenderResult:
    """Тело документа (контракт documents/body.schema.json) → PDF на бланке со статистикой страниц."""
    prepared = prepare(
        body,
        letterhead=letterhead,
        layout=layout,
        meta=meta,
        values=values,
        blocks=blocks,
        catalog=catalog,
        highlight_missing=highlight_missing,
        contracts_dir=contracts_dir,
    )
    return render_prepared(prepared, tuning)


def render_html_unsafe_for_tests(html: str) -> tuple[bytes, tuple[str, ...]]:
    """Рендер произвольного HTML с тем же fetcher'ом и шрифтами — только для тестов защиты (file://, http://)."""
    policy = ResourcePolicy()
    document = HTML(string=html, base_url=None, url_fetcher=SafeURLFetcher(policy)).render(
        font_config=IsolatedFontConfiguration()
    )
    return document.write_pdf(), tuple(policy.blocked)
