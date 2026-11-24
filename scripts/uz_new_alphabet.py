#!/usr/bin/env python3
"""Convert Uzbek text from the old Latin spelling to the owner's new Latin alphabet.

Owner rule 2026-11-17: Ö Ğ Ş Ç instead of Oʻ Gʻ Sh Ch; the modifier letter apostrophe ʼ (U+02BC) stays for
the glottal stop; counterparty data (names, addresses, brands, codes) is never transliterated.

``convert_uz(text)`` is a pure function. File handlers touch only Uzbek values:

* ``*.json``  - every string *value* (never keys) of an Uzbek locale file;
* ``*.po``    - ``msgstr`` / ``msgstr[n]`` strings (never ``msgid``, never the header entry);
* ``*.ts``    - string literals (or arrays of them) of an ``uz:`` property;
* ``*.py``    - string literals reachable from the value of an ``"uz"`` dict key (str, f-string text parts,
  conditional branches, tuples/lists, nested dict values, ``+``); never code inside ``{...}``.

CLI (dev script of task uz1; the converter is idempotent, a second --apply changes nothing)::

    convert.py --check  FILE...     # count strings that would change
    convert.py --diff   FILE...     # print a unified diff
    convert.py --apply  FILE...     # rewrite the given copies in place
"""

from __future__ import annotations

import argparse
import ast
import difflib
import io
import json
import re
import sys
import tokenize
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

# ── Vocabulary ──────────────────────────────────────────────────────────────────────────────────────

# Brand / product / foreign names that keep their spelling. Matched as a word *stem*, case-sensitive, so an
# Uzbek suffix after it is still converted («Telegramga», «Excelda»).
BRANDS: tuple[str, ...] = (
    "RailTech",
    "Telegram",
    "WhatsApp",
    "Didox",
    "Excel",
    "PDF",
    "Siemens",
    "Google",
    "Gmail",
    "Microsoft",
    "Outlook",
    "Chrome",
    "ChatGPT",
    "Chat GPT",
    "Shopify",
    "Yandex",
    "Payme",
    "Click",
    "Uzum",
    "Soliq",
    "Faktura",
    "E-IMZO",
    "MyID",
    "OneID",
    "LiteLLM",
    "Ollama",
    "Claude",
    "Gemini",
    "Markdown",
    "English",
    "Bitrix",
    "Docker",
    "Postgres",
    "Schneider",
    "Bosch",
    "Hitachi",
    "Mitsubishi",
    "Wabtec",
    "Knorr",
    "Stadler",
    "Alstom",
    "Škoda",
    "Skoda",
    "Caterpillar",
    "Cummins",
    "Deutsche",
    "Shift",
    "Enter",
    "Tab",
    "Ctrl",
    "Esc",
    "Backspace",
)

# Words where «sh»/«ch» is not a digraph, or which must keep their spelling for another reason. Whole word,
# case-insensitive. Uzbek words with a real s+h boundary are written with ʼ («Isʼhoq», «Asʼhob») and need
# nothing; this list is for loans and foreign words that appear in UI copy.
EXCEPTIONS: tuple[str, ...] = (
    "English",  # language name shown in its own language
    "MChJ",  # legal-form abbreviation, part of company names (counterparty data)
    "Tashkent",  # English spelling inside English-only fragments / timezone names
    "JShShIR",  # official abbreviation (ЖШШИР, personal ID number), kept like STIR / MChJ — owner to decide
)

_LETTER = r"A-Za-zÀ-ÖØ-öø-ÿĀ-žƏəŞşÇçĞğ"
_APOS = "\u02bb\u2018\u2019'`\u02bc"  # ʻ ‘ ’ ' ` ʼ
_GLOTTAL = "\u02bc"

_LEGAL_FORMS = r"MChJ|MCHJ|OAJ|AJ|XK|QK|YaTT|XAJ|DUK|LLC|OOO|ООО"

