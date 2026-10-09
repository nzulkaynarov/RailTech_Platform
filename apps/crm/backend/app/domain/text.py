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
