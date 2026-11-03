"""Входящая почта общего ящика (W18A-P2, B-INB-5): разбор письма, вложения, подсказка помощника.

Чистые функции без I/O. Письмо RFC 5322 → `ParsedMail`: Message-ID (ключ дедупликации), отправитель,
тема, дата, цепочка (`In-Reply-To`, `References`), тело только текстом (HTML → текст без разметки,
скриптов и стилей; в интерфейсе показывается как текст) и вложения по белому списку типов EDS
(PDF, изображения, Office) с пределом размера и числа — остальные в `skipped` с причиной.

Помощник (DECISIONS 2026-10-28, «код решает, модель предлагает»): модель возвращает только тип из
минимального набора и суть; предложение действия по типу выбирает код (`SUGGESTED_ACTION`), действие
подтверждает человек.
"""

import hashlib
import json
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Final, Literal, get_args

Kind = Literal["buyer", "official", "supplier_doc", "other"]
Action = Literal["register", "lead", "archive"]
SkipReason = Literal["type", "size", "count"]

KINDS: Final[tuple[Kind, ...]] = get_args(Kind)
#: Предложение действия по типу письма — решает код, не модель.
SUGGESTED_ACTION: Final[dict[Kind, Action]] = {
    "buyer": "lead",
    "official": "register",
    "supplier_doc": "register",
    "other": "archive",
}

# Белый список — типы, которые принимает EDS (`apps/eds/app/services/files.py`, ALLOWED):
# вложение письма можно без перекодирования приложить к ВХ.
_OOXML: Final = "application/vnd.openxmlformats-officedocument."
ALLOWED_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/tiff",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        f"{_OOXML}wordprocessingml.document",
        f"{_OOXML}spreadsheetml.sheet",
        f"{_OOXML}presentationml.presentation",
    }
)
MAX_FILE_BYTES: Final = 25 * 1024 * 1024  # как предел файла EDS
MAX_FILES: Final = 20
MAX_TEXT_CHARS: Final = 50_000
MAX_SUBJECT_CHARS: Final = 300
SUMMARY_MAX_CHARS: Final = 300
_INN: Final = re.compile(r"(?<!\d)(\d{9})(?!\d)")
_CONTROL: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NAME_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f/\\]")
_BLANKS: Final = re.compile(r"\n{3,}")
_SPACES: Final = re.compile(r"[ \t\r\f\v]+")


@dataclass(frozen=True, slots=True)
class MailFile:
    name: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class SkippedFile:
    name: str
    reason: SkipReason


@dataclass(frozen=True, slots=True)
class ParsedMail:
    message_id: str
    from_email: str
    from_name: str
    to: tuple[str, ...]
    subject: str
    sent_at: datetime | None
    in_reply_to: str | None
    references: str | None
    text: str
    files: tuple[MailFile, ...] = ()
    skipped: tuple[SkippedFile, ...] = field(default_factory=tuple)


