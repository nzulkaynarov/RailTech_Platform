"""Поиск словарных совпадений (стоп-слова, конкуренты, просьба о человеке)."""

import re
from collections.abc import Iterable

from app.domain.text import normalize_question


def find_terms(text: str, terms: Iterable[str]) -> list[str]:
    """Термины из словаря, встречающиеся в тексте целым словом/фразой (без учёта регистра)."""
    haystack = f" {normalize_question(text)} "
    found: list[str] = []
    for term in terms:
        needle = normalize_question(term)
        if needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
            found.append(term)
    return found
