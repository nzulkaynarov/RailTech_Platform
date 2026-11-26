"""ДП-1: текст договора, его DOCX для правок и сравнение с редакцией контрагента («система показывает, что изменилось»).

Три вещи, и ни одна не решает за людей (код считает, человек решает):

* `contract_paragraphs(contract)` — текст нашей редакции абзацами: тело договора из замороженной редакции шаблона, как оно
  печатается в PDF, без разметки;
* `contract_docx(contract)` — те же абзацы в DOCX: контрагент скачивает, правит и загружает обратно;
* `compare(ours, theirs)` — построчное сравнение двух списков абзацев: изменён / добавлен / удалён, пункт — по номеру в
  начале абзаца. Загруженная редакция — вложение и точка правды; разбор лишь помогает её прочитать. XLSX не сравнивается
  (таблицы произвольной формы) — вложение остаётся, разбор пустой.
"""

from __future__ import annotations

import difflib
import re
import time
from io import BytesIO
from typing import Optional

BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div", "td", "th", "blockquote"}
POINT_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")
#: Предел списка в ответе: договор на сотни абзацев не должен раздувать карточку.
MAX_ITEMS = 200
_WORD = re.compile(r"\s+|\S+")
EMPTY_SUMMARY = {"changed": [], "added": [], "removed": [], "total": 0, "more": 0}

#: Пределы разбора чужого файла: договор на сотни абзацев — норма, тысячи — не договор, а попытка занять сервер.
MAX_PARAGRAPHS = 1500
MAX_PARAGRAPH_CHARS = 2000
#: В кратком разборе — не больше стольких пунктов на вид, остальное — «и ещё N».
SUMMARY_POINTS = 30
#: Заменённый кусок больше этого числа пар сравнивается только по номерам пунктов.
MAX_PAIR_CELLS = 10_000
#: Подсветка слов — не более чем для стольких изменённых пунктов.
MAX_SEGMENTED = 100
#: Бюджет попарного сравнения: сумма len(a)*len(b) по парам абзацев и предел времени на весь разбор.
MAX_PAIR_COST = 3_000_000
MAX_COMPARE_SECONDS = 3.0
#: Архив DOCX/XLSX (zip): сколько частей, сколько всего после распаковки и во сколько раз одна часть может сжиматься.
MAX_ARCHIVE_MEMBERS = 2000
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


class TooBig(Exception):
    """Сравнение не уложилось в бюджет: файл остаётся вложением, разбора нет."""


class HostileFile(ValueError):
    """Файл не разбирается: архив-бомба или слишком большой после распаковки."""


def _unpacked_size(content: bytes, member, budget: int) -> int:
    """Сколько байт на самом деле даёт часть после распаковки (останавливается за `budget`): размеры из каталога архива
    подделываются, поэтому считаем сами по потоку, кусками, не держа распакованное в памяти."""
    import struct
    import zlib

    head = content[member.header_offset : member.header_offset + 30]
    if len(head) < 30 or head[:4] != b"PK\x03\x04":
        raise HostileFile("broken local header")
    name_len, extra_len = struct.unpack("<HH", head[26:30])
    start = member.header_offset + 30 + name_len + extra_len
    if member.compress_type == 0:  # stored
        return min(max(len(content) - start, 0), member.compress_size)
    if member.compress_type != 8:  # только deflate
        raise HostileFile("unsupported compression")
    unpacker = zlib.decompressobj(-15)
    total, pos = 0, start
    while not unpacker.eof:
        data = unpacker.unconsumed_tail
        if not data:
            if pos >= len(content):
                break
            data = content[pos : pos + 65536]
            pos += 65536
        try:
            total += len(unpacker.decompress(data, 1 << 20))
        except zlib.error as error:
            raise HostileFile("broken deflate stream") from error
        if total > budget:
            break
    return total


