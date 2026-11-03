"""Входящая почта общего ящика (W18A-P2, B-INB-5): разбор письма, вложения, подсказка помощника.

Чистые функции без I/O. Письмо RFC 5322 → `ParsedMail`: Message-ID (ключ дедупликации), отправитель,
тема, дата, цепочка (`In-Reply-To`, `References`), тело текстом (нормализованным, без цитаты и
подписи — W18A-P2-4: `domain/mail_text.py`; цитата и подпись — `text_tail`), безопасная HTML-версия
(`domain/mail_html.py`) и вложения по белому списку типов EDS
(PDF, изображения, Office) с пределом размера и числа — остальные в `skipped` с причиной.

Помощник (DECISIONS 2026-10-28, «код решает, модель предлагает»): модель возвращает только тип из
минимального набора и суть; предложение действия по типу выбирает код (`SUGGESTED_ACTION`), действие
подтверждает человек.
"""

import hashlib
import json
import mimetypes
import re
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage, MIMEPart
from email.utils import getaddresses, parsedate_to_datetime
from typing import Final, Literal, get_args

from app.domain.mail_html import InlineImage, SafeHtml, html_text_parts, sanitize_html
from app.domain.mail_text import MAX_TEXT_CHARS, normalize_text, split_quote

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
MAX_SUBJECT_CHARS: Final = 300
SUMMARY_MAX_CHARS: Final = 300
_INN: Final = re.compile(r"(?<!\d)(\d{9})(?!\d)")
_CONTROL: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NAME_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f/\\]")


@dataclass(frozen=True, slots=True)
class MailFile:
    name: str
    content_type: str
    data: bytes
    content_id: str | None = None  # Content-ID встроенной картинки (`cid:` в HTML), без скобок
    inline: bool = False  # картинка встроена в HTML письма — в списке вложений не показывается


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
    cc: tuple[str, ...]
    subject: str
    sent_at: datetime | None
    in_reply_to: str | None
    references: str | None
    text: str
    files: tuple[MailFile, ...] = ()
    text_tail: str = ""  # цитата прошлой переписки и подпись — свёрнуты под «…»
    html: SafeHtml | None = None
    skipped: tuple[SkippedFile, ...] = field(default_factory=tuple)


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


def _content(part: MIMEPart | None) -> str:
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeError, AssertionError):
        payload = part.get_payload(decode=True)
        content = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else ""
    return content if isinstance(content, str) else ""


def _text_parts(plain: str | None, html: str | None) -> tuple[str, str]:
    """(текст без цитаты и подписи, свёрнутый хвост). Есть текстовая часть — она; иначе текст из
    HTML (цитата — блок `blockquote`/`gmail_quote` в конце письма, потом те же признаки по
    строкам). Тело, целиком состоящее из цитаты, — это и есть текст письма."""
    if plain is not None:
        return split_quote(normalize_text(plain))
    if html is None:
        return "", ""
    main_raw, quoted_raw = html_text_parts(html)
    quoted = normalize_text(quoted_raw)
    main, tail = split_quote(normalize_text(main_raw), html_quote=bool(quoted))
    return main, "\n\n".join(part for part in (tail, quoted) if part)[:MAX_TEXT_CHARS]


def _bodies(message: EmailMessage, files: tuple[MailFile, ...]) -> tuple[str, str, SafeHtml | None]:
    plain_part = message.get_body(preferencelist=("plain",))
    html_part = message.get_body(preferencelist=("html",))
    plain = _content(plain_part) if plain_part is not None else None
    html = _content(html_part) if html_part is not None else None
    text, tail = _text_parts(plain, html)
    inline = {f.content_id: InlineImage(f.content_type, f.data) for f in files if f.content_id}
    safe = sanitize_html(html, inline) if html else None
    return text, tail, safe


def _related_images(part: EmailMessage) -> Iterator[EmailMessage]:
    """Встроенные картинки с Content-ID из вложенных `multipart/*`; внутрь приложенных писем
    (`message/rfc822`) не заходим: чужие картинки не должны подменять картинки этого письма."""
    for sub in part.iter_parts():
        if not isinstance(sub, EmailMessage) or sub.get_content_type() == "message/rfc822":
            continue
        if sub.is_multipart():
            yield from _related_images(sub)
        elif sub.get_content_maintype() == "image" and _header(sub, "Content-ID"):
            yield sub


def _file_parts(message: EmailMessage) -> list[EmailMessage]:
    """Вложения письма и встроенные картинки из вложенного `multipart/related` (рассылка
    `alternative[plain, related[html, image]]`), которые `iter_attachments` не отдаёт."""
    parts = [p for p in message.iter_attachments() if isinstance(p, EmailMessage)]
    seen = {id(p) for p in parts}
    parts.extend(p for p in _related_images(message) if id(p) not in seen)
    return parts


def _files(message: EmailMessage) -> tuple[tuple[MailFile, ...], tuple[SkippedFile, ...]]:
    files: list[MailFile] = []
    skipped: list[SkippedFile] = []
    for part in _file_parts(message):
        if part.is_multipart():
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
            cid = _header(part, "Content-ID").strip().strip("<>").strip().lower()
            files.append(MailFile(name, content_type, data, cid or None))
        else:
            skipped.append(SkippedFile(name, reason))
    return tuple(files), tuple(skipped)


def _addresses(message: EmailMessage, name: str) -> tuple[str, ...]:
    """Адреса заголовка («Кому» и «Копия» хранятся раздельно, W18A-P2-3), в нижнем регистре."""
    found = (addr.strip().lower() for _, addr in getaddresses([_header(message, name)]))
    return tuple(dict.fromkeys(a for a in found if a))


def parse_message(raw: bytes) -> ParsedMail:
    message = message_from_bytes(raw, policy=policy.default)
    if not isinstance(message, EmailMessage):  # policy.default всегда даёт EmailMessage
        raise TypeError(type(message).__name__)
    senders = getaddresses([_header(message, "From")])
    from_name, from_email = senders[0] if senders else ("", "")
    to = _addresses(message, "To")
    cc = _addresses(message, "Cc")
    files, skipped = _files(message)
    text, tail, safe_html = _bodies(message, files)
    if safe_html is not None and safe_html.inlined:
        files = tuple(
            replace(f, inline=True) if f.content_id in safe_html.inlined else f for f in files
        )
    return ParsedMail(
        message_id=normalize_message_id(_header(message, "Message-ID"), raw),
        from_email=from_email.strip().lower()[:255],
        from_name=from_name.strip()[:255],
        to=to[:20],
        cc=cc[:20],
        subject=_header(message, "Subject")[:MAX_SUBJECT_CHARS],
        sent_at=_sent_at(message),
        in_reply_to=_header(message, "In-Reply-To")[:998] or None,
        references=_header(message, "References")[:4000] or None,
        text=text,
        files=files,
        skipped=skipped,
        text_tail=tail,
        html=safe_html,
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


def parse_assist(raw: str) -> AssistVerdict | None:
    """Ответ модели `{"kind": …, "summary": …}` → подсказка; неизвестный тип или мусор — None."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    kind = data.get("kind")
    summary = data.get("summary")
    if kind not in KINDS or not isinstance(summary, str):
        return None
    text = normalize_text(summary).replace("\n", " ")[:SUMMARY_MAX_CHARS].strip()
    if not text:
        return None
    return AssistVerdict(kind, text, SUGGESTED_ACTION[kind])


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