# Spans that are never converted, tried left to right.
_PROTECT = re.compile(
    "|".join(
        (
            r"\{\{.*?\}\}",  # i18next {{name}}
            # company names next to a legal form are counterparty data: MChJ «Toshkent Logistik»
            rf"(?:{_LEGAL_FORMS})\s*«[^»]*»|«[^»]*»\s*(?:{_LEGAL_FORMS})\b",
            r"\$\{[^{}]*\}",  # template literal ${x}
            r"\{[^{}]*\}",  # python / ICU {name} {0}
            r"%\([A-Za-z_]\w*\)[sdifr]|%[sdif]",  # %(x)s %s
            r"\$t\([^)]*\)",  # i18next nesting
            r"(?<![\w/.])/[a-z][a-z_]*\b",  # bot commands /start /delete, URL paths
            r"<[^<>]+>",  # HTML tags with attributes
            r"&(?:[A-Za-z]+|#\d+);",  # HTML entities
            r"(?:https?|ftp)://[^\s\"'<>«»)]+",  # URLs
            r"\bwww\.[^\s\"'<>«»)]+",
            r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",  # e-mail
            r"\b[\w-]+\.(?:pdf|docx?|xlsx?|csv|json|md|txt|png|jpe?g|svg|zip|xml|html?|po|uz|ru|com|org|net|io)\b",
            r"(?<![\w])\.(?:pdf|docx?|xlsx?|csv|json|md|txt|png|jpe?g|svg|zip|xml|html?)\b",  # bare extension
            r"(?<![A-Za-z])`[^`\n]+`",  # inline code (a backtick glued to a letter is an apostrophe)
            r"\b\w*_\w*\b",  # snake_case identifiers
            r"\b[a-z]+[A-Z]\w*\b",  # camelCase identifiers
            r"\b\w*\d\w*\b",  # tokens with digits (codes, SHA256, 6x)
            r"\b[A-Z][A-Z\u02bb\u2018\u2019'`]*[A-Z]\s?-?\s?\d+",  # legal acts / standards: OʻRQ-547, PQ-123
            r"\bO[\u02bb\u2018\u2019'`]?z\s?DSt\b",  # national standard OʻzDSt
            r"\b(?=[a-z0-9.-]*\d)[a-z][a-z0-9]*(?:[-.][a-z0-9]+)+\b",  # model / package ids: gemini-3.8-flash
            r"\b[A-Z][A-Z]+\b",  # ALL-CAPS abbreviations (CRM, ERP, SHA, MCHJ)
            r"\b[A-Z]{2,}(?=[a-z])",  # abbreviation + Uzbek suffix: TTni, PDFdan
        )
    )
)

_BRAND_RE = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(b) for b in sorted(BRANDS, key=len, reverse=True)) + r")")
_EXCEPTION_RE = re.compile(
    r"(?<![\w])(?:" + "|".join(re.escape(e) for e in sorted(EXCEPTIONS, key=len, reverse=True)) + r")(?![\w])",
    re.IGNORECASE,
)

# oʻ / gʻ in any apostrophe variant. A letter must follow; gʻ may also end a word after a vowel («togʻ»).
_OG_RE = re.compile(rf"([oOgG])[{_APOS}](?=[{_LETTER}])|(?<=[aeiouAEIOU])([gG])[{_APOS}](?![{_LETTER}{_APOS}])")
# A non-oʻ/gʻ apostrophe becomes the glottal stop ʼ only after a known Uzbek stem («maʼlumot», «eʼlon»,
# «masʼul»). After anything else it is usually a suffix separator after a foreign word («Disk'da», «Drive'ni»,
# «Cloud'dan») and is left alone for a human to decide.
GLOTTAL_STEMS: frozenset[str] = frozenset(
    {
        "a",
        "ba",
        "da",
        "e",
        "in",
        "is",
        "as",
        "ja",
        "jur",
        "ma",
        "man",
        "mas",
        "mu",
        "mo",
        "noma",
        "qat",
        "ra",
        "sa",
        "san",
        "sun",
        "shu",
        "şu",
        "ta",
        "va",
        "mutaa",
        "nota",
    }
)
_GLOTTAL_RE = re.compile(rf"(?<![{_LETTER}])([{_LETTER}]+)([\u02bb\u2018\u2019'`])(?=([{_LETTER}])?)")
_SH_CH_RE = re.compile(r"([sScC])([hH])")