def check_archive(content: bytes) -> None:
    """Проверка zip-архива ДО python-docx: число частей, суммарный размер после распаковки и степень сжатия — по
    фактически распакованным байтам (размеры в каталоге архива могут лгать)."""
    import zipfile

    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
    except zipfile.BadZipFile as error:
        raise HostileFile("not a zip archive") from error
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise HostileFile("too many parts")
    total = 0
    for member in members:
        if member.is_dir():
            continue
        actual = _unpacked_size(content, member, MAX_ARCHIVE_BYTES - total)
        total += actual
        if total > MAX_ARCHIVE_BYTES:
            raise HostileFile("too large after unpacking")
        if actual > 1024 * 1024 and actual > max(member.compress_size, 1) * MAX_COMPRESSION_RATIO:
            raise HostileFile("suspicious compression ratio")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def html_paragraphs(html: str) -> list[str]:
    """Абзацы из HTML: листовые блочные элементы; строка таблицы — одним абзацем через « | »."""
    from lxml import html as lxml_html

    if not (html or "").strip():
        return []
    root = lxml_html.fragment_fromstring(html, create_parent="div")
    for bad in root.xpath("//script|//style"):
        bad.getparent().remove(bad)
    out: list[str] = []

    def has_block_child(node) -> bool:
        return any(isinstance(c.tag, str) and c.tag in BLOCK_TAGS for c in node.iterdescendants())

    def walk(node) -> None:
        for child in node:
            if not isinstance(child.tag, str):
                continue
            if child.tag == "tr":
                cells = [_norm(c.text_content()) for c in child if isinstance(c.tag, str) and c.tag in ("td", "th")]
                row = " | ".join(c for c in cells if c)
                if row:
                    out.append(row)
            elif child.tag in BLOCK_TAGS and not has_block_child(child):
                text = _norm(child.text_content())
                if text:
                    out.append(text)
            else:
                walk(child)

    walk(root)
    if not out:
        text = _norm(root.text_content())
        return [text] if text else []
    return out


def contract_body_html(contract) -> str:
    """HTML тела нашей редакции договора — как в PDF (замороженная редакция шаблона или образец)."""
    from core.seeds.documents import CONTRACT_BODY

    from .document_blocks import company_template_for, render_contract_body
    from .documents import document_brand_context, document_totals
    from .documents.projection import client_billable_lines
    from .quotes import _quote_seller_company

    supplier = _quote_seller_company(contract.quote)
    brand = document_brand_context(supplier)
    ccy = contract.currency.code if contract.currency_id else "UZS"
    totals = document_totals(
        ccy=ccy, vat_rate=contract.quote.vat_rate if contract.quote_id else None, total=contract.total_amount
    )
    items = client_billable_lines(contract.quote)
    frozen = contract.frozen_template_body
    template = None if frozen else company_template_for(supplier, "CONTRACT")
    return render_contract_body(
        contract,
        items,
        totals,
        ccy,
        template,
        seller=brand.get("seller"),
        seller_profile=brand.get("seller_profile"),
        body_html=frozen or (template.body_html if template is not None else CONTRACT_BODY),
        draft=False,
    )


def contract_paragraphs(contract) -> list[str]:
    return html_paragraphs(contract_body_html(contract))


def paragraphs_to_docx(paragraphs: list[str]) -> bytes:
    from docx import Document

    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def contract_docx(contract) -> bytes:
    return paragraphs_to_docx(contract_paragraphs(contract))


