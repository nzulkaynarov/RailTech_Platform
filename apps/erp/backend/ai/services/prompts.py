"""Промпты ИИ ERP — файлы `backend/prompts/<имя>.md`, версия = хэш содержимого (ADR-0005, M1-ERP-06).

Файл — ровно системный промпт, без шапки: что в файле, то и уходит модели. Значения, которые
код подставляет при вызове (справочник единиц, потолок строк, коды находок), — плейсхолдеры
`{{имя}}`; пользовательский текст в промпт НЕ подставляется — он едет отдельным сообщением
`user` (граница «инструкция / данные»). Версия — первые 12 hex SHA-256 файла: меняется с любой
правкой, пишется в журнал вызовов (`ai.AICall.prompt_version`) и в трейс Langfuse, поэтому
по трейсу видно, какой текст промпта дал этот ответ.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
VERSION_LENGTH = 12


class PromptError(LookupError):
    """Нет файла промпта или не хватает значения плейсхолдера — ошибка кода, не модели."""


@dataclass(frozen=True)
class Prompt:
    name: str
    template: str
    version: str

    @property
    def placeholders(self) -> frozenset[str]:
        return frozenset(_PLACEHOLDER.findall(self.template))

    def render(self, **values: object) -> str:
        """Текст для модели: плейсхолдеры заменены, лишних и недостающих значений нет."""
        missing = self.placeholders - values.keys()
        extra = values.keys() - self.placeholders
        if missing or extra:
            raise PromptError(f"prompt {self.name}: missing={sorted(missing)} extra={sorted(extra)}")
        return _PLACEHOLDER.sub(lambda match: str(values[match.group(1)]), self.template).rstrip()


def prompts_dir() -> Path:
    return Path(getattr(settings, "AI_PROMPTS_DIR", None) or Path(settings.BASE_DIR) / "prompts")


def prompt_version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:VERSION_LENGTH]


@lru_cache(maxsize=64)
def load_prompt(name: str) -> Prompt:
    """Промпт по имени файла без расширения. Кэш на процесс: файлы меняются только с деплоем."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise PromptError(f"bad prompt name: {name!r}")
    path = prompts_dir() / f"{name}.md"
    try:
        template = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"prompt file not found: {path}") from exc
    return Prompt(name=name, template=template, version=prompt_version(template))


def available_prompts() -> list[str]:
    return sorted(path.stem for path in prompts_dir().glob("*.md"))
