"""Текст письма: нормализация и выделение цитаты и подписи (W18A-P2-4). Чистые функции без I/O.

Нормализованный текст без цитаты — то, что видит сотрудник в превью и что уходит дальше (лид,
входящий документ, помощник, предзаполнение регистрации). Цитата прошлой переписки и подпись
остаются в `tail` — их показывают свёрнутыми под «…» (Gmail, Front, Help Scout, Zendesk).
"""

import re
from typing import Final

MAX_TEXT_CHARS: Final = 50_000
#: Подпись длиннее — не подпись (иначе `--` в середине письма срезал бы текст).
MAX_SIGNATURE_LINES: Final = 40

_CONTROL: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Невидимые символы рассылок (прехедер «&zwnj;&nbsp;» ×100): нулевой ширины, мягкий перенос, BOM.
_INVISIBLE: Final = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u00ad\u034f\ufeff\u180e\u061c]"
)
_LINE_BREAKS: Final = re.compile(r"[\u2028\u2029\u0085]")
_UNICODE_SPACES: Final = re.compile(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")
_SPACES: Final = re.compile(r"[ \t\f\v]+")
_BLANKS: Final = re.compile(r"\n{3,}")

_ORIGINAL: Final = re.compile(
    r"^-{2,}\s*(original message|исходное сообщение|исходное письмо|первоначальное сообщение"
    r"|asl xabar)\s*-{2,}$",
    re.IGNORECASE,
)
_RULE: Final = re.compile(r"^(_{5,}|-{5,}|={5,})$")
_HEAD_FROM: Final = re.compile(r"^(from|от|von|de)\s*:\s*\S", re.IGNORECASE)
_HEAD_DATE: Final = re.compile(r"^(sent|date|отправлено|дата|gesendet)\s*:", re.IGNORECASE)
_HEAD_SUBJECT: Final = re.compile(r"^(subject|тема|betreff)\s*:", re.IGNORECASE)
_ATTRIBUTION: Final = (
    re.compile(r"^(on|el|le|am)\s.{1,300}\b(wrote|écrit|escribió|schrieb)\s*:$", re.IGNORECASE),
    re.compile(
        r"^.{1,300}\b(пишет|писал|писала|написал|написала)\b(\s*\(а\))?[^\n:]{0,60}:$",
        re.IGNORECASE,
    ),
    re.compile(r"^.{1,300}\b(yozdi|yozgan|yozibdi)\s*:$", re.IGNORECASE),
    re.compile(r"^.{0,200}<[^<>@\s]+@[^<>\s]+>\s*:$"),
)
_WRAPPED_START: Final = re.compile(r"^(on|el|le|am)\s", re.IGNORECASE)
_WRAPPED_END: Final = re.compile(r"^(wrote|écrit|escribió|schrieb|пишет)\s*:$", re.IGNORECASE)
_SIGNATURE: Final = "--"


def normalize_text(raw: str) -> str:
    """Управляющие и невидимые символы прочь, неразрывные пробелы и повторы схлопнуты, пустые
    строки подряд — в одну."""
    text = _LINE_BREAKS.sub("\n", raw.replace("\r\n", "\n").replace("\r", "\n"))
    text = _UNICODE_SPACES.sub(" ", _INVISIBLE.sub("", _CONTROL.sub("", text)))
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()[:MAX_TEXT_CHARS].strip()


def _quoted(line: str) -> bool:
    return line.startswith(">")


def _is_attribution(lines: list[str], index: int) -> bool:
    line = lines[index]
    if any(p.match(line) for p in _ATTRIBUTION):
        return True
    return bool(
        _WRAPPED_START.match(line)
        and index + 1 < len(lines)
        and _WRAPPED_END.match(lines[index + 1])
    )


def _attribution_cut(lines: list[str]) -> int | None:
    """Первая строка «Иван пишет:», после которой идёт цитата (а не ответ под цитатой)."""
    for index in range(len(lines)):
        if not _is_attribution(lines, index):
            continue
        rest = [line for line in lines[index + 1 :] if line]
        if not rest:
            continue
        if not _quoted(rest[0]) or all(_quoted(line) for line in rest):
            return index
    return None


def _header_cut(lines: list[str]) -> int | None:
    """«-----Original Message-----» или блок «От / Отправлено / Тема» (Outlook)."""
    for index, line in enumerate(lines):
        if _ORIGINAL.match(line):
            return index
        if _HEAD_FROM.match(line):
            window = lines[index + 1 : index + 6]
            if any(_HEAD_DATE.match(w) for w in window) and any(
                _HEAD_SUBJECT.match(w) for w in window
            ):
                return index - 1 if index > 0 and _RULE.match(lines[index - 1]) else index
    return None


def _quote_run_cut(lines: list[str]) -> int | None:
    """Начало хвоста из строк «>» (до конца письма только цитата и пустые строки)."""
    start: int | None = None
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index]
        if _quoted(line):
            start = index
        elif line:
            break
    return start


def _signature_cut(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line == _SIGNATURE and len(lines) - index - 1 <= MAX_SIGNATURE_LINES:
            return index
    return None


def split_quote(text: str) -> tuple[str, str]:
    """Нормализованный текст → (письмо без цитаты и подписи, свёрнутый хвост).

    Хвост — от первого признака: «-----Original Message-----», блок заголовков Outlook, строка
    «<кто> пишет:» с цитатой, «>» до конца письма, подпись после «-- ». Ответ под цитатой и ответы
    между цитатами не режутся; письмо, целиком состоящее из цитаты, остаётся как есть.
    """
    lines = text.split("\n")
    signature = _signature_cut(lines)
    region = lines if signature is None else lines[:signature]  # подпись цитате не мешает
    found = [
        c
        for c in (_header_cut(region), _attribution_cut(region), _quote_run_cut(region))
        if c is not None
    ]
    cuts = [*found, *([signature] if signature is not None else [])]
    if not cuts:
        return text, ""
    cut = min(cuts)
    main = "\n".join(lines[:cut]).strip()
    if not main:
        return text, ""
    return main, "\n".join(lines[cut:]).strip()