def docx_paragraphs(stream) -> list[str]:
    """Абзацы DOCX в порядке документа: обычные абзацы и строки таблиц (ячейки через « | »)."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(stream)
    out: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = _norm(Paragraph(child, doc).text)
            if text:
                out.append(text)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                seen, cells = set(), []
                for cell in row.cells:  # объединённые ячейки повторяются — берём один раз
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    text = _norm(cell.text)
                    if text:
                        cells.append(text)
                if cells:
                    out.append(" | ".join(cells))
    return out


def _point(text: str) -> Optional[str]:
    found = POINT_RE.match(text or "")
    return found.group(1) if found else None


def _segments(old: str, new: str) -> list[dict]:
    """Слова двух абзацев: общие, удалённые (`del`) и добавленные (`ins`) — для подсветки рядом."""
    a, b = _WORD.findall(old), _WORD.findall(new)
    out: list[dict] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"op": "equal", "text": "".join(a[i1:i2])})
            continue
        if i2 > i1:
            out.append({"op": "del", "text": "".join(a[i1:i2])})
        if j2 > j1:
            out.append({"op": "ins", "text": "".join(b[j1:j2])})
    return out


def _pair(old: list[str], new: list[str], deadline: float) -> dict[int, int]:
    """Какой абзац «заменён» каким: тот же номер пункта либо достаточно похожий текст; остальные — добавлены/удалены."""
    pairs: dict[int, int] = {}
    taken: set[int] = set()
    if (
        len(old) * len(new) > MAX_PAIR_CELLS
    ):  # большой заменённый кусок: только по номеру пункта, без попарного сходства
        by_point = {_point(t): m for m, t in reversed(list(enumerate(old))) if _point(t)}
        for k, text in enumerate(new):
            m = by_point.get(_point(text))
            if m is not None and m not in taken:
                pairs[k] = m
                taken.add(m)
        return pairs
    if sum(len(t) for t in old) * sum(len(t) for t in new) > MAX_PAIR_COST:
        raise TooBig("pairwise comparison over budget")
    for k, text in enumerate(new):
        point = _point(text)
        best, best_ratio = None, 0.0
        for m, before in enumerate(old):
            if m in taken:
                continue
            if time.monotonic() > deadline:
                raise TooBig("comparison took too long")
            matcher = difflib.SequenceMatcher(a=before, b=text, autojunk=False)
            bonus = (
                1.0 if point is not None and _point(before) == point else 0.0
            )  # тот же номер пункта — главный признак
            # дешёвые верхние оценки: заведомо непохожее и хуже лучшего не считаем точно
            if bonus + matcher.real_quick_ratio() <= best_ratio or bonus + matcher.quick_ratio() <= best_ratio:
                continue
            if not bonus and matcher.quick_ratio() < 0.6:
                continue
            ratio = bonus + matcher.ratio()
            if ratio > best_ratio:
                best, best_ratio = m, ratio
        if best is not None and best_ratio >= 0.6:
            pairs[k] = best
            taken.add(best)
    return pairs


def compare(ours: list[str], theirs: list[str]) -> dict:
    """`{items, summary}`: что изменилось в `theirs` относительно `ours`.

    `items` — `{point, kind: changed|added|removed, ours, theirs, segments}` в порядке договора; `summary` —
    `{changed: [пункты], added: [пункты], removed: [пункты], total}` (пункт без номера не попадает в списки, но
    считается в `total`). Абзацы выравниваются `difflib`, внутри «заменённого» куска пары берутся по порядку.
    """
    items: list[dict] = []
    deadline = time.monotonic() + MAX_COMPARE_SECONDS
    matcher = difflib.SequenceMatcher(a=ours, b=theirs, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        old, new = ours[i1:i2], theirs[j1:j2]
        pairs = _pair(old, new, deadline) if op == "replace" else {}
        for k, text in enumerate(new):
            if k in pairs:
                before = old[pairs[k]]
                items.append(
                    {
                        "point": _point(text) or _point(before) or "",
                        "kind": "changed",
                        "ours": before,
                        "theirs": text,
                        "segments": (
                            _segments(before, text)
                            if len(items) < MAX_SEGMENTED and time.monotonic() < deadline
                            else []
                        ),
                    }
                )
            else:
                items.append({"point": _point(text) or "", "kind": "added", "ours": "", "theirs": text, "segments": []})
        for k, text in enumerate(old):
            if k not in pairs.values():
                items.append(
                    {"point": _point(text) or "", "kind": "removed", "ours": text, "theirs": "", "segments": []}
                )
    summary: dict = {"more": 0}
    for kind in ("changed", "added", "removed"):
        points = [i["point"] for i in items if i["kind"] == kind and i["point"]]
        summary[kind] = points[:SUMMARY_POINTS]
        summary["more"] += max(0, len(points) - SUMMARY_POINTS)
    summary["total"] = len(items)
    return {"items": items[:MAX_ITEMS], "summary": summary}


def compare_upload(contract, file_obj, name: str) -> dict:
    """Разбор загруженной редакции: DOCX сравнивается с нашей, прочее (XLSX) — без разбора. Нечитаемый DOCX — пустой разбор."""
    unreadable = {"items": [], "summary": dict(EMPTY_SUMMARY), "comparable": False}
    if not name.lower().endswith(".docx"):
        return unreadable
    try:
        file_obj.seek(0)
        check_archive(file_obj.read())
        file_obj.seek(0)
        theirs = docx_paragraphs(file_obj)
        file_obj.seek(0)
        ours = contract_paragraphs(contract)
        if len(theirs) > MAX_PARAGRAPHS or len(ours) > MAX_PARAGRAPHS:
            return unreadable  # слишком большой файл: вложение остаётся, автоматического разбора нет
        result = compare([x[:MAX_PARAGRAPH_CHARS] for x in ours], [x[:MAX_PARAGRAPH_CHARS] for x in theirs])
    except TooBig:
        return {**unreadable, "too_big": True}
    except Exception:  # файл с правильной сигнатурой, но не читается как Word: вложение остаётся, разбора нет
        return unreadable
    return {**result, "comparable": True}
