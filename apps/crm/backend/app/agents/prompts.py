"""Загрузка и рендер промптов из `backend/prompts/*.md` (CONVENTIONS.md §4, SPEC §7.4).

Подстановка — `string.Template` (`$name`); пользовательский текст и фрагменты KB
экранируются и попадают только внутрь XML-блоков промпта.
"""

import hashlib
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Final
from xml.sax.saxutils import escape

PROMPTS_DIR: Final = Path(__file__).resolve().parents[2] / "prompts"

LANGUAGE_NAMES: Final = {"ru": "русский", "uz": "узбекский (латиница)", "en": "английский"}


@lru_cache
def load(name: str) -> Template:
    return Template((PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"))


def version(name: str) -> str:
    """Короткий хэш содержимого — версия промпта для трейсов и Langfuse."""
    return hashlib.sha256(load(name).template.encode("utf-8")).hexdigest()[:12]


def render(name: str, **values: str) -> str:
    """Все плейсхолдеры обязательны: пропуск — KeyError, а не тихий `$x` в промпте."""
    return load(name).substitute(**values)


def xml_escape(text: str) -> str:
    return escape(text)


def xml_items(tag: str, items: list[tuple[dict[str, str], str]]) -> str:
    """`<tag attr="…">текст</tag>` построчно; атрибуты и текст экранируются."""
    lines = []
    for attrs, body in items:
        rendered = " ".join(f'{k}="{escape(v, {chr(34): "&quot;"})}"' for k, v in attrs.items())
        opening = f"<{tag} {rendered}>" if rendered else f"<{tag}>"
        lines.append(f"{opening}{escape(body)}</{tag}>")
    return "\n".join(lines)
