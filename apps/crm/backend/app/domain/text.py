"""Нормализация текста вопросов (дедупликация пробелов KB, SPEC §7.1 fallback)."""

import re
import unicodedata
from typing import Final

_APOSTROPHES = re.compile(r"[‘’`ʻʼ]")
_NON_WORD = re.compile(r"[^\w']+", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize_question(text: str) -> str:
    """Ключ для upsert в `kb_gaps`: регистр, ё→е, единые апострофы, без пунктуации."""
    value = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    value = _APOSTROPHES.sub("'", value)
    value = _NON_WORD.sub(" ", value)
    return _SPACES.sub(" ", value).strip()


_SENTENCE = re.compile(r"[^.!?…]+(?:[.!?…]+|$)\s*")


def limit_words(text: str, max_words: int) -> str:
    """Не длиннее `max_words` слов: обрезка по границе предложения (SPEC §7.1, ≤ 120 слов).

    Первое предложение остаётся всегда, даже если оно само длиннее лимита.
    """
    if len(text.split()) <= max_words:
        return text
    kept: list[str] = []
    words = 0
    for sentence in _SENTENCE.findall(text):
        count = len(sentence.split())
        if kept and words + count > max_words:
            break
        kept.append(sentence)
        words += count
    return "".join(kept).rstrip()


def drop_trailing_question(text: str) -> str:
    """Убрать вопросы в конце ответа (тон, SPEC §7.1); ответ из одного вопроса не трогаем."""
    sentences = _SENTENCE.findall(text.strip())
    while len(sentences) > 1 and sentences[-1].rstrip().endswith("?"):
        sentences.pop()
    return "".join(sentences).rstrip()


_SERVICE_NAME = re.compile(
    r"@|\d|\b(test|тест|admin|админ|administrator|bot|бот|service|сервис|demo|демо|system|"
    r"user|manager|менеджер|operator|оператор)\b",
    re.IGNORECASE,
)
STAFF_FALLBACK: Final = {"ru": "менеджер", "uz": "menejer", "en": "A manager"}


def staff_name(full_name: str, language: str) -> str:
    """Имя сотрудника для клиента: полное имя человека; служебная/тестовая учётка —
    «менеджер» на языке клиента (аудит 2026-10-12)."""
    name = " ".join(full_name.split())
    if not name or _SERVICE_NAME.search(name):
        return STAFF_FALLBACK.get(language, STAFF_FALLBACK["ru"])
    return name


def ends_with_question(text: str) -> bool:
    return text.rstrip().endswith("?")
