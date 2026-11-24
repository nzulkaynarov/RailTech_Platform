# ruff: noqa: E501
"""Узбекская латиница нового алфавита (владелец 2026-11-17): Ö Ğ Ş Ç вместо Oʻ Gʻ Sh Ch.

`convert_uz` — чистая идемпотентная функция; боту нужна, чтобы привести ответ модели к одному алфавиту
(модель пишет по-старому: o'zbekcha, qo'ng'iroq, shartnoma). Те же правила использует разовый скрипт
`scripts/uz_new_alphabet.py` (правит файлы репозитория); тест `tests/unit/domain/test_uz_alphabet.py`
следит, чтобы оба не разошлись. Бренды, аббревиатуры, коды, URL и плейсхолдеры не трогаются.
"""

from __future__ import annotations

import re

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

_BRAND_RE = re.compile(
    r"(?<![\w])(?:" + "|".join(re.escape(b) for b in sorted(BRANDS, key=len, reverse=True)) + r")"
)
_EXCEPTION_RE = re.compile(
    r"(?<![\w])(?:"
    + "|".join(re.escape(e) for e in sorted(EXCEPTIONS, key=len, reverse=True))
    + r")(?![\w])",
    re.IGNORECASE,
)

# oʻ / gʻ in any apostrophe variant. A letter must follow; gʻ may also end a word after a vowel («togʻ»).
_OG_RE = re.compile(
    rf"([oOgG])[{_APOS}](?=[{_LETTER}])|(?<=[aeiouAEIOU])([gG])[{_APOS}](?![{_LETTER}{_APOS}])"
)
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
_GLOTTAL_RE = re.compile(
    rf"(?<![{_LETTER}])([{_LETTER}]+)([\u02bb\u2018\u2019'`])(?=([{_LETTER}])?)"
)
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
