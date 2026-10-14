"""Шаблоны писем сотрудникам из `backend/templates/email/<name>.<lang>.md` (M3-CRM-08).

Формат файла: первая строка `Subject: …`, пустая строка, затем тело (plain text; Markdown — только
для читаемости в почтовом клиенте). Подстановка — `string.Template` (`$name`), как у промптов:
пропущенный плейсхолдер — `KeyError`, а не тихий `$x` в письме. Языка нет — русский (Q-012).
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Final

TEMPLATES_DIR: Final = Path(__file__).resolve().parents[2] / "templates" / "email"
LANGUAGES: Final = ("ru", "uz", "en")
DEFAULT_LANGUAGE: Final = "ru"
TEMPLATES: Final = ("invite", "password_reset", "test", "service_alert")
_SUBJECT_PREFIX: Final = "Subject:"


class TemplateMissingError(LookupError):
    """Нет файла шаблона ни на запрошенном языке, ни на русском."""


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    body: str
    lang: str


@dataclass(frozen=True, slots=True)
class _Loaded:
    subject: Template
    body: Template


def resolve_language(lang: str | None) -> str:
    code = (lang or "").strip().lower()[:2]
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def template_path(name: str, lang: str) -> Path:
    """Файл шаблона на языке; нет — русский; нет и его — `TemplateMissingError`."""
    for code in (lang, DEFAULT_LANGUAGE):
        path = TEMPLATES_DIR / f"{name}.{code}.md"
        if path.is_file():
            return path
    raise TemplateMissingError(f"email template '{name}' is missing")


@lru_cache
def _load(path: Path) -> _Loaded:
    text = path.read_text(encoding="utf-8")
    first, _, rest = text.partition("\n")
    if not first.startswith(_SUBJECT_PREFIX):
        raise TemplateMissingError(f"{path.name}: first line must be 'Subject: …'")
    subject = first.removeprefix(_SUBJECT_PREFIX).strip()
    return _Loaded(Template(subject), Template(rest.lstrip("\n").rstrip() + "\n"))


def render(name: str, lang: str | None, **values: str) -> RenderedEmail:
    """Тема и тело на языке сотрудника (нет словаря — русский). Все плейсхолдеры обязательны."""
    code = resolve_language(lang)
    path = template_path(name, code)
    loaded = _load(path)
    return RenderedEmail(
        subject=loaded.subject.substitute(**values)[:255],
        body=loaded.body.substitute(**values),
        lang=path.suffixes[0].lstrip("."),
    )
