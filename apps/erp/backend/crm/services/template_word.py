"""ШАБЛ-1: текст шаблона документа в Word и обратно.

Зачем. Шаблон — это HTML с `{{подстановками}}`, а читать и править его должны люди, которые HTML не знают: юрист, закупщик,
руководитель. Поэтому шаблон скачивается как Word («как его читают люди»), правится там и загружается обратно; система
сначала показывает, что изменилось, и только после «Принять» сохраняет.

Как устроено.

* Между HTML и Word стоит одно промежуточное представление (`Block`): заголовок, абзац, список, таблица; в абзаце —
  куски текста с жирным, курсивом и подчёркиванием. HTML → блоки → Word и Word → блоки → HTML идут через него, поэтому
  «скачал и загрузил без правок» даёт тот же текст, а сравнение с текущим шаблоном честное: обе стороны приведены к одному виду.
* Подстановка в Word печатается подписанным полем: `[Название контрагента {{counterparty.name}}]`, с выделением цветом.
  Подпись только для чтения: при загрузке из квадратных скобок остаётся код `{{counterparty.name}}`, что бы ни сделали с подписью.
  Блок документа (`{{doc.signatures}}`) — то же самое, отдельной серой строкой.
* Всё, чего нет в списке (рисунки, цвета, шрифты, колонтитулы, комментарии, макросы), при загрузке отбрасывается; HTML после
  этого проходит ту же очистку, что и при сохранении (`sanitize_template_html`).
* Чужой файл — недоверенный: архив проверяется теми же проверками, что и редакция контрагента в договоре
  (`contract_compare.check_archive`: число частей, фактический размер после распаковки, степень сжатия), затем размер файла
  и число абзацев.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from io import BytesIO
from typing import Optional

from . import contract_compare
from .document_placeholders import PLACEHOLDER_CATALOG, PLACEHOLDER_RE, extract_placeholders, sanitize_template_html

#: Файл больше — отказ до разбора; шаблон на десятки страниц — это уже несколько мегабайт только с рисунками.
MAX_WORD_BYTES = 5 * 1024 * 1024
#: Абзацев в одном файле (договор на сто страниц — несколько сотен).
MAX_BLOCKS = contract_compare.MAX_PARAGRAPHS
LANGUAGES = ("ru", "uz", "en")
LANGUAGE_FIELD = {"ru": "body_html", "uz": "body_html_uz", "en": "body_html_en"}

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class WordError(ValueError):
    """Файл нельзя принять; `code` — код отказа API (`WORD_*`)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── Промежуточное представление ───────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Run:
    text: str  # «\n» — перенос строки внутри абзаца
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass
class Para:
    runs: list[Run]
    level: int = 0  # 0 — обычный абзац, 1..4 — заголовок

    def text(self) -> str:
        return _clean("".join(r.text for r in self.runs))


@dataclass
class ListBlock:
    ordered: bool
    items: list[list[Run]]


@dataclass
class TableBlock:
    rows: list[list[list[Para]]]  # строка → ячейка → абзацы


Block = Para | ListBlock | TableBlock


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _squash(runs: list[Run]) -> list[Run]:
    """Склеивает соседние куски с одинаковым оформлением, схлопывает пробелы, срезает края абзаца."""
    out: list[Run] = []
    for run in runs:
        text = run.text
        if not text:
            continue
        if out and (out[-1].bold, out[-1].italic, out[-1].underline) == (run.bold, run.italic, run.underline):
            out[-1] = Run(out[-1].text + text, run.bold, run.italic, run.underline)
        else:
            out.append(run)
    # пробелы и переносы: пробелы подряд — один, пробелы вокруг переноса убираются
    joined = []
    for run in out:
        text = re.sub(r"[ \t\r\f\v\xa0]+", " ", run.text)
        text = re.sub(r" ?\n ?", "\n", text)
        joined.append(Run(text, run.bold, run.italic, run.underline))
    # края абзаца
    while joined and not joined[0].text.strip(" \n"):
        joined.pop(0)
    while joined and not joined[-1].text.strip(" \n"):
        joined.pop()
    if joined:
        first, last = joined[0], joined[-1]
        joined[0] = Run(first.text.lstrip(" \n"), first.bold, first.italic, first.underline)
        last = joined[-1]
        joined[-1] = Run(last.text.rstrip(" \n"), last.bold, last.italic, last.underline)
    # соседи после подрезки снова склеиваем, пробелы на стыке — один
    merged: list[Run] = []
    for run in joined:
        if merged and (merged[-1].bold, merged[-1].italic, merged[-1].underline) == (
            run.bold,
            run.italic,
            run.underline,
        ):
            text = merged[-1].text + run.text
            merged[-1] = Run(re.sub(r" {2,}", " ", text), run.bold, run.italic, run.underline)
        else:
            if merged and merged[-1].text.endswith(" ") and run.text.startswith(" "):
                run = Run(run.text[1:], run.bold, run.italic, run.underline)
            merged.append(run)
    return [r for r in merged if r.text]


