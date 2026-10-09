"""Поиск словарных совпадений (стоп-слова, конкуренты, просьба о человеке)."""

import re
from collections.abc import Iterable

from app.domain.text import normalize_question


def find_terms(text: str, terms: Iterable[str]) -> list[str]:
    """Термины из словаря, встречающиеся в тексте целым словом/фразой (без учёта регистра).

    `основа*` совпадает с любой словоформой: «firibgar*» → «firibgarsiz», «мошенни*» →
    «мошенники», «мошенничество». Без звёздочки — только целое слово («суд» ≠ «судя»).
    """
    haystack = f" {normalize_question(text)} "
    found: list[str] = []
    for term in terms:
        stem = term.strip().endswith("*")
        needle = normalize_question(term.strip().rstrip("*"))
        ending = r"\w*" if stem else ""
        if needle and re.search(rf"(?<!\w){re.escape(needle)}{ending}(?!\w)", haystack):
            found.append(term)
    return found
