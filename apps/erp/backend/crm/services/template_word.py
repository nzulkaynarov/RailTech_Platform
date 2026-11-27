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
import time
from dataclasses import dataclass, field
from html import escape, unescape
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
    """Склеивает соседние куски с одинаковым оформлением, схлопывает пробелы, срезает края абзаца (за один проход, без
    попарного склеивания строк: абзац в десятки тысяч знаков не должен считаться квадратично)."""
    groups: list[tuple[tuple[bool, bool, bool], list[str]]] = []
    for run in runs:
        if not run.text:
            continue
        key = (run.bold, run.italic, run.underline)
        if groups and groups[-1][0] == key:
            groups[-1][1].append(run.text)
        else:
            groups.append((key, [run.text]))
    # пробелы и переносы: пробелы подряд — один, пробелы вокруг переноса убираются
    joined: list[Run] = []
    for key, pieces in groups:
        text = re.sub(r"[ \t\r\f\v\xa0]+", " ", "".join(pieces))
        text = re.sub(r" ?\n ?", "\n", text)
        joined.append(Run(text, *key))
    # края абзаца
    while joined and not joined[0].text.strip(" \n"):
        joined.pop(0)
    while joined and not joined[-1].text.strip(" \n"):
        joined.pop()
    if joined:
        first = joined[0]
        joined[0] = Run(first.text.lstrip(" \n"), first.bold, first.italic, first.underline)
        last = joined[-1]
        joined[-1] = Run(last.text.rstrip(" \n"), last.bold, last.italic, last.underline)
    # пробел на стыке двух кусков — один
    merged: list[Run] = []
    for run in joined:
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


_STRAY = re.compile(r"\{\{[^{}\n]{0,80}\}?\}?|\{?[^{}\n]{0,80}\}\}|[{}]")
_FIELD_AFTER = re.compile(r"([^\[\]{}\n]{0,120}?)\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}\]")


def broken_fields(html: str) -> list[str]:
    """Обрывки полей в тексте: `{{counterparty.name}`, `{{counterparty name}}`, `{{контрагент.имя}}`, стёртая «[» (остались
    подпись и «]»). Целые поля вида `{{code}}` — не обрывки (их проверяет `known_codes`)."""
    text = unescape(re.sub(r"<[^>]*>", "", html or ""))
    found: list[str] = []
    for match in _FIELD_AFTER.finditer(text):
        label = PLACEHOLDER_CATALOG.get(match.group(2), "")
        if label and match.group(1).rstrip().endswith(label):
            found.append(f"{label} {{{{{match.group(2)}}}}}]")
    rest = PLACEHOLDER_RE.sub("", text)
    for match in _STRAY.finditer(rest):
        token = match.group(0).strip()
        if token and token not in found:
            found.append(token)
    return found