_MAP = {"o": "ö", "O": "Ö", "g": "ğ", "G": "Ğ"}


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans = [m.span() for m in _PROTECT.finditer(text)]
    spans += [m.span() for m in _BRAND_RE.finditer(text)]
    spans += [m.span() for m in _EXCEPTION_RE.finditer(text)]
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _convert_plain(chunk: str) -> str:
    def og(m: re.Match[str]) -> str:
        letter = m.group(1) or m.group(2)
        return _MAP[letter]

    chunk = _OG_RE.sub(og, chunk)

    def glottal(m: re.Match[str]) -> str:
        stem = m.group(1)
        known = stem.lower() in GLOTTAL_STEMS
        if known and (m.group(3) or stem.lower() == "man"):  # «manʼ» ends a word
            return stem + _GLOTTAL
        return m.group(0)

    chunk = _GLOTTAL_RE.sub(glottal, chunk)

    def digraph(m: re.Match[str]) -> str:
        first = m.group(1)
        new = "ş" if first in "sS" else "ç"
        return new.upper() if first.isupper() else new

    return _SH_CH_RE.sub(digraph, chunk)


def convert_uz(text: str) -> str:
    """Return ``text`` in the new alphabet; protected spans are copied verbatim. Idempotent."""
    out: list[str] = []
    pos = 0
    for start, end in _protected_spans(text):
        out.append(_convert_plain(text[pos:start]))
        out.append(text[start:end])
        pos = end
    out.append(_convert_plain(text[pos:]))
    return "".join(out)


# ── File handlers ───────────────────────────────────────────────────────────────────────────────────


@dataclass
class Change:
    where: str
    before: str
    after: str


@dataclass
class Result:
    text: str
    changes: list[Change] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # literals the handler refused to touch


def _replace_spans(source: str, edits: list[tuple[int, int, str]]) -> str:
    out, pos = [], 0
    for start, end, new in sorted(edits):
        out.append(source[pos:start])
        out.append(new)
        pos = end
    out.append(source[pos:])
    return "".join(out)


# JSON: scan the raw text so formatting and escapes stay byte-identical; only values change.
_JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


