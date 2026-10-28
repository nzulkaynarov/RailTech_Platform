"""Стили документа: CSS Paged Media для WeasyPrint — макеты бланка, плотность, колонтитулы, правила разрывов.

База — `apps/erp/backend/crm/templates/crm/_document_base.html` (поля ГОСТ Р 7.0.97, подвал running element,
повтор шапки таблицы, строки без разрыва), плюс правила исследования шаблонов §3.2. Все числа и цвет генерируются
из проверенных значений (Letterhead.accent — #rrggbb, плотность — перечисление); пользовательского CSS нет.
"""

from __future__ import annotations

from dataclasses import dataclass

from .labels import PAGE_OF
from .model import Density, Lang, Layout, Letterhead, Orientation, Tuning

#: Плотность: кегль основного текста (pt) и межстрочный (исследование §3.2).
DENSITY: dict[Density, tuple[float, float]] = {
    Density.COMPACT: (9.5, 1.35),
    Density.NORMAL: (11.0, 1.45),
    Density.SPACIOUS: (12.0, 1.5),
}
DEFAULT_DENSITY: dict[Layout, Density] = {
    Layout.LETTER: Density.NORMAL,
    Layout.INTERNAL: Density.NORMAL,
    Layout.COMMERCIAL: Density.COMPACT,
}
#: Поля страницы, мм: верх, право, низ, лево (ГОСТ Р 7.0.97: левое ≥ 20, правое ≥ 10, верх и низ ≥ 20).
MARGINS: dict[Orientation, tuple[int, int, int, int]] = {
    Orientation.PORTRAIT: (20, 15, 20, 20),
    Orientation.LANDSCAPE: (15, 20, 15, 20),
}
FONT_FILES: dict[str, tuple[tuple[str, int, str], ...]] = {
    "sans": (
        ("NotoSans-Regular.ttf", 400, "normal"),
        ("NotoSans-Bold.ttf", 700, "normal"),
        ("NotoSans-Italic.ttf", 400, "italic"),
        ("NotoSans-BoldItalic.ttf", 700, "italic"),
    ),
    "serif": (
        ("NotoSerif-Regular.ttf", 400, "normal"),
        ("NotoSerif-Bold.ttf", 700, "normal"),
        ("NotoSerif-Italic.ttf", 400, "italic"),
        ("NotoSerif-BoldItalic.ttf", 700, "italic"),
    ),
}
FAMILY = {"sans": "RT Doc Sans", "serif": "RT Doc Serif"}


@dataclass(frozen=True)
class PageSetup:
    """Итоговые параметры вёрстки одного рендера."""

    layout: Layout
    orientation: Orientation
    density: Density
    font_pt: float
    line_height: float
    margins_mm: tuple[int, int, int, int]
    lead_mm: int


def page_setup(layout: Layout, orientation: Orientation, density: Density | None, tuning: Tuning) -> PageSetup:
    chosen = tuning.density or density or DEFAULT_DENSITY[layout]
    font_pt, line_height = DENSITY[chosen]
    top, right, bottom, left = MARGINS[orientation]
    delta = tuning.margin_delta_mm
    return PageSetup(
        layout=layout,
        orientation=orientation,
        density=chosen,
        font_pt=font_pt,
        line_height=tuning.line_height or line_height,
        margins_mm=(top + delta, right, bottom + delta, left),
        lead_mm=tuning.lead_mm,
    )


def _font_faces() -> str:
    rules = []
    for key, files in FONT_FILES.items():
        for name, weight, style in files:
            rules.append(
                f'@font-face {{ font-family: "{FAMILY[key]}"; src: url("rtdocs:fonts/{name}"); '
                f"font-weight: {weight}; font-style: {style}; }}"
            )
    return "\n".join(rules)


def stylesheet(setup: PageSetup, letterhead: Letterhead, lang: Lang, *, page_numbers: bool) -> str:
    top, right, bottom, left = setup.margins_mm
    size = "A4 landscape" if setup.orientation is Orientation.LANDSCAPE else "A4"
    family = FAMILY[letterhead.font]
    accent = letterhead.accent
    before, middle, after = PAGE_OF[lang]
    numbers = (
        f'content: "{before}" counter(page) "{middle}" counter(pages) "{after}";' if page_numbers else "content: none;"
    )
    bottom_left = {
        Layout.LETTER: "content: element(rtexec);",
        Layout.INTERNAL: "content: element(rtexec);",
        Layout.COMMERCIAL: "content: element(rtfooter);",
    }[setup.layout]
    return f"""
{_font_faces()}
@page {{
  size: {size};
  margin: {top}mm {right}mm {bottom}mm {left}mm;
  @bottom-left {{ {bottom_left} vertical-align: top; padding-top: 3mm; }}
  @bottom-right {{ {numbers} vertical-align: top; padding-top: 3mm; font-family: "{family}"; font-size: 7.5pt;
                   color: #7a828f; white-space: nowrap; }}
  @top-right {{ content: string(rtdocref); vertical-align: bottom; padding-bottom: 3mm; font-family: "{family}";
                font-size: 7.5pt; color: #7a828f; }}
}}
@page :first {{ @top-right {{ content: none; }} }}
{BASE_CSS}
html {{ font-family: "{family}"; font-size: {setup.font_pt:g}pt; line-height: {setup.line_height:g}; }}
.rt-accent, h1.rt-title, .rt-company, table.rt-grid th {{ color: {accent}; }}
.rt-rule {{ border-top: 1.5pt solid {accent}; }}
table.rt-grid th {{ border-bottom: 1.2pt solid {accent}; }}
table.rt-totals tr.rt-em td {{ border-top: 1pt solid {accent}; color: {accent}; }}
main.rt-body {{ padding-top: {setup.lead_mm}mm; }}
"""


