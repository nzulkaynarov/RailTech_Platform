"""Формат документа базы знаний (M5-CRM-02): проверка при загрузке (docs/kb/FORMAT.md).

В базу знаний принимается только Markdown (`.md`) с front matter YAML. Файл готовит человек или
сторонний ИИ-агент вне системы (docs/kb/PROMPT.md); здесь он только проверяется и режется на чанки.
Каждое нарушение — `ValidationFailedError(reason=kb_format)` с правилом `rule` и текстом
«что исправить» на ru/uz/en (`details.detail` — ru, `details.messages` — все три).
"""

# ruff: noqa: E501 — каталог сообщений ru/uz/en читается лучше без переносов
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final

import yaml

from app.domain.errors import Reason, ValidationFailedError

MAX_DOCUMENT_BYTES: Final = 100 * 1024
LANGUAGES: Final = ("ru", "uz", "en")
REQUIRED_FIELDS: Final = ("title", "language", "source", "updated")
FORMAT_URL: Final = "docs/kb/FORMAT.md"

_FRONT_MATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_FENCE = re.compile(r"^ {0,3}(```|~~~)")
_H1 = re.compile(r"^# +\S")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<img\b", re.IGNORECASE)
_FILE_LINK = re.compile(
    r"\[[^\]]*\]\([^)\s]+\.(?:pdf|docx?|xlsx?|pptx?|zip|rar|png|jpe?g|gif|webp)(?:[?#][^)]*)?\)",
    re.IGNORECASE,
)

Messages = dict[str, str]


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    meta: dict[str, Any]
    body: str


def split_front_matter(text: str) -> ParsedDocument:
    """Отделяет front matter от тела; без него `meta` пуст (ручной Markdown)."""
    match = _FRONT_MATTER.match(text.lstrip("﻿"))
    if match is None:
        return ParsedDocument({}, text)
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        meta = None
    body = text.lstrip("﻿")[match.end() :]
    return ParsedDocument(meta if isinstance(meta, dict) else {}, body)


def _fail(rule: str, ru: str, uz: str, en: str, **extra: object) -> ValidationFailedError:
    messages: Messages = {"ru": ru, "uz": uz, "en": en}
    return ValidationFailedError(
        f"kb format: {rule}: {en}",
        reason=Reason.KB_FORMAT,
        field="file",
        rule=rule,
        detail=ru,
        messages=messages,
        format_doc=FORMAT_URL,
        **extra,
    )


def not_markdown_error() -> ValidationFailedError:
    messages: Messages = {
        "ru": "Принимаются только документы Markdown (.md) по формату базы знаний — см. инструкцию",
        "uz": "Faqat bilimlar bazasi formatidagi Markdown (.md) hujjatlari qabul qilinadi — "
        "yo‘riqnomaga qarang",
        "en": "Only Markdown (.md) documents in the knowledge base format are accepted — "
        "see the instructions",
    }
    return ValidationFailedError(
        f"only .md is accepted: {messages['en']}",
        reason=Reason.KB_MARKDOWN_ONLY,
        field="file",
        messages=messages,
        format_doc=FORMAT_URL,
    )