class _TextExtractor(HTMLParser):
    """HTML → текст: без тегов, `script`/`style`/`head`; блоки — переводами строк."""

    _SKIP: Final = frozenset({"script", "style", "head", "title", "noscript", "template"})
    _BREAK: Final = frozenset(
        {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return clean_text(parser.text())


def clean_text(raw: str) -> str:
    """Управляющие символы прочь, пробелы схлопнуты, не больше двух пустых строк подряд."""
    text = _CONTROL.sub("", raw.replace("\r\n", "\n"))
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()[:MAX_TEXT_CHARS]


def clean_name(raw: str | None) -> str:
    name = _NAME_CONTROL.sub("_", (raw or "").strip())[:255].strip(" .")
    return name or "file"


def resolve_type(declared: str, name: str) -> str:
    base = declared.split(";")[0].strip().lower()
    if base in ("", "application/octet-stream"):
        base = (mimetypes.guess_type(name)[0] or base).lower()
    return base


def normalize_message_id(raw: str | None, fallback: bytes) -> str:
    """Message-ID без пробелов и угловых скобок; нет заголовка — отпечаток содержимого письма."""
    value = (raw or "").strip().strip("<>").strip()
    if value and " " not in value:
        return value[:500]
    return "sha256-" + hashlib.sha256(fallback).hexdigest()


def _header(message: EmailMessage, name: str) -> str:
    try:
        value = message.get(name)
    except (ValueError, IndexError):  # битый заголовок не роняет разбор
        return ""
    return _CONTROL.sub("", str(value or "")).strip()


def _sent_at(message: EmailMessage) -> datetime | None:
    raw = _header(message, "Date")
    if not raw:
        return None
    try:
        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    return moment if moment.tzinfo is not None else None


def _body(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeError, AssertionError):
        payload = part.get_payload(decode=True)
        content = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else ""
    if not isinstance(content, str):
        return ""
    if part.get_content_type() == "text/html":
        return html_to_text(content)
    return clean_text(content)


def _files(message: EmailMessage) -> tuple[tuple[MailFile, ...], tuple[SkippedFile, ...]]:
    files: list[MailFile] = []
    skipped: list[SkippedFile] = []
    for part in message.iter_attachments():
        if not isinstance(part, EmailMessage) or part.is_multipart():
            continue
        name = clean_name(part.get_filename())
        content_type = resolve_type(part.get_content_type(), name)
        payload = part.get_payload(decode=True)
        data = payload if isinstance(payload, bytes) else b""
        reason: SkipReason | None = None
        if content_type not in ALLOWED_TYPES:
            reason = "type"
        elif len(data) > MAX_FILE_BYTES:
            reason = "size"
        elif len(files) >= MAX_FILES:
            reason = "count"
        if reason is None:
            files.append(MailFile(name, content_type, data))
        else:
            skipped.append(SkippedFile(name, reason))
    return tuple(files), tuple(skipped)


def parse_message(raw: bytes) -> ParsedMail:
    message = message_from_bytes(raw, policy=policy.default)
    if not isinstance(message, EmailMessage):  # policy.default всегда даёт EmailMessage
        raise TypeError(type(message).__name__)
    senders = getaddresses([_header(message, "From")])
    from_name, from_email = senders[0] if senders else ("", "")
    to = tuple(
        addr.strip().lower()
        for _, addr in getaddresses([_header(message, "To"), _header(message, "Cc")])
        if addr.strip()
    )
    files, skipped = _files(message)
    return ParsedMail(
        message_id=normalize_message_id(_header(message, "Message-ID"), raw),
        from_email=from_email.strip().lower()[:255],
        from_name=from_name.strip()[:255],
        to=to[:20],
        subject=_header(message, "Subject")[:MAX_SUBJECT_CHARS],
        sent_at=_sent_at(message),
        in_reply_to=_header(message, "In-Reply-To")[:998] or None,
        references=_header(message, "References")[:4000] or None,
        text=_body(message),
        files=files,
        skipped=skipped,
    )


def find_inns(text: str) -> list[str]:
    """ИНН юрлица Узбекистана (9 цифр) из текста — подсказка связи с клиентом, без проверки."""
    seen: list[str] = []
    for match in _INN.finditer(text):
        value = match.group(1)
        if value not in seen:
            seen.append(value)
    return seen[:5]


@dataclass(frozen=True, slots=True)
class AssistVerdict:
    kind: Kind
    summary: str
    action: Action


#: Как модели пишут тип письма (ru/en, разный регистр) → код. Сверено с `prompts/mail_assist.md`.
KIND_SYNONYMS: Final[dict[str, Kind]] = {
    "buyer": "buyer",
    "customer": "buyer",
    "client": "buyer",
    "покупатель": "buyer",
    "клиент": "buyer",
    "official": "official",
    "official_letter": "official",
    "официальное": "official",
    "официальное_письмо": "official",
    "supplier_doc": "supplier_doc",
    "supplier": "supplier_doc",
    "supplier_document": "supplier_doc",
    "invoice": "supplier_doc",
    "поставщик": "supplier_doc",
    "документ_поставщика": "supplier_doc",
    "счёт_или_документ_поставщика": "supplier_doc",
    "счет_или_документ_поставщика": "supplier_doc",
    "other": "other",
    "прочее": "other",
    "другое": "other",
    "spam": "other",
    "спам": "other",
}
_FENCE: Final = re.compile(r"```[a-zA-Z]*\s*(.*?)```", re.DOTALL)
_KIND_SEP: Final = re.compile(r"[\s\-]+")


def _first_object(raw: str) -> tuple[dict[str, object] | None, str | None]:
    """Первый JSON-объект ответа: без ограждений ``` и ```json, текст вокруг — прочь."""
    fenced = _FENCE.search(raw)
    text = fenced.group(1) if fenced else raw
    decoder = json.JSONDecoder()
    seen_json = False
    for start, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            continue
        seen_json = True
        if isinstance(value, dict):
            return value, None
    return None, "no_object" if seen_json else "not_json"


def _kind(value: object) -> Kind | None:
    if not isinstance(value, str):
        return None
    key = _KIND_SEP.sub("_", value.strip().strip(".«»\"'").lower())
    return KIND_SYNONYMS.get(key)


def parse_assist_reason(raw: str | None) -> tuple[AssistVerdict | None, str | None]:
    """Ответ модели → подсказка или причина отказа словом-кодом (в лог, без текста письма):
    `not_json`, `no_object`, `unknown_kind=<значение>`, `empty_summary`."""
    data, problem = _first_object(raw or "")
    if data is None:
        return None, problem
    raw_kind = data.get("kind")
    kind = _kind(raw_kind)
    if kind is None:
        shown = _CONTROL.sub("", str(raw_kind))[:32]
        return None, f"unknown_kind={shown}"
    summary = data.get("summary")
    text = (
        clean_text(summary).replace("\n", " ")[:SUMMARY_MAX_CHARS].strip()
        if isinstance(summary, str)
        else ""
    )
    if not text:
        return None, "empty_summary"
    return AssistVerdict(kind, text, SUGGESTED_ACTION[kind]), None


def parse_assist(raw: str | None) -> AssistVerdict | None:
    """Ответ модели `{"kind": …, "summary": …}` → подсказка; неизвестный тип или мусор — None."""
    return parse_assist_reason(raw)[0]


def reply_subject(subject: str) -> str:
    """«Re: тема» без накопления «Re: Re:»."""
    base = subject.strip()
    if re.match(r"^(re|ответ)\s*:", base, flags=re.IGNORECASE):
        return base[:255]
    return f"Re: {base}"[:255] if base else "Re:"


def thread_references(message_id: str, references: str | None) -> str:
    """`References` ответа: прежняя цепочка + Message-ID письма, на которое отвечаем."""
    own = f"<{message_id}>"
    chain = (references or "").split()
    if own not in chain:
        chain.append(own)
    return " ".join(chain[-20:])