# ── HTML → блоки ──────────────────────────────────────────────────────────────────────────────────────────────────

_VOID = {"br", "hr", "img"}
_BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th", "hr"}
_HEADING = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
_DROPPED = {"script", "style", "iframe", "object", "embed"}


@dataclass
class _Node:
    tag: str
    children: list = field(default_factory=list)  # _Node | str


class _Dom(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]
        self.drop = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROPPED:
            self.drop += 1
            return
        if self.drop:
            return
        node = _Node(tag)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if tag in _DROPPED or self.drop:
            return
        self.stack[-1].children.append(_Node(tag))

    def handle_endtag(self, tag):
        if tag in _DROPPED:
            self.drop = max(0, self.drop - 1)
            return
        if self.drop or tag in _VOID:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not self.drop:
            self.stack[-1].children.append(data)


def _inline_runs(node: _Node, fmt: tuple[bool, bool, bool] = (False, False, False)) -> list[Run]:
    bold, italic, underline = fmt
    runs: list[Run] = []
    for child in node.children:
        if isinstance(child, str):
            runs.append(Run(child, bold, italic, underline))
            continue
        tag = child.tag
        if tag == "br":
            runs.append(Run("\n", bold, italic, underline))
        elif tag in ("strong", "b"):
            runs += _inline_runs(child, (True, italic, underline))
        elif tag in ("em", "i"):
            runs += _inline_runs(child, (bold, True, underline))
        elif tag == "u":
            runs += _inline_runs(child, (bold, italic, True))
        elif tag in ("img", "hr"):
            continue
        else:  # span, a и неожиданные: только содержимое; вложенные блоки внутри абзаца читаются подряд
            runs += _inline_runs(child, fmt)
            if tag in _BLOCK:
                runs.append(Run(" ", bold, italic, underline))
    return runs


def _has_block(node: _Node) -> bool:
    return any(isinstance(c, _Node) and (c.tag in _BLOCK) for c in node.children)


def _cell_paragraphs(node: _Node) -> list[Para]:
    """Содержимое ячейки: абзацы; списки и вложенные таблицы внутри ячейки читаются плоскими абзацами."""
    paras: list[Para] = []
    for block in _blocks(node.children):
        if isinstance(block, Para):
            paras.append(block)
        elif isinstance(block, ListBlock):
            paras += [Para(item) for item in block.items]
        else:
            for row in block.rows:
                for cell in row:
                    paras += cell
    return [p for p in paras if p.runs]


