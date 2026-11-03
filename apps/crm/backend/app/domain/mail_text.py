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
#: Разделитель подписи по RFC 3676 — «-- » с пробелом; «--» без него (строка таблицы) — не подпись.
_SIGNATURE: Final = "-- "
#: Длиннее — режем вход до нормализации: письмо до 60 МБ не должно держать разбор.
MAX_INPUT_CHARS: Final = 1_000_000


def _line(raw: str) -> str:
    """Строка без повторов пробелов и краёв; разделитель подписи «-- » сохраняется с пробелом."""
    line = _SPACES.sub(" ", raw)
    return line if line == _SIGNATURE else line.strip()


def normalize_text(raw: str) -> str:
    """Управляющие и невидимые символы прочь, неразрывные пробелы и повторы схлопнуты, пустые
    строки подряд — в одну. Разделитель подписи «-- » остаётся с пробелом (RFC 3676)."""
    text = _LINE_BREAKS.sub("\n", raw[:MAX_INPUT_CHARS].replace("\r\n", "\n").replace("\r", "\n"))
    text = _UNICODE_SPACES.sub(" ", _INVISIBLE.sub("", _CONTROL.sub("", text)))
    lines = [_line(line) for line in text.split("\n")]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()[:MAX_TEXT_CHARS].strip()


def _quoted(line: str) -> bool:
    return line.startswith(">")


def _attribution_start(lines: list[str], index: int) -> int | None:
    """«Иван пишет:» — на строке `index` или на двух («On … <почта>» + «wrote:») → её начало."""
    line = lines[index]
    if any(p.match(line) for p in _ATTRIBUTION):
        return index
    if index > 0 and _WRAPPED_END.match(line) and _WRAPPED_START.match(lines[index - 1]):
        return index - 1
    return None


def _attribution_cut(lines: list[str], run_start: int | None, html_quote: bool) -> int | None:
    """Строка «Иван пишет:» — только при подтверждённой цитате: сразу под ней начинается хвост
    из строк «>» до конца письма, а у письма из HTML — цитата-блок (`blockquote`) в конце. Обычная
    фраза «Наш директор пишет:» с текстом ниже — часть письма."""
    if run_start is not None:
        index = run_start - 1
    elif html_quote:
        index = len(lines) - 1
    else:
        return None
    while index >= 0 and not lines[index]:
        index -= 1
    return _attribution_start(lines, index) if index >= 0 else None


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


def split_quote(text: str, *, html_quote: bool = False) -> tuple[str, str]:
    """Нормализованный текст → (письмо без цитаты и подписи, свёрнутый хвост).

    Хвост — от первого признака: «-----Original Message-----», блок заголовков Outlook, строка
    «<кто> пишет:» с цитатой, «>» до конца письма, подпись после «-- ». Ответ под цитатой и ответы
    между цитатами не режутся; письмо, целиком состоящее из цитаты, остаётся как есть.
    `html_quote` — письмо пришло HTML с цитатой-блоком: подводящая строка «… пишет:» перед ним
    тоже в хвост.
    """
    lines = text.split("\n")
    signature = _signature_cut(lines)
    region = lines if signature is None else lines[:signature]  # подпись цитате не мешает
    run_start = _quote_run_cut(region)
    found = [
        c
        for c in (
            _header_cut(region),
            _attribution_cut(region, run_start, html_quote),
            run_start,
        )
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