def unknown_placeholders(*bodies: str) -> list[str]:
    """Неизвестные поля текстов в порядке появления, без повторов: коды без фигурных скобок (`warehouse.name`) и обрывки с
    ними (`{{counterparty.name}`). Любой из них не даёт отправить шаблон на утверждение."""
    known = known_codes()
    seen: list[str] = []
    for body in bodies:
        for code in extract_placeholders(body or ""):
            if code not in known and code not in seen:
                seen.append(code)
    for body in bodies:
        for token in broken_fields(body or ""):
            if token not in seen:
                seen.append(token)
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
    "ru": "Проект шаблона «{name}», ред. {edition}. Правьте текст как обычно. Поля в квадратных скобках заполняются данными: "
    "подпись можно не трогать, код в фигурных скобках менять нельзя. Колонтитулы при загрузке не читаются.",
    "uz": "«{name}» şablon loyihasi, {edition}-tahrir. Matnni odatdagidek tahrirlang. Kvadrat qavsdagi maydonlar "
    "maʼlumot bilan töldiriladi: nomiga tegmasa ham böladi, jingalak qavsdagi kodni özgartirib bölmaydi. "
    "Kolontitullar yuklaşda öqilmaydi.",
    "en": "Template draft «{name}», edition {edition}. Edit the text as usual. Fields in square brackets are filled with data: "
    "the label may be left alone, the code in curly braces must not be changed. Headers and footers are not read "
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
    blocks: list[Block], *, name: str, edition: int, language: str, brand: Optional[dict] = None, tag: str = ""
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
    doc.core_properties.keywords = tag

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
    """Word шаблона; в свойствах файла — метка «откуда»: id, редакция, язык и отпечаток текста на момент скачивания
    (загрузка файла, скачанного до чьей-то правки, отказывается: «скачайте заново и перенесите правки»)."""
    body = template_body(template, language) or template.body_html
    tag = f"{TAG_PREFIX}:{template.pk}:{template.edition}:{language}:{digest(template_body(template, language))}"
    return blocks_to_docx(
        html_to_blocks(body),
        name=template.name,
        edition=template.edition,
        language=language,
        brand=brand,
        tag=tag,
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
#
# Файл читается напрямую по XML (python-docx только открывает архив): так обход идёт один раз, стили и нумерация
# собираются в словари заранее (поиск стиля у python-docx — около 10 мс на абзац), а правки с записью исправлений,
# переносами, элементами управления, надписями и вложенными таблицами не теряются молча. Общий предел времени на разбор —
# `MAX_PARSE_SECONDS`, число единиц (абзацы, пункты списков, строки таблиц) — `MAX_BLOCKS`, ячеек — `MAX_CELLS`.

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
V_NS = "urn:schemas-microsoft-com:vml"
MAX_PARSE_SECONDS = 5.0
#: Знаков в одном абзаце и во всём тексте (как у сохранённого шаблона): больше — отказ ДО посимвольной обработки.
MAX_PARAGRAPH_TEXT = 50_000
MAX_TOTAL_TEXT = 100_000
MAX_CELLS = 6000
#: Что хранит «стоп-метка» файла: id шаблона, редакция, язык, отпечаток текста на момент скачивания.
TAG_PREFIX = "rt-template"


def _w(name: str) -> str:
    return f"{{{W_NS}}}{name}"


def _local(element) -> str:
    return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""


def _val(element, default: str = "") -> str:
    return element.get(_w("val"), default) if element is not None else default


def _on(element) -> bool:
    """Свойство текста вида `<w:b/>` включено: значение не «0» / «false» / «off»."""
    return element is not None and _val(element, "1").lower() not in ("0", "false", "off", "none")


@dataclass
class _Ctx:
    """Справочники файла и счётчики разбора."""

    styles: dict = field(default_factory=dict)  # id → (имя в нижнем регистре без пробелов, numId стиля или None)
    num_format: dict = field(default_factory=dict)  # numId → «bullet» / «decimal» / …
    deadline: float = 0.0
    units: int = 0
    cells: int = 0
    para_chars: int = 0
    total_chars: int = 0
    dropped: dict = field(default_factory=lambda: {k: 0 for k in DROPPED_KINDS})

    def add_chars(self, count: int) -> None:
        self.para_chars += count
        self.total_chars += count
        if self.para_chars > MAX_PARAGRAPH_TEXT or self.total_chars > MAX_TOTAL_TEXT:
            raise WordError("WORD_TOO_BIG")

    def tick(self, units: int = 1, cells: int = 0) -> None:
        self.units += units
        self.cells += cells
        if self.units > MAX_BLOCKS or self.cells > MAX_CELLS:
            raise WordError("WORD_TOO_BIG")
        if time.monotonic() > self.deadline:
            raise WordError("WORD_TOO_COMPLEX")


DROPPED_KINDS = ("images", "comments", "notes", "colors", "fonts", "highlights")


def _context(doc) -> _Ctx:
    ctx = _Ctx(deadline=time.monotonic() + MAX_PARSE_SECONDS)
    root = doc.styles.element
    for style in root.findall(_w("style")):
        name = _val(style.find(_w("name")))
        num = style.find(f"{_w('pPr')}/{_w('numPr')}/{_w('numId')}")
        ctx.styles[style.get(_w("styleId"), "")] = (
            name.lower().replace(" ", ""),
            int(_val(num)) if num is not None and _val(num).isdigit() else None,
        )
    try:
        numbering = doc.part.numbering_part.numbering_definitions._numbering
    except (KeyError, AttributeError, NotImplementedError):
        return ctx
    abstract: dict[int, str] = {}
    for node in numbering.findall(_w("abstractNum")):
        lvl = node.find(_w("lvl"))
        fmt = _val(lvl.find(_w("numFmt"))) if lvl is not None and lvl.find(_w("numFmt")) is not None else ""
        abstract[int(node.get(_w("abstractNumId"), "-1"))] = fmt
    for num in numbering.findall(_w("num")):
        link = num.find(_w("abstractNumId"))
        if link is not None:
            ctx.num_format[int(num.get(_w("numId"), "-1"))] = abstract.get(int(_val(link, "-1")), "")
    return ctx


@dataclass
class _Char:
    ch: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: bool = False
    highlight: bool = False
    font: bool = False


def _run_text(run) -> str:
    out = []
    for child in run:
        tag = _local(child)
        if tag == "t":
            out.append(child.text or "")
        elif tag in ("tab", "ptab"):
            out.append(" ")
        elif tag in ("br", "cr"):
            if child.get(_w("type"), "textWrapping") != "page":
                out.append("\n")
        elif tag == "noBreakHyphen":
            out.append("-")
    return "".join(out)


def _run_chars(run, ctx: _Ctx, heading: bool) -> list[_Char]:
    text = _run_text(run)
    if not text:
        return []
    ctx.add_chars(len(text))  # до посимвольной обработки: абзац в миллионы знаков отклоняется сразу
    ctx.tick(0)
    props = run.find(_w("rPr"))
    style_name = ""
    bold = italic = underline = color = highlight = font = False
    if props is not None:
        style = props.find(_w("rStyle"))
        style_name = ctx.styles.get(_val(style), ("", None))[0] if style is not None else ""
        bold, italic = _on(props.find(_w("b"))), _on(props.find(_w("i")))
        underline = _on(props.find(_w("u")))
        paint = props.find(_w("color"))
        color = paint is not None and _val(paint).lower() not in ("", "auto", "000000")
        mark = props.find(_w("highlight"))
        shade = props.find(_w("shd"))
        highlight = (mark is not None and _val(mark) != "none") or (
            shade is not None and shade.get(_w("fill"), "auto").lower() not in ("auto", "ffffff")
        )
        fonts = props.find(_w("rFonts"))
        font = fonts is not None and any(fonts.get(_w(k)) for k in ("ascii", "hAnsi", "cs", "eastAsia"))
    bold = (bold or style_name == "strong") and not heading
    italic = italic or style_name == "emphasis"
    return [_Char(ch, bold, italic, underline, color, highlight, font) for ch in text]


def _inside_fallback(element) -> bool:
    parent = element.getparent()
    while parent is not None:
        if parent.tag == f"{{{MC_NS}}}Fallback":
            return True
        parent = parent.getparent()
    return False


def _scan_run_objects(run, ctx: _Ctx, extra: list) -> None:
    """Рисунки, сноски, комментарии и надписи внутри строки текста."""
    for child in run.iter():
        tag = _local(child)
        if tag in ("commentReference",):
            ctx.dropped["comments"] += 1
        elif tag in ("footnoteReference", "endnoteReference"):
            ctx.dropped["notes"] += 1
        elif tag == "txbxContent" and not _inside_fallback(child):
            extra.append(child)
        elif (tag == "blip" and child.tag == f"{{{A_NS}}}blip") or (
            tag == "imagedata" and child.tag == f"{{{V_NS}}}imagedata"
        ):
            if not _inside_fallback(child):
                ctx.dropped["images"] += 1


_INLINE_WRAPPERS = {
    "hyperlink",
    "ins",
    "moveTo",
    "smartTag",
    "sdt",
    "sdtContent",
    "customXml",
    "fldSimple",
    "dir",
    "bdo",
}


def _collect(element, ctx: _Ctx, heading: bool, chars: list[_Char], extra: list) -> None:
    for child in element:
        tag = _local(child)
        if tag == "r":
            chars += _run_chars(child, ctx, heading)
            _scan_run_objects(child, ctx, extra)
        elif tag in _INLINE_WRAPPERS:
            _collect(child, ctx, heading, chars, extra)
        # w:del и w:moveFrom — удалённое при записи исправлений, не читается


def _reduce_fields(chars: list[_Char], ctx: _Ctx) -> list[Run]:
    """Подписи полей `[Подпись {{code}}]` → `{{code}}`; любой `{{…}}` получает оформление первого знака, иначе
    `{{counter<i>party.</i>name}}` печатался бы с тегами внутри. Цвет, шрифт и выделение вне полей считаются отброшенным.
    """
    text = "".join(c.ch for c in chars)
    spans: list[tuple[int, int, str]] = []  # (от, до, на что заменить)
    if "{{" in text or "[" in text:
        taken = []
        for match in FIELD_RE.finditer(text):
            spans.append((match.start(), match.end(), f"{{{{{match.group(1)}}}}}"))
            taken.append((match.start(), match.end()))
        for match in re.finditer(r"\{\{[^{}\n]*?\}\}", text):
            if not any(a <= match.start() < b for a, b in taken):
                spans.append((match.start(), match.end(), match.group(0)))
        spans.sort()
    out: list[_Char] = []
    inside: list[bool] = []
    pos = 0
    for start, end, keep in spans:
        for c in chars[pos:start]:
            out.append(c)
            inside.append(False)
        first = chars[start]
        for ch in keep:
            out.append(_Char(ch, first.bold, first.italic, first.underline))
            inside.append(True)
        pos = end
    for c in chars[pos:]:
        out.append(c)
        inside.append(False)
    for flag in ("color", "font", "highlight"):
        previous = False
        for c, in_field in zip(out, inside):
            now = getattr(c, flag) and not in_field and bool(c.ch.strip())
            if now and not previous:
                ctx.dropped[{"color": "colors", "font": "fonts", "highlight": "highlights"}[flag]] += 1
            previous = now
    groups: list[tuple[tuple[bool, bool, bool], list[str]]] = []
    for c in out:
        key = (c.bold, c.italic, c.underline)
        if groups and groups[-1][0] == key:
            groups[-1][1].append(c.ch)
        else:
            groups.append((key, [c.ch]))
    runs = [Run("".join(pieces), *key) for key, pieces in groups]
    return runs


def _heading_level(name: str) -> int:
    if name == "title":
        return 1
    found = re.fullmatch(r"(?:heading|заголовок)(\d)", name)
    return min(int(found.group(1)), 4) if found else 0


def _list_kind(p, ctx: _Ctx, style_id: str) -> Optional[tuple[bool, str]]:
    props = p.find(_w("pPr"))
    num_pr = props.find(_w("numPr")) if props is not None else None
    num_id = None
    if num_pr is not None and num_pr.find(_w("numId")) is not None:
        raw = _val(num_pr.find(_w("numId")))
        num_id = int(raw) if raw.isdigit() else None
    name, style_num = ctx.styles.get(style_id, ("", None))
    if num_id is None:
        num_id = style_num
    if num_id == 0:
        return None
    if num_id is not None:
        return (ctx.num_format.get(num_id, "bullet" if "bullet" in name else "decimal") != "bullet", f"n{num_id}")
    if name.startswith("listbullet"):
        return (False, f"s:{name}")
    if name.startswith("listnumber"):
        return (True, f"s:{name}")
    return None


def _para(p, ctx: _Ctx) -> tuple[Optional[Para], Optional[tuple[bool, str]], list]:
    ctx.tick()
    ctx.para_chars = 0
    props = p.find(_w("pPr"))
    style = props.find(_w("pStyle")) if props is not None else None
    style_id = _val(style) if style is not None else ""
    level = _heading_level(ctx.styles.get(style_id, ("", None))[0])
    chars: list[_Char] = []
    extra: list = []
    _collect(p, ctx, bool(level), chars, extra)
    runs = _squash(_reduce_fields(chars, ctx))
    kind = None if level else _list_kind(p, ctx, style_id)
    return (Para(runs, level) if runs else None), kind, extra


def _container(element, ctx: _Ctx, flat: bool) -> list[Block]:
    """Блоки внутри тела, ячейки, надписи или элемента управления; `flat` — в ячейке: списки и вложенные таблицы плоскими абзацами."""
    blocks: list[Block] = []
    current: Optional[tuple[str, ListBlock]] = None
    for child in element:
        tag = _local(child)
        if tag == "p":
            para, kind, extra = _para(child, ctx)
            if para is not None:
                if kind is not None and not flat:
                    ordered, key = kind
                    if current is not None and current[0] == key and current[1].ordered == ordered:
                        current[1].items.append(para.runs)
                    else:
                        block = ListBlock(ordered, [para.runs])
                        blocks.append(block)
                        current = (key, block)
                else:
                    current = None
                    blocks.append(para)
            else:
                current = None
            for box in extra:  # надпись: её абзацы идут следом за абзацем-хозяином
                blocks += _container(box, ctx, flat)
        elif tag == "tbl":
            current = None
            rows: list[list[list[Para]]] = []
            for row in child.iter(_w("tr")):
                if next((a for a in row.iterancestors(_w("tbl"))), None) is not child:
                    continue  # строка вложенной таблицы читается своим вызовом
                ctx.tick()
                cells: list[list[Para]] = []
                for cell in row.findall(_w("tc")):
                    ctx.tick(0, 1)
                    inner = _container(cell, ctx, True)
                    paras: list[Para] = []
                    for block in inner:
                        if isinstance(block, Para):
                            paras.append(block)
                        elif isinstance(block, TableBlock):
                            for sub_row in block.rows:
                                joined = [p for sub in sub_row for p in sub]
                                if joined:
                                    runs = []
                                    for k, part in enumerate(joined):
                                        runs += ([Run(" | ")] if k else []) + part.runs
                                    paras.append(Para(runs))
                    cells.append(paras)
                if any(cells):
                    rows.append(cells)
            if rows:
                blocks.append(TableBlock(rows))
        elif tag in ("sdt", "customXml", "ins", "moveTo", "smartTag"):
            content = child.find(_w("sdtContent")) if tag == "sdt" else child
            if content is not None:
                blocks += _container(content, ctx, flat)
        # w:del / w:moveFrom, закладки, свойства — не читаются
    return blocks


def _tag_of(doc) -> str:
    return (doc.core_properties.keywords or "").strip()


def docx_to_blocks(stream) -> tuple[list[Block], dict]:
    """Блоки из DOCX и сведения: что отброшено (`dropped`) и метка скачивания (`tag`)."""
    from docx import Document

    doc = Document(stream)
    ctx = _context(doc)
    blocks = _container(doc.element.body, ctx, False)
    return blocks, {"dropped": ctx.dropped, "tag": _tag_of(doc)}


# ── что в текущем шаблоне Word не удержит ─────────────────────────────────────────────────────────────────────────


class _Lost(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found = {"links": 0, "rules": 0, "pictures": 0, "merged_cells": 0, "nested_lists": 0, "nested_tables": 0}
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.found["links"] += 1
        elif tag == "hr":
            self.found["rules"] += 1
        elif tag == "img":
            self.found["pictures"] += 1
        elif tag in ("td", "th") and any(str(a.get(k) or "1") not in ("1", "") for k in ("colspan", "rowspan")):
            self.found["merged_cells"] += 1
        elif tag in ("ul", "ol") and any(t in ("ul", "ol") for t in self.stack):
            self.found["nested_lists"] += 1
        elif tag == "table" and "table" in self.stack:
            self.found["nested_tables"] += 1
        if tag not in ("br", "hr", "img"):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass


def lost_markup(html: str) -> list[dict]:
    """Что есть в текущем тексте и не переживёт загрузку из Word: `[{kind, count}]`, пусто — ничего."""
    parser = _Lost()
    parser.feed(html or "")
    parser.close()
    return [{"kind": kind, "count": count} for kind, count in parser.found.items() if count]


# ── проверка и сохранение загрузки ────────────────────────────────────────────────────────────────────────────────


def digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def file_sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:16]


def read_upload(content: bytes, name: str) -> tuple[list[Block], dict]:
    """Недоверенный файл → блоки. Только `.docx`, размер, архив (бомба), число абзацев и время; нечитаемое — `WORD_UNREADABLE`."""
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
        blocks, meta = docx_to_blocks(BytesIO(content))
    except WordError:
        raise
    except Exception as error:  # правильная сигнатура, но не Word (битый XML, чужой zip)
        raise WordError("WORD_UNREADABLE") from error
    if not paragraphs_of(blocks):
        raise WordError("WORD_EMPTY")
    return blocks, meta


def _compare(ours: list[str], theirs: list[str]) -> dict:
    clip = contract_compare.MAX_PARAGRAPH_CHARS
    try:
        return contract_compare.compare([x[:clip] for x in ours], [x[:clip] for x in theirs])
    except contract_compare.TooBig as error:
        raise WordError("WORD_TOO_COMPLEX") from error


def _assert_fresh(template, language: str, tag: str) -> bool:
    """Файл скачан с этого шаблона, на этом языке, и текст с тех пор не менялся. Метка есть, но чужая — отказ (другой шаблон,
    другой язык, устаревший текст). Возвращает `False` для файла без метки: он сделан не нашей выгрузкой, принимается, сравнение
    покажет всё."""
    parts = tag.split(":") if tag.startswith(f"{TAG_PREFIX}:") else []
    if len(parts) != 5:
        return False
    _prefix, template_id, edition, tagged_language, fingerprint = parts
    if template_id != str(template.pk):
        raise WordError("WORD_OTHER_TEMPLATE")
    if tagged_language != language:
        raise WordError("WORD_OTHER_LANGUAGE")
    if edition != str(template.edition) or fingerprint != digest(template_body(template, language)):
        raise WordError("WORD_STALE")
    return True


def check(template, language: str, content: bytes, name: str) -> dict:
    """Что изменится, если принять файл. Ничего не пишет.

    `{unchanged, formatting_only, changes, unknown_placeholders, missing_blocks, dropped, lost_markup, base, file_sha,
    locked, can_apply, body_html}`; `base` — отпечаток текущего текста, `file_sha` — отпечаток файла: «Принять» присылает оба
    (текст успели поменять — 409, подменили файл — 409, а не тихая перезапись).
    """
    from . import contract_templates
    from .document_blocks import DOCUMENT_BLOCKS, missing_required_blocks

    blocks, meta = read_upload(content, name)
    marked = _assert_fresh(template, language, meta["tag"])
    current_html = template_body(template, language)
    new_html = sanitize_template_html(blocks_to_html(blocks))
    ours, theirs = paragraphs_of(html_to_blocks(current_html)), paragraphs_of(blocks)
    changes = _compare(ours, theirs)
    text_same = ours == theirs
    markup_same = canonical_html(current_html) == new_html
    dropped = [{"kind": k, "count": n} for k, n in meta["dropped"].items() if n]
    locked = contract_templates.is_locked(template)
    missing = []
    if language == "ru" and template.is_active and not locked:
        missing = [
            {"code": code, "label": DOCUMENT_BLOCKS.get(code, code)}
            for code in missing_required_blocks(template.kind.code, new_html)
        ]
    differs = not (text_same and markup_same)
    return {
        "unchanged": not differs and not dropped,
        "formatting_only": text_same and not markup_same,
        "changes": changes,
        "unknown_placeholders": unknown_placeholders(new_html),
        "missing_blocks": missing,
        "dropped": dropped,
        "lost_markup": lost_markup(current_html) if differs else [],
        "base": digest(current_html),
        "file_sha": file_sha(content),
        "from_elsewhere": not marked,
        "locked": locked,
        "can_apply": differs and not locked and not missing,
        "body_html": new_html,
    }


def apply(template, user, language: str, content: bytes, name: str, base: str, *, sha: str, confirm_loss: bool = False):
    """«Принять изменения»: тот же разбор, что и в `check`, затем запись в тот же текст и язык + запись в журнале.

    Закреплённый (утверждённый или на утверждении) шаблон договора не меняется — только новая редакция (`TEMPLATE_LOCKED`).
    Текст успели поменять после проверки — `WORD_BASE_CHANGED`; прислан другой файл, чем проверенный, — `WORD_FILE_CHANGED`;
    то, что Word не удержит (ссылки, рисунки, объединённые ячейки…), `check` перечисляет заранее, «Принять» не задерживает;
    прежний текст остаётся в записи журнала (`event_params.previous`).
    """
    from django.core.exceptions import ValidationError
    from django.db import transaction

    from . import contract_templates
    from .generated_documents import MAX_TEMPLATE_BODY_CHARS, _assert_legal_template_integrity

    with transaction.atomic():
        template = type(template).objects.select_for_update().select_related("kind").get(pk=template.pk)
        if contract_templates.is_locked(template):
            raise ValidationError("TEMPLATE_LOCKED")
        blocks, meta = read_upload(content, name)
        if sha != file_sha(content):
            raise WordError("WORD_FILE_CHANGED")
        _assert_fresh(template, language, meta["tag"])
        if digest(template_body(template, language)) != base:
            raise WordError("WORD_BASE_CHANGED")
        before = template_body(template, language)
        new_html = sanitize_template_html(blocks_to_html(blocks))
        if len(new_html) > MAX_TEMPLATE_BODY_CHARS:
            raise ValidationError("TEMPLATE_BODY_TOO_LARGE")
        if language == "ru":
            _assert_legal_template_integrity(template.kind.code, new_html, template.is_active)
        setattr(template, LANGUAGE_FIELD[language], new_html)
        fields = [LANGUAGE_FIELD[language], "updated_at"]
        if language == "ru":
            template.placeholders_used = extract_placeholders(new_html)
            fields.append("placeholders_used")
        template.save(update_fields=fields)
        try:
            summary = _compare(paragraphs_of(html_to_blocks(before)), paragraphs_of(blocks))["summary"]
            counts = {
                "changed": len(summary["changed"]),
                "added": len(summary["added"]),
                "removed": len(summary["removed"]),
                "total": summary["total"],
            }
        except WordError:  # слишком много правок для сравнения: текст принят, число пунктов в журнал не пишется
            counts = {}
        contract_templates._journal(
            template,
            user,
            "document_template.word_uploaded",
            "Текст шаблона загружен из Word",
            language=language,
            file=re.sub(r"[\x00-\x1f]+", " ", name)[:120],
            previous=before,
            **counts,
        )
    return template