def _blocks(children: list) -> list[Block]:
    out: list[Block] = []
    pending: list[Run] = []

    def flush() -> None:
        runs = _squash(pending)
        pending.clear()
        if runs:
            out.append(Para(runs))

    for child in children:
        if isinstance(child, str):
            pending.append(Run(child))
            continue
        tag = child.tag
        if tag in _HEADING:
            flush()
            runs = _squash(_inline_runs(child))
            if runs:
                out.append(Para(runs, _HEADING[tag]))
        elif tag in ("p", "div", "li") and not _has_block(child):
            flush()
            runs = _squash(_inline_runs(child))
            if runs:
                out.append(Para(runs))
        elif tag in ("ul", "ol"):
            flush()
            items: list[list[Run]] = []

            def collect(lst: _Node) -> None:
                for li in lst.children:
                    if not isinstance(li, _Node):
                        continue
                    if li.tag in ("ul", "ol"):
                        collect(li)
                        continue
                    own = _Node("li", [c for c in li.children if not (isinstance(c, _Node) and c.tag in ("ul", "ol"))])
                    runs = _squash(_inline_runs(own))
                    if runs:
                        items.append(runs)
                    for sub in li.children:
                        if isinstance(sub, _Node) and sub.tag in ("ul", "ol"):
                            collect(sub)

            collect(child)
            if items:
                out.append(ListBlock(tag == "ol", items))
        elif tag == "table":
            flush()
            rows: list[list[list[Para]]] = []

            def collect_rows(node: _Node) -> None:
                for part in node.children:
                    if not isinstance(part, _Node):
                        continue
                    if part.tag == "tr":
                        cells = [
                            _cell_paragraphs(c) for c in part.children if isinstance(c, _Node) and c.tag in ("td", "th")
                        ]
                        if cells:
                            rows.append(cells)
                    elif part.tag in ("thead", "tbody", "tfoot"):
                        collect_rows(part)

            collect_rows(child)
            if rows:
                out.append(TableBlock(rows))
        elif tag in _BLOCK or tag in ("span", "a", "section", "article"):
            if tag in _BLOCK and tag not in ("span", "a"):
                flush()
            if _has_block(child) or tag in ("div", "section", "article", "li", "thead", "tbody", "tr", "td", "th", "p"):
                out += _blocks(child.children)
            else:
                pending += _inline_runs(child)
        elif tag == "br":
            pending.append(Run("\n"))
        elif tag in ("img", "hr"):
            flush() if tag == "hr" else None
        else:  # strong, em, u и прочее встроенное
            pending += _inline_runs(_Node("x", [child]))
    flush()
    return out


def html_to_blocks(html: str) -> list[Block]:
    dom = _Dom()
    dom.feed(html or "")
    dom.close()
    return _blocks(dom.root.children)


# ── блоки → HTML ──────────────────────────────────────────────────────────────────────────────────────────────────


def _runs_html(runs: list[Run]) -> str:
    out = []
    for run in runs:
        piece = "<br />".join(escape(part, quote=False) for part in run.text.split("\n"))
        if run.underline:
            piece = f"<u>{piece}</u>"
        if run.italic:
            piece = f"<em>{piece}</em>"
        if run.bold:
            piece = f"<strong>{piece}</strong>"
        out.append(piece)
    return "".join(out)


def blocks_to_html(blocks: list[Block]) -> str:
    out: list[str] = []
    for block in blocks:
        if isinstance(block, Para):
            tag = f"h{block.level}" if block.level else "p"
            out.append(f"<{tag}>{_runs_html(block.runs)}</{tag}>")
        elif isinstance(block, ListBlock):
            tag = "ol" if block.ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{_runs_html(item)}</li>" for item in block.items) + f"</{tag}>")
        else:
            rows = []
            for row in block.rows:
                cells = [
                    "<td>"
                    + (
                        _runs_html(cell[0].runs)
                        if len(cell) == 1
                        else "".join(f"<p>{_runs_html(p.runs)}</p>" for p in cell)
                    )
                    + "</td>"
                    for cell in row
                ]
                rows.append("<tr>" + "".join(cells) + "</tr>")
            out.append("<table><tbody>" + "".join(rows) + "</tbody></table>")
    return "\n".join(out)


def canonical_html(html: str) -> str:
    """Текст шаблона в том виде, в каком его вернёт загрузка из Word без правок."""
    return sanitize_template_html(blocks_to_html(html_to_blocks(html)))