@dataclass(slots=True)
class _Checker:
    text: str
    language: str | None
    fields: list[str] = field(default_factory=list)

    def run(self) -> ParsedDocument:
        raw = self.text
        if len(raw.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            kb = MAX_DOCUMENT_BYTES // 1024
            raise _fail(
                "size",
                f"Документ больше {kb} КБ — разбейте его на несколько документов по темам",
                f"Hujjat {kb} KB dan katta — uni mavzular bo‘yicha bir nechta hujjatga bo‘ling",
                f"The document is larger than {kb} KB — split it into several documents by topic",
            )
        if _FRONT_MATTER.match(raw.lstrip("﻿")) is None:
            raise _fail(
                "front_matter_missing",
                "В начале файла нет front matter: добавьте блок между строками --- "
                "с полями title, language, source, updated",
                "Fayl boshida front matter yo‘q: --- qatorlari orasiga title, language, "
                "source, updated maydonlarini qo‘shing",
                "The file has no front matter: add a block between --- lines with the fields "
                "title, language, source, updated",
            )
        parsed = split_front_matter(raw)
        if not parsed.meta:
            raise _fail(
                "front_matter_invalid",
                "Front matter не разобран: это должен быть корректный YAML вида «поле: значение»",
                "Front matter o‘qilmadi: «maydon: qiymat» ko‘rinishidagi to‘g‘ri YAML bo‘lishi kerak",
                "Front matter could not be parsed: it must be valid YAML of the form 'field: value'",
            )
        self._fields(parsed.meta)
        self._body(parsed.body)
        return parsed

    def _fields(self, meta: dict[str, Any]) -> None:
        for name in REQUIRED_FIELDS:
            value = meta.get(name)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise _fail(
                    "field_missing",
                    f"В front matter нет обязательного поля «{name}»",
                    f"Front matterda majburiy «{name}» maydoni yo‘q",
                    f"Front matter is missing the required field '{name}'",
                    missing=name,
                )
        for name in ("title", "source"):
            if not isinstance(meta[name], str):
                raise _fail(
                    "field_type",
                    f"Поле «{name}» должно быть строкой",
                    f"«{name}» maydoni matn bo‘lishi kerak",
                    f"The field '{name}' must be a string",
                    missing=name,
                )
        language = meta["language"]
        if language not in LANGUAGES:
            raise _fail(
                "language_invalid",
                "Поле language должно быть одним из: ru, uz, en",
                "language maydoni quyidagilardan biri bo‘lishi kerak: ru, uz, en",
                "The language field must be one of: ru, uz, en",
            )
        if self.language is not None and language != self.language:
            raise _fail(
                "language_mismatch",
                f"Язык в файле ({language}) не совпадает с выбранным в форме ({self.language})",
                f"Fayldagi til ({language}) formada tanlangan til ({self.language}) bilan mos emas",
                f"The language in the file ({language}) differs from the one chosen in the "
                f"form ({self.language})",
            )
        updated = meta["updated"]
        if isinstance(updated, datetime) or not (
            isinstance(updated, date)
            or (isinstance(updated, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", updated))
        ):
            raise _fail(
                "updated_invalid",
                "Поле updated — дата в виде ГГГГ-ММ-ДД, например 2026-10-21",
                "updated maydoni — YYYY-MM-DD ko‘rinishidagi sana, masalan 2026-10-21",
                "The updated field must be a date as YYYY-MM-DD, e.g. 2026-10-21",
            )
        tags = meta.get("tags")
        if tags is not None and not (
            isinstance(tags, list) and all(isinstance(tag, str) for tag in tags)
        ):
            raise _fail(
                "tags_invalid",
                "Поле tags — список строк: tags: [доставка, гарантия]",
                "tags maydoni — matnlar ro‘yxati: tags: [yetkazish, kafolat]",
                "The tags field must be a list of strings: tags: [delivery, warranty]",
            )

    def _body(self, body: str) -> None:
        h1_count = 0
        in_code = False
        for line in body.splitlines():
            if _FENCE.match(line):
                in_code = not in_code
                continue
            if in_code:
                continue
            if _H1.match(line):
                h1_count += 1
            if _IMAGE.search(line):
                raise _fail(
                    "images",
                    "В документе есть картинка — уберите её и опишите смысл словами",
                    "Hujjatda rasm bor — uni olib tashlang va ma’nosini so‘z bilan yozing",
                    "The document contains an image — remove it and describe it in words",
                )
            if _FILE_LINK.search(line):
                raise _fail(
                    "file_links",
                    "В документе есть ссылка на файл — уберите её, нужное перенесите в текст",
                    "Hujjatda faylga havola bor — uni olib tashlang, kerakli ma’lumotni matnga o‘tkazing",
                    "The document links to a file — remove the link and move the content into the text",
                )
        if h1_count == 0:
            raise _fail(
                "h1_missing",
                "Нет заголовка первого уровня: после front matter добавьте строку «# Название»",
                "Birinchi darajali sarlavha yo‘q: front matterdan keyin «# Nomi» qatorini qo‘shing",
                "There is no level-1 heading: add a '# Title' line after the front matter",
            )
        if h1_count > 1:
            raise _fail(
                "h1_multiple",
                "Заголовков первого уровня («# …») должен быть ровно один; "
                "разделы оформляйте как «##» и «###»",
                "Birinchi darajali sarlavha («# …») aynan bitta bo‘lishi kerak; "
                "bo‘limlar uchun «##» va «###» ishlating",
                "There must be exactly one level-1 heading ('# …'); use '##' and '###' for sections",
            )


def validate_document(content: bytes, *, language: str | None = None) -> ParsedDocument:
    """Проверяет файл по docs/kb/FORMAT.md; при нарушении — `ValidationFailedError`."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise _fail(
            "encoding",
            "Файл не в кодировке UTF-8 — сохраните его как UTF-8",
            "Fayl UTF-8 kodirovkasida emas — uni UTF-8 sifatida saqlang",
            "The file is not UTF-8 — save it as UTF-8",
        ) from None
    return _Checker(text, language).run()