BASE_CSS = """
* { box-sizing: border-box; }
html { color: #20242b; font-variant-numeric: tabular-nums; }
body { margin: 0; }
p { margin: 0 0 0.55em; orphans: 2; widows: 2; }
p:empty::before { content: "\\00a0"; }
h1, h2, h3 { break-after: avoid; break-inside: avoid; line-height: 1.25; margin: 0.9em 0 0.45em; font-weight: 700; }
h1 { font-size: 1.4em; }
h2 { font-size: 1.18em; }
h3 { font-size: 1.04em; }
h1.rt-title { margin: 0 0 0.8em; }
ul, ol { margin: 0 0 0.55em; padding-left: 1.5em; }
li { margin: 0 0 0.15em; }
li > p { margin: 0; }
a { color: inherit; text-decoration: underline; }
.rt-al-left { text-align: left; }
.rt-al-center { text-align: center; }
.rt-al-right { text-align: right; }
.rt-al-justify { text-align: justify; }
.rt-pb { break-before: page; height: 0; margin: 0; }

/* Таблицы: повтор шапки на каждой странице, строка не рвётся, ширины колонок из тела (table-layout: fixed). */
table.rt-table { width: 100%; border-collapse: collapse; table-layout: fixed; margin: 0.3em 0 0.8em;
                 font-size: 0.92em; }
table.rt-table thead { display: table-header-group; }
table.rt-table tr { break-inside: avoid; }
table.rt-table td, table.rt-table th { vertical-align: top; text-align: left; hyphens: auto;
                                       overflow-wrap: break-word; }
table.rt-table td p, table.rt-table th p { margin: 0; }
table.rt-grid th { font-weight: 700; padding: 3pt 5pt; border-top: 0.5pt solid #d7dbe3; font-size: 0.92em; }
table.rt-grid td { padding: 3pt 5pt; border-bottom: 0.5pt solid #e1e5ec; }
table.rt-plain td, table.rt-plain th { padding: 1pt 10pt 1pt 0; }
table.rt-totals { width: 55%; margin-left: 45%; margin-top: 0; }
table.rt-totals td { padding: 2pt 5pt; }
table.rt-totals tr.rt-em td { font-weight: 700; }
table.rt-grid tr.rt-em td { font-weight: 700; }
table.rt-table .rt-num { text-align: right; white-space: nowrap; hyphens: manual; }
table.rt-table .rt-al-center { text-align: center; }
table.rt-table .rt-al-right { text-align: right; }

/* Блоки с замком; keep — не отрывать от предыдущего (итоги — от таблицы позиций). */
.rt-block { margin: 0; }
.rt-keep { break-before: avoid; }
.rt-block-missing { border: 0.75pt dashed #c9a227; color: #7a5d00; padding: 5pt 7pt; margin: 0.4em 0 0.8em; }
.rt-var-missing { background: #fff1b8; color: #6b5300; }

/* Подписи: не рвутся и не уходят на новую страницу одни — только вместе с предыдущим абзацем. */
table.rt-signature { width: 100%; border-collapse: collapse; margin: 1.6em 0 0; table-layout: fixed;
                     break-inside: avoid; break-before: avoid; }
table.rt-signature td { vertical-align: bottom; width: 50%; padding: 0 16pt 0 0; }
table.rt-signature td + td { padding: 0 0 0 16pt; }
.rt-sign-role { font-weight: 700; margin-bottom: 0.2em; }
.rt-sign-line { border-bottom: 0.75pt solid #6b7280; height: 2.2em; margin-bottom: 1pt; }
.rt-sign-caption { font-size: 0.72em; color: #7a828f; }
.rt-stamp { font-size: 0.8em; color: #7a828f; margin-top: 0.35em; }

/* Шапка бланка (только первая страница — она в потоке) и реквизиты. */
table.rt-brand { width: 100%; border-collapse: collapse; margin-bottom: 6pt; }
table.rt-brand td { vertical-align: top; padding: 0; }
table.rt-brand td.rt-logo { width: 1%; padding-right: 10pt; vertical-align: middle; }
td.rt-logo img { max-height: 46pt; max-width: 120pt; }
.rt-company { font-size: 1.35em; font-weight: 700; line-height: 1.2; }
.rt-req { font-size: 0.74em; color: #5a6270; line-height: 1.35; margin-top: 2pt; }
table.rt-brand td.rt-docid { text-align: right; font-size: 0.85em; color: #5a6270; white-space: nowrap;
                             padding-left: 12pt; }
.rt-docno { font-weight: 700; font-size: 1.15em; string-set: rtdocref content(); }
.rt-rule { margin: 0 0 12pt; height: 0; }
table.rt-letter-meta { width: 100%; border-collapse: collapse; margin: 0 0 14pt; font-size: 0.92em; }
table.rt-letter-meta td { vertical-align: top; padding: 0; width: 50%; }
td.rt-addressee { padding-left: 18pt; }
.rt-int-head { font-size: 0.85em; color: #5a6270; margin-bottom: 10pt; }
.rt-int-head .rt-company { font-size: 1.1em; }

/* Колонтитулы: подвал бланка на каждой странице (коммерческий), «Исполнитель» — на последней (письмо). */
.rt-footer { position: running(rtfooter); font-size: 6.5pt; color: #8a909b; line-height: 1.35;
             border-top: 0.5pt solid #e1e5ec; padding-top: 2pt; width: 140mm; }
.rt-executor { position: running(rtexec); font-size: 7pt; color: #5a6270; line-height: 1.3; width: 120mm; }
"""