def paragraphs_of(blocks: list[Block]) -> list[str]:
    """Абзацы для сравнения: строка таблицы — одним абзацем через « | » (как в сравнении редакции договора)."""
    out: list[str] = []
    for block in blocks:
        if isinstance(block, Para):
            if block.text():
                out.append(block.text())
        elif isinstance(block, ListBlock):
            out += [t for t in (_clean("".join(r.text for r in item)) for item in block.items) if t]
        else:
            for row in block.rows:
                cells = [_clean(" ".join(p.text() for p in cell)) for cell in row]
                line = " | ".join(c for c in cells if c)
                if line:
                    out.append(line)
    return out


# ── подстановки: как они выглядят в Word ──────────────────────────────────────────────────────────────────────────

#: Подпись поля в скобках перед кодом: `[Название контрагента {{counterparty.name}}]`.
FIELD_RE = re.compile(r"\[[^\[\]{}]*?\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}\s*\]")


def known_codes() -> set[str]:
    """Подстановки, которые система умеет заполнять: данные, реквизиты компании, блоки, формулировки, значения документа."""
    from .document_blocks import DOCUMENT_BLOCKS, DOCUMENT_SCALARS, DOCUMENT_WORDING_TOKENS
    from .document_placeholders import RESOLVERS

    return set(RESOLVERS) | set(DOCUMENT_BLOCKS) | set(DOCUMENT_WORDING_TOKENS) | set(DOCUMENT_SCALARS)


def unknown_placeholders(*bodies: str) -> list[str]:
    """Коды подстановок текстов, которых система не знает, в порядке появления, без повторов."""
    known = known_codes()
    seen: list[str] = []
    for body in bodies:
        for code in extract_placeholders(body or ""):
            if code not in known and code not in seen:
                seen.append(code)
    return seen


def _block_codes() -> set[str]:
    from .document_blocks import DOCUMENT_BLOCKS, DOCUMENT_WORDING_TOKENS

    return set(DOCUMENT_BLOCKS) | set(DOCUMENT_WORDING_TOKENS)


def field_label(code: str, language: str) -> str:
    """Подпись поля в Word; только русская (каталог один), на других языках — один код без подписи."""
    if language != "ru":
        return ""
    return PLACEHOLDER_CATALOG.get(code, "")


# ── блоки → DOCX ──────────────────────────────────────────────────────────────────────────────────────────────────

_HINTS = {
    "ru": "Проект шаблона «{name}», ред. {edition}. Правьте текст как обычно. Поля в квадратных скобках — подстановки данных: "
    "подпись можно не трогать, код в фигурных скобках менять нельзя. Верхний и нижний колонтитулы при загрузке не читаются.",
    "uz": "«{name}» shablon loyihasi, {edition}-tahrir. Matnni odatdagidek tahrirlang. Kvadrat qavsdagi maydonlar — "
    "ma’lumot o‘rniga qo‘yiladigan joylar: nomiga tegmasa ham bo‘ladi, jingalak qavsdagi kodni o‘zgartirib bo‘lmaydi. "
    "Yuqori va pastki kolontitullar yuklashda o‘qilmaydi.",
    "en": "Template draft «{name}», edition {edition}. Edit the text as usual. Fields in square brackets are data "
    "placeholders: the label may be left alone, the code in curly braces must not be changed. Headers and footers are not read "
    "when the file is uploaded.",
}
_PLACEHOLDER_SPLIT = re.compile(r"(\{\{\s*[a-zA-Z0-9_.]+\s*\}\})")


def _add_runs(paragraph, runs: list[Run], language: str) -> None:
    from docx.enum.text import WD_COLOR_INDEX

    blocks = _block_codes()
    for run in runs:
        for part in _PLACEHOLDER_SPLIT.split(run.text):
            if not part:
                continue
            found = PLACEHOLDER_RE.fullmatch(part)
            if found:
                code = found.group(1)
                label = field_label(code, language)
                shown = f"[{label} {{{{{code}}}}}]" if label else f"[{{{{{code}}}}}]"
                item = paragraph.add_run(shown)
                item.bold = run.bold
                item.italic = run.italic
                item.underline = run.underline
                item.font.highlight_color = WD_COLOR_INDEX.GRAY_25 if code in blocks else WD_COLOR_INDEX.YELLOW
                continue
            for k, line in enumerate(part.split("\n")):
                if k:
                    paragraph.add_run().add_break()
                if line:
                    item = paragraph.add_run(line)
                    item.bold = run.bold
                    item.italic = run.italic
                    item.underline = run.underline


