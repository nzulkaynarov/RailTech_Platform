"""Нормализация текста вопросов (дедупликация пробелов KB, SPEC §7.1 fallback)."""

import re
import unicodedata

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
