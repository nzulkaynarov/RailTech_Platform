"""Слияние ранжированных списков поиска — Reciprocal Rank Fusion (ADR-0007).

score(d) = Σ_i 1 / (k + rank_i(d)), rank с 1; классическое k = 60
(Cormack, Clarke, Büttcher, SIGIR 2009). Порог релевантности к RRF-оценке
не применяется: она не откалибрована (ADR-0007).
"""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import Final

DEFAULT_K: Final = 60


@dataclass(frozen=True, slots=True)
class FusedItem[T: Hashable]:
    key: T
    score: float
    ranks: tuple[int | None, ...]


def reciprocal_rank_fusion[T: Hashable](
    rankings: Sequence[Sequence[T]], k: int = DEFAULT_K, limit: int | None = None
) -> list[FusedItem[T]]:
    """Сливает списки ключей (лучший — первый) в один, по убыванию RRF-оценки.

    Дубликаты внутри одного списка учитываются по первому вхождению. При равной
    оценке порядок детерминирован: ранги по спискам по порядку, затем ключ.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    ranks: dict[T, list[int | None]] = {}
    for list_index, ranking in enumerate(rankings):
        for position, key in enumerate(ranking, start=1):
            slots = ranks.setdefault(key, [None] * len(rankings))
            if slots[list_index] is None:
                slots[list_index] = position
    fused = [
        FusedItem(
            key=key, score=sum(1 / (k + r) for r in slots if r is not None), ranks=tuple(slots)
        )
        for key, slots in ranks.items()
    ]
    fused.sort(key=lambda item: (-item.score, _rank_key(item.ranks), str(item.key)))
    return fused if limit is None else fused[:limit]


def _rank_key(ranks: tuple[int | None, ...]) -> tuple[float, ...]:
    """Ранги по спискам по порядку; отсутствие в списке — хуже любого ранга."""
    return tuple(float("inf") if r is None else float(r) for r in ranks)