def _restart_numbering(doc, paragraphs: list) -> None:
    """Каждому нумерованному списку — своя нумерация с единицы (иначе второй список продолжает счёт первого)."""
    from docx.oxml.ns import qn

    numbering = doc.part.numbering_part.numbering_definitions._numbering
    style = doc.styles["List Number"]
    style_num = style.element.pPr.numPr.numId.val
    abstract = None
    for num in numbering.findall(qn("w:num")):
        if int(num.get(qn("w:numId"))) == style_num:
            abstract = int(num.find(qn("w:abstractNumId")).get(qn("w:val")))
    if abstract is None:
        return
    num = numbering.add_num(abstract)
    override = num.add_lvlOverride(ilvl=0)
    override.add_startOverride(1)
    for paragraph in paragraphs:
        paragraph._p.get_or_add_pPr().get_or_add_numPr().get_or_add_numId().val = num.numId
        paragraph._p.get_or_add_pPr().get_or_add_numPr().get_or_add_ilvl().val = 0


def blocks_to_docx(
    blocks: list[Block], *, name: str, edition: int, language: str, brand: Optional[dict] = None
) -> bytes:
    """Word: бланк компании в верхнем колонтитуле (при загрузке не читается), текст шаблона, подстановки подписанными полями."""
    from docx import Document
    from docx.enum.text import WD_COLOR_INDEX
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    for section in doc.sections:
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.left_margin = section.right_margin = Cm(2.2)
        section.top_margin, section.bottom_margin = Cm(2.2), Cm(2)
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(10.5)
    for level in range(1, 5):
        style = doc.styles[f"Heading {level}"]
        style.font.name = "Arial"
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.font.size = Pt({1: 16, 2: 13, 3: 11.5, 4: 10.5}[level])
    doc.core_properties.title = f"{name}, ред. {edition}"
    doc.core_properties.author = ""

    brand = brand or {}
    section = doc.sections[0]
    head = section.header.paragraphs[0]
    title = head.add_run(str(brand.get("seller_name") or ""))
    title.bold = True
    title.font.size = Pt(12)
    details = " · ".join(str(brand.get(key)) for key in ("inn", "address", "phone", "email") if brand.get(key))
    if details:
        line = section.header.add_paragraph()
        piece = line.add_run(details)
        piece.font.size = Pt(8.5)
        piece.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
    hint = section.header.add_paragraph()
    note = hint.add_run(_HINTS.get(language, _HINTS["ru"]).format(name=name, edition=edition))
    note.italic = True
    note.font.size = Pt(8)
    note.font.highlight_color = WD_COLOR_INDEX.TURQUOISE
    if brand.get("footer_text"):
        foot = section.footer.paragraphs[0]
        run = foot.add_run(str(brand["footer_text"]))
        run.font.size = Pt(8.5)

    for block in blocks:
        if isinstance(block, Para):
            paragraph = doc.add_heading("", level=block.level) if block.level else doc.add_paragraph()
            _add_runs(paragraph, block.runs, language)
        elif isinstance(block, ListBlock):
            made = []
            for item in block.items:
                paragraph = doc.add_paragraph(style="List Number" if block.ordered else "List Bullet")
                _add_runs(paragraph, item, language)
                made.append(paragraph)
            if block.ordered:
                _restart_numbering(doc, made)
        else:
            width = max(len(row) for row in block.rows)
            table = doc.add_table(rows=len(block.rows), cols=width)
            table.style = "Table Grid"
            for r, row in enumerate(block.rows):
                for c, cell_paras in enumerate(row):
                    cell = table.cell(r, c)
                    first = True
                    for para in cell_paras or [Para([])]:
                        paragraph = cell.paragraphs[0] if first else cell.add_paragraph()
                        first = False
                        _add_runs(paragraph, para.runs, language)
            doc.add_paragraph()
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def template_docx(template, language: str, *, brand: Optional[dict] = None) -> bytes:
    body = template_body(template, language) or template.body_html
    return blocks_to_docx(
        html_to_blocks(body), name=template.name, edition=template.edition, language=language, brand=brand
    )