def _json_encode(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def convert_json(source: str, name: str = "") -> Result:
    res = Result(source)
    edits: list[tuple[int, int, str]] = []
    key = ""
    for m in _JSON_STRING.finditer(source):
        rest = source[m.end() :].lstrip()
        if rest.startswith(":"):
            key = json.loads(m.group(0))
            continue  # key
        raw = m.group(0)
        value = json.loads(raw)
        new = convert_uz(value)
        if new == value:
            continue
        if _json_encode(value) != raw:
            res.skipped.append(f"{name}: non-canonical JSON escape in {raw[:60]}")
            continue
        edits.append((m.start(), m.end(), _json_encode(new)))
        line = source.count("\n", 0, m.start()) + 1
        res.changes.append(Change(f"{name}:{line} {key}", value, new))
    json.loads(_replace_spans(source, edits))  # still valid JSON
    res.text = _replace_spans(source, edits)
    return res


# PO: msgstr lines and their continuation lines.
_PO_LINE = re.compile(r'^(msgstr(?:\[\d+\])?\s+|\s*)"((?:[^"\\]|\\.)*)"\s*$')
_PO_ESC = {"\\\\": "\\", '\\"': '"', "\\n": "\n", "\\t": "\t"}


def _po_decode(raw: str) -> str:
    return re.sub(r"\\[\\\"nt]", lambda m: _PO_ESC[m.group(0)], raw)


def _po_encode(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def convert_po(source: str, name: str = "") -> Result:
    res = Result(source)
    lines = source.splitlines(keepends=True)
    in_msgstr = False
    header = False
    last_msgid = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("msgid "):
            last_msgid = stripped
            in_msgstr = False
            continue
        if stripped.startswith("msgstr"):
            in_msgstr = True
            header = last_msgid == 'msgid ""'
        elif not stripped.startswith('"'):
            in_msgstr = False
        if not in_msgstr or header:
            continue
        m = _PO_LINE.match(line.rstrip("\n"))
        if not m:
            continue
        raw = m.group(2)
        value = _po_decode(raw)
        if _po_encode(value) != raw:
            res.skipped.append(f"{name}:{i + 1}: unusual PO escape")
            continue
        new = convert_uz(value)
        if new != value:
            start = line.index('"', len(m.group(1))) if m.group(1) else line.index('"')
            lines[i] = line[: start + 1] + _po_encode(new) + line[start + 1 + len(raw) :]
            res.changes.append(Change(f"{name}:{i + 1}", value, new))
    res.text = "".join(lines)
    return res


# TS: `uz: '...'`, `uz: "..."`, `uz: \`...\``, or `uz: [ '...', '...' ]`.
_TS_UZ = re.compile(r"(?<![\w$.])['\"]?uz['\"]?\s*:\s*")
_TS_STR = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`")
_TS_ESC = re.compile(r"\\(.)", re.DOTALL)


def _ts_decode(body: str) -> str:
    return _TS_ESC.sub(lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


def _ts_literal(source: str, pos: int) -> tuple[int, int] | None:
    m = _TS_STR.match(source, pos)
    return m.span() if m else None


def convert_ts(source: str, name: str = "") -> Result:
    res = Result(source)
    edits: list[tuple[int, int, str]] = []

    def handle(start: int, end: int) -> None:
        raw = source[start:end]
        quote, body = raw[0], raw[1:-1]
        if "\\" in body and quote != "`":
            # keep escapes verbatim: convert segments between escapes only
            parts = re.split(r"(\\.)", body)
            new_body = "".join(p if p.startswith("\\") else convert_uz(p) for p in parts)
        else:
            new_body = convert_uz(body)
        if new_body != body:
            edits.append((start, end, quote + new_body + quote))
            line = source.count("\n", 0, start) + 1
            res.changes.append(Change(f"{name}:{line}", _ts_decode(body), _ts_decode(new_body)))

    for m in _TS_UZ.finditer(source):
        pos = m.end()
        span = _ts_literal(source, pos)
        if span:
            handle(*span)
            continue
        if source.startswith("[", pos):
            pos += 1
            while True:
                ws = re.compile(r"(?:\s|,|//[^\n]*)*").match(source, pos)
                pos = ws.end() if ws else pos
                if source.startswith("]", pos):
                    break
                span = _ts_literal(source, pos)
                if not span:
                    res.skipped.append(f"{name}:{source.count(chr(10), 0, pos) + 1}: non-literal in uz array")
                    break
                handle(*span)
                pos = span[1]
    res.text = _replace_spans(source, edits)
    return res


# Python: AST finds the uz values, tokenize gives exact literal positions.
PY_EXCLUDE = {
    "language.py": "matches user input (old spelling, normalised apostrophes); converting breaks detection",
    "platform_roles_generated.py": "generated from packages/contracts/platform-rbac.yaml; convert the source",
}


# Helpers whose positional argument N is the Uzbek text: `localized(ru, uz, en)` (alias `_t`) in CRM settings,
# `_fail(rule, ru, uz, en)` in the KB format checker. Any `uz=` keyword argument counts as well.
PY_POSITIONAL_UZ: dict[str, int] = {"localized": 1, "_t": 1, "_fail": 2}


def _uz_value_ranges(tree: ast.AST) -> Iterator[ast.expr]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "uz":
                    yield value
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "uz":
                    yield kw.value
            func = node.func
            fname = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            index = PY_POSITIONAL_UZ.get(fname)
            if index is not None and len(node.args) > index:
                yield node.args[index]


def _text_nodes(node: ast.expr) -> Iterator[ast.expr]:
    """String-bearing nodes of a uz value; never descends into calls, comprehensions or replacement fields."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str) or isinstance(node, ast.JoinedStr):
        yield node
    elif isinstance(node, ast.IfExp):
        yield from _text_nodes(node.body)
        yield from _text_nodes(node.orelse)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        yield from _text_nodes(node.left)
        yield from _text_nodes(node.right)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            yield from _text_nodes(elt)
    elif isinstance(node, ast.Dict):
        for value in node.values:
            yield from _text_nodes(value)


def _offsets(source: str) -> list[int]:
    starts, acc = [0], 0
    for line in source.splitlines(keepends=True):
        acc += len(line)
        starts.append(acc)
    return starts


def _py_string_body(token: str) -> tuple[str, str, str] | None:
    m = re.match(r"(?is)^([rbuf]*)('''|\"\"\"|'|\")(.*)\2$", token)
    if not m or "b" in m.group(1).lower():
        return None
    return m.group(1), m.group(2), m.group(3)


def convert_py(source: str, name: str = "") -> Result:
    res = Result(source)
    if Path(name).name in PY_EXCLUDE:
        res.skipped.append(f"{name}: excluded — {PY_EXCLUDE[Path(name).name]}")
        return res
    tree = ast.parse(source)
    line_starts = _offsets(source)

    def abs_pos(line: int, col: int) -> int:
        return line_starts[line - 1] + col

    ranges: list[tuple[int, int]] = []
    for value in _uz_value_ranges(tree):
        for node in _text_nodes(value):
            assert node.end_lineno is not None and node.end_col_offset is not None
            # ast col offsets are UTF-8 byte offsets; convert via the line text
            sl = source.splitlines(keepends=True)
            s_line = sl[node.lineno - 1].encode()[: node.col_offset].decode()
            e_line = sl[node.end_lineno - 1].encode()[: node.end_col_offset].decode()
            ranges.append((abs_pos(node.lineno, len(s_line)), abs_pos(node.end_lineno, len(e_line))))
    if not ranges:
        return res

    def inside(pos: int) -> bool:
        return any(a <= pos < b for a, b in ranges)

    edits: list[tuple[int, int, str]] = []
    fdepth = 0
    brace = [0]
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        start = abs_pos(*tok.start)
        end = abs_pos(*tok.end)
        if tok.type == tokenize.FSTRING_START:
            fdepth += 1
            brace.append(0)
            continue
        if tok.type == tokenize.FSTRING_END:
            fdepth -= 1
            brace.pop()
            continue
        if fdepth and tok.type == tokenize.OP and tok.string in "{}":
            brace[-1] += 1 if tok.string == "{" else -1
            continue
        if not inside(start):
            continue
        if tok.type == tokenize.FSTRING_MIDDLE and fdepth == 1 and brace[-1] == 0:
            raw = source[start:end]
            if raw != tok.string:  # tokenize un-doubles '{{'; positions unreliable — refuse
                res.skipped.append(f"{name}:{tok.start[0]}: f-string text with literal braces")
                continue
            body = raw
            new = _convert_py_body(body)
            if new != body:
                edits.append((start, end, new))
                res.changes.append(Change(f"{name}:{tok.start[0]}", body, new))
        elif tok.type == tokenize.STRING and fdepth == 0:
            parts = _py_string_body(tok.string)
            if not parts:
                continue
            prefix, quote, body = parts
            new = _convert_py_body(body)
            if new != body:
                edits.append((start, end, prefix + quote + new + quote))
                res.changes.append(Change(f"{name}:{tok.start[0]}", body, new))
    res.text = _replace_spans(source, edits)
    ast.parse(res.text)  # still valid Python
    return res


def _convert_py_body(body: str) -> str:
    parts = re.split(r"(\\(?:N\{[^}]*\}|.))", body)
    return "".join(p if p.startswith("\\") else convert_uz(p) for p in parts)


HANDLERS: dict[str, Callable[[str, str], Result]] = {
    ".json": convert_json,
    ".po": convert_po,
    ".ts": convert_ts,
    ".py": convert_py,
}


def convert_file(path: Path, label: str | None = None) -> Result:
    handler = HANDLERS.get(path.suffix)
    if handler is None:
        raise SystemExit(f"no handler for {path}")
    return handler(path.read_text(encoding="utf-8"), label or str(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="count strings that would change")
    mode.add_argument("--diff", action="store_true", help="print a unified diff")
    mode.add_argument("--apply", action="store_true", help="rewrite the given files in place")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)

    total = 0
    for path in args.files:
        res = convert_file(path)
        total += len(res.changes)
        if args.check:
            print(f"{len(res.changes):5d}  {path}")
        elif args.diff:
            original = path.read_text(encoding="utf-8")
            sys.stdout.writelines(
                difflib.unified_diff(
                    original.splitlines(keepends=True), res.text.splitlines(keepends=True), str(path), str(path)
                )
            )
        else:
            path.write_text(res.text, encoding="utf-8")
        for note in res.skipped:
            print(f"  skipped: {note}", file=sys.stderr)
    if args.check:
        print(f"{total:5d}  total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
