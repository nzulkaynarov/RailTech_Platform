"""Имя файла при скачивании — одно правило (ПРОСМ-2, решение владельца 2026-11-26).

`<Вид> № <Номер> от <дата> — <Контрагент>.<расширение>`: частей, которых нет, не будет — вместе
со своим словом (`Договор № 12.pdf`). Имя собирает только эта функция; своих шаблонов вида
`f"{id}.pdf"` в маршрутах нет. Заголовок `Content-Disposition` — тоже отсюда (ASCII-имя и UTF-8).
"""

import datetime as dt
import re
import unicodedata
from urllib.parse import quote

_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_SPACES = re.compile(r"\s+")
_SAFE_EXTENSIONS = frozenset({"pdf", "jpg", "jpeg", "png", "webp", "docx", "xlsx", "bin"})
MAX_STEM = 140


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return _SPACES.sub(" ", _FORBIDDEN.sub(" ", text)).strip(" .")


def document_file_name(
    kind: str,
    number: str | int | None = None,
    date: dt.date | dt.datetime | None = None,
    counterparty: str | None = None,
    ext: str = "pdf",
) -> str:
    """«Договор № ДП-12 от 18.11.2026 — ООО Ромашка.pdf»; расширение из белого списка, иначе bin."""
    stem = _clean(kind) or "Документ"
    if number is not None and _clean(str(number)):
        stem += f" № {_clean(str(number))}"
    if date is not None:
        stem += f" от {date:%d.%m.%Y}"
    who = _clean(counterparty or "")
    if who:
        stem += f" — {who}"
    stem = stem[:MAX_STEM].rstrip(" .—")
    clean_ext = ext.lower().lstrip(".")
    return f"{stem}.{clean_ext if clean_ext in _SAFE_EXTENSIONS else 'bin'}"


def content_disposition(name: str, disposition: str = "attachment") -> str:
    """Заголовок: ASCII-запасное имя и `filename*=UTF-8` — безопасно, кириллица доходит."""
    stem, _, ext = name.rpartition(".")
    plain = unicodedata.normalize("NFKD", stem or name).encode("ascii", "ignore").decode()
    ascii_name = (_clean(plain) or "file") + (f".{ext}" if stem else "")
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"