def template_body(template, language: str) -> str:
    return getattr(template, LANGUAGE_FIELD[language]) or ""


def download_name(template, language: str, extension: str = "docx") -> str:
    """«<Название>, ред. <N> — проект.docx»: одно правило имени и для Word, и для PDF; язык, кроме русского, — в названии."""
    base = (
        re.sub(r"\s+", " ", re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", template.name or "")).strip()[:120].strip()
        or "Шаблон"
    )
    if language != "ru":
        base = f"{base} ({language.upper()})"
    return f"{base}, ред. {template.edition} — проект.{extension}"


# ── DOCX → блоки ──────────────────────────────────────────────────────────────────────────────────────────────────


def _runs_of(paragraph, *, heading: bool) -> list[Run]:
    from docx.enum.text import WD_UNDERLINE
    from docx.oxml.ns import qn
    from docx.text.run import Run as DocxRun

    out: list[Run] = []

    def take(element) -> None:
        for child in element.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "r":
                run = DocxRun(child, paragraph)
                text = run.text.replace("\t", " ")
                if not text:
                    continue
                style = run.style.name if run.style is not None else ""
                underline = run.underline not in (None, False, WD_UNDERLINE.NONE)
                out.append(
                    Run(
                        text,
                        bold=False if heading else bool(run.bold) or style == "Strong",
                        italic=bool(run.italic) or style == "Emphasis",
                        underline=bool(underline),
                    )
                )
            elif tag in ("hyperlink", "ins", "smartTag", "sdt", "sdtContent", "fldSimple"):
                take(child)
            # w:del — удалённое при записи исправлений не читается

    take(paragraph._p)
    _ = qn  # импорт оставлен для читаемости пространства имён
    return out


def _heading_level(paragraph) -> int:
    name = (paragraph.style.name if paragraph.style is not None else "").lower().replace(" ", "")
    if name == "title":
        return 1
    found = re.fullmatch(r"(?:heading|заголовок)(\d)", name)
    return min(int(found.group(1)), 4) if found else 0


def _list_kind(paragraph, doc) -> Optional[tuple[bool, str]]:
    """(нумерованный?, ключ списка) для абзаца списка, иначе None."""
    from docx.oxml.ns import qn

    style_name = (paragraph.style.name if paragraph.style is not None else "").lower()
    num_pr = paragraph._p.pPr.numPr if paragraph._p.pPr is not None else None
    num_id = num_pr.numId.val if num_pr is not None and num_pr.numId is not None else None
    if num_id is None and paragraph.style is not None and paragraph.style.element.pPr is not None:
        style_pr = paragraph.style.element.pPr.numPr
        if style_pr is not None and style_pr.numId is not None:
            num_id = style_pr.numId.val
    if num_id == 0:
        return None
    if num_id is not None:
        try:
            numbering = doc.part.numbering_part.numbering_definitions._numbering
            abstract = None
            for num in numbering.findall(qn("w:num")):
                if int(num.get(qn("w:numId"))) == num_id:
                    abstract = int(num.find(qn("w:abstractNumId")).get(qn("w:val")))
            for node in numbering.findall(qn("w:abstractNum")):
                if abstract is not None and int(node.get(qn("w:abstractNumId"))) == abstract:
                    lvl = node.find(qn("w:lvl"))
                    fmt = (
                        lvl.find(qn("w:numFmt")).get(qn("w:val"))
                        if lvl is not None and lvl.find(qn("w:numFmt")) is not None
                        else ""
                    )
                    return (fmt != "bullet", f"n{num_id}")
        except (KeyError, AttributeError, ValueError, NotImplementedError):
            pass
        return ("bullet" not in style_name, f"n{num_id}")
    if style_name.startswith("list bullet"):
        return (False, f"s:{style_name}")
    if style_name.startswith("list number"):
        return (True, f"s:{style_name}")
    return None


def _reduce_fields(runs: list[Run]) -> list[Run]:
    """`[Подпись {{code}}]` → `{{code}}` по символам, чтобы оформление поля (цвет, жирный) не мешало найти скобки."""
    text = "".join(r.text for r in runs)
    if "{{" not in text:
        return runs
    chars = [(ch, r.bold, r.italic, r.underline) for r in runs for ch in r.text]
    out: list[tuple[str, bool, bool, bool]] = []
    pos = 0
    for match in FIELD_RE.finditer(text):
        out += chars[pos : match.start()]
        keep = f"{{{{{match.group(1)}}}}}"
        _, bold, italic, underline = chars[match.start()]
        out += [(ch, bold, italic, underline) for ch in keep]
        pos = match.end()
    out += chars[pos:]
    result: list[Run] = []
    for ch, bold, italic, underline in out:
        if result and (result[-1].bold, result[-1].italic, result[-1].underline) == (bold, italic, underline):
            result[-1] = Run(result[-1].text + ch, bold, italic, underline)
        else:
            result.append(Run(ch, bold, italic, underline))
    return result


def _para_of(paragraph, doc) -> tuple[Optional[Para], Optional[tuple[bool, str]]]:
    level = _heading_level(paragraph)
    runs = _squash(_reduce_fields(_runs_of(paragraph, heading=bool(level))))
    kind = None if level else _list_kind(paragraph, doc)
    return (Para(runs, level) if runs else None), kind


def docx_to_blocks(stream) -> tuple[list[Block], dict]:
    """Блоки из DOCX и сведения о том, что отброшено (`images`)."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(stream)
    blocks: list[Block] = []
    current: Optional[tuple[str, ListBlock]] = None
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para, kind = _para_of(Paragraph(child, doc), doc)
            if para is None:
                continue
            if kind is not None:
                ordered, key = kind
                if current is not None and current[0] == key and current[1].ordered == ordered:
                    current[1].items.append(para.runs)
                else:
                    block = ListBlock(ordered, [para.runs])
                    blocks.append(block)
                    current = (key, block)
                continue
            current = None
            blocks.append(para)
        elif tag == "tbl":
            current = None
            rows: list[list[list[Para]]] = []
            for row in Table(child, doc).rows:
                seen: set[int] = set()
                cells: list[list[Para]] = []
                for cell in row.cells:  # объединённая ячейка повторяется — берём один раз
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cells.append([p for p in (_para_of(x, doc)[0] for x in cell.paragraphs) if p is not None])
                if any(cells):
                    rows.append(cells)
            if rows:
                blocks.append(TableBlock(rows))
        if len(blocks) > MAX_BLOCKS:
            raise WordError("WORD_TOO_BIG")
    images = len(doc.element.body.xpath(".//w:drawing | .//w:pict"))
    return blocks, {"images": images}


# ── проверка и сохранение загрузки ────────────────────────────────────────────────────────────────────────────────


def digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def read_upload(content: bytes, name: str) -> tuple[list[Block], dict]:
    """Недоверенный файл → блоки. Только `.docx`, размер, архив (бомба), число абзацев; нечитаемое — `WORD_UNREADABLE`."""
    if not (name or "").lower().endswith(".docx"):
        raise WordError("WORD_ONLY_DOCX")
    if len(content) > MAX_WORD_BYTES:
        raise WordError("WORD_TOO_BIG")
    if not content:
        raise WordError("WORD_EMPTY")
    try:
        contract_compare.check_archive(content)
    except contract_compare.HostileFile as error:
        raise WordError("WORD_HOSTILE") from error
    try:
        blocks, dropped = docx_to_blocks(BytesIO(content))
    except WordError:
        raise
    except Exception as error:  # правильная сигнатура, но не Word (битый XML, чужой zip)
        raise WordError("WORD_UNREADABLE") from error
    if not paragraphs_of(blocks):
        raise WordError("WORD_EMPTY")
    return blocks, dropped


def check(template, language: str, content: bytes, name: str) -> dict:
    """Что изменится, если принять файл. Ничего не пишет.

    `{unchanged, formatting_only, changes: {items, summary}, unknown_placeholders, missing_blocks, images_dropped, base,
    locked, can_apply, body_html}`; `base` — отпечаток текущего текста, его же присылает «Принять» (текст успели поменять —
    409, а не тихая перезапись).
    """
    from . import contract_templates
    from .document_blocks import missing_required_blocks

    blocks, dropped = read_upload(content, name)
    current_html = template_body(template, language)
    new_html = sanitize_template_html(blocks_to_html(blocks))
    current_blocks = html_to_blocks(current_html)
    ours, theirs = paragraphs_of(current_blocks), paragraphs_of(blocks)
    clip = contract_compare.MAX_PARAGRAPH_CHARS
    try:
        changes = contract_compare.compare([x[:clip] for x in ours], [x[:clip] for x in theirs])
    except contract_compare.TooBig as error:
        raise WordError("WORD_TOO_COMPLEX") from error
    text_same = ours == theirs
    unchanged = text_same and canonical_html(current_html) == new_html
    missing = []
    if language == "ru" and template.is_active and not contract_templates.is_locked(template):
        from .document_blocks import DOCUMENT_BLOCKS

        missing = [
            {"code": code, "label": DOCUMENT_BLOCKS.get(code, code)}
            for code in missing_required_blocks(template.kind.code, new_html)
        ]
    locked = contract_templates.is_locked(template)
    return {
        "unchanged": unchanged,
        "formatting_only": text_same and not unchanged,
        "changes": changes,
        "unknown_placeholders": unknown_placeholders(new_html),
        "missing_blocks": missing,
        "images_dropped": dropped["images"],
        "base": digest(current_html),
        "locked": locked,
        "can_apply": not unchanged and not locked and not missing,
        "body_html": new_html,
    }


def apply(template, user, language: str, content: bytes, name: str, base: str):
    """«Принять изменения»: тот же разбор, что и в `check`, затем запись в тот же текст и язык + запись в журнале.

    Закреплённый (утверждённый или на утверждении) шаблон договора не меняется — только новая редакция (`TEMPLATE_LOCKED`).
    Текст успели поменять после проверки — `WORD_BASE_CHANGED`.
    """
    from django.core.exceptions import ValidationError
    from django.db import transaction

    from . import contract_templates
    from .generated_documents import MAX_TEMPLATE_BODY_CHARS, _assert_legal_template_integrity

    with transaction.atomic():
        template = type(template).objects.select_for_update().select_related("kind").get(pk=template.pk)
        if contract_templates.is_locked(template):
            raise ValidationError("TEMPLATE_LOCKED")
        blocks, _dropped = read_upload(content, name)
        if digest(template_body(template, language)) != base:
            raise WordError("WORD_BASE_CHANGED")
        new_html = sanitize_template_html(blocks_to_html(blocks))
        if len(new_html) > MAX_TEMPLATE_BODY_CHARS:
            raise ValidationError("TEMPLATE_BODY_TOO_LARGE")
        if language == "ru":
            _assert_legal_template_integrity(template.kind.code, new_html, template.is_active)
        before = template_body(template, language)
        setattr(template, LANGUAGE_FIELD[language], new_html)
        fields = [LANGUAGE_FIELD[language], "updated_at"]
        if language == "ru":
            template.placeholders_used = extract_placeholders(new_html)
            fields.append("placeholders_used")
        template.save(update_fields=fields)
        changes = contract_compare.compare(
            [x[: contract_compare.MAX_PARAGRAPH_CHARS] for x in paragraphs_of(html_to_blocks(before))],
            [x[: contract_compare.MAX_PARAGRAPH_CHARS] for x in paragraphs_of(blocks)],
        )["summary"]
        contract_templates._journal(
            template,
            user,
            "document_template.word_uploaded",
            "Текст шаблона загружен из Word",
            language=language,
            file=re.sub(r"[\x00-\x1f]+", " ", name)[:120],
            changed=len(changes["changed"]),
            added=len(changes["added"]),
            removed=len(changes["removed"]),
            total=changes["total"],
        )
    return template
