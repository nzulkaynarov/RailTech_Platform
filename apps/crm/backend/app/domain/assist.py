"""Проверки ИИ-помощи менеджеру (Q-019): решает код, а не модель (SPEC §1.3). Чистые функции.

- «Улучшить» не добавляет фактов: в результате нет чисел, которых не было в тексте менеджера.
- «Черновик» не выдумывает цены и числа: предложения с числами не из базы знаний и истории
  выбрасываются.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from app.domain.numbers import unsupported_numbers

_SENTENCE_END: Final = re.compile(r"(?<=[.!?…])\s+")
# Разряды через любой пробел (в т. ч. неразрывный): «1 200 000» = «1200000».
_THOUSANDS: Final = re.compile(r"(?<=\d)\s(?=\d{3}(?!\d))")


def _compact(text: str) -> str:
    return _THOUSANDS.sub("", text)


def may_assist(*, assigned_user_id: int | None, user_id: int, is_admin: bool) -> bool:
    """ИИ-помощь при ответе — как сам ответ: ответственный за лида или админ."""
    return is_admin or (assigned_user_id is not None and assigned_user_id == user_id)


def improve_adds_numbers(original: str, improved: str) -> bool:
    """В улучшенном тексте есть число, которого не было у менеджера (цена, дата, срок)."""
    return bool(unsupported_numbers(_compact(improved), [_compact(original)]))


@dataclass(frozen=True, slots=True)
class DraftCheck:
    text: str
    removed: int


def strip_unsupported(draft: str, sources: Iterable[str]) -> DraftCheck:
    """Убрать предложения черновика с числами, которых нет в источниках (KB, история)."""
    known = [_compact(source) for source in sources]
    kept: list[str] = []
    removed = 0
    for paragraph in draft.split("\n"):
        sentences = [s for s in _SENTENCE_END.split(paragraph) if s]
        good = [s for s in sentences if not unsupported_numbers(_compact(s), known)]
        removed += len(sentences) - len(good)
        if good or not sentences:
            kept.append(" ".join(good))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return DraftCheck(text=text, removed=removed)
